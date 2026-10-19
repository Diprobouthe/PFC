"""PostgreSQL regression for the Round -> Match lineup-lock contract.

Uses independent real PostgreSQL connections. SQLite is intentionally skipped:
it cannot reproduce row-level FOR UPDATE contention.
"""

from __future__ import annotations

import threading
import time
from datetime import timedelta

from django.db import connection, connections, transaction
from django.test import TransactionTestCase, skipUnlessDBFeature
from django.utils import timezone

from matches.models import Match, MatchPlayer
from teams.models import Player, Team
from tournaments.lineup_lifecycle import save_match_lineup
from tournaments.models import Round, Tournament


@skipUnlessDBFeature("has_select_for_update")
class RoundMatchLockOrderPostgresTests(TransactionTestCase):
    def setUp(self):
        now = timezone.now()
        self.tournament = Tournament.objects.create(
            name="Round-first row-lock regression",
            format="swiss",
            play_format="doublets",
            allowed_match_types={"allowed_match_types": ["doublet"]},
            lineup_selection_seconds=30,
            start_date=now,
            end_date=now + timedelta(hours=3),
        )
        self.north = Team.objects.create(name="Lock North", pin="968001")
        self.south = Team.objects.create(name="Lock South", pin="968002")
        self.north_players = [
            Player.objects.create(name=f"Lock North {i}", team=self.north)
            for i in (1, 2)
        ]
        self.south_players = [
            Player.objects.create(name=f"Lock South {i}", team=self.south)
            for i in (1, 2)
        ]
        self.round = Round.objects.create(
            tournament=self.tournament,
            number=1,
            lineup_deadline_at=now + timedelta(minutes=5),
        )
        self.match = Match.objects.create(
            tournament=self.tournament,
            round=self.round,
            team1=self.north,
            team2=self.south,
            status="pending",
        )

    def _save_side(self, team, players):
        save_match_lineup(
            match_id=self.match.pk,
            acting_team_id=team.pk,
            player_ids=[player.pk for player in players],
            roles_by_player_id={},
        )

    def test_waiting_writer_does_not_lock_match_before_round(self):
        """A writer blocked by the Round must leave the Match row free.

        This test fails with the historical Match -> Round ordering: while
        another transaction owns Round, the lineup writer would grab Match,
        then block on Round, and the NOWAIT Match lock below would fail.
        """
        ready = threading.Event()
        errors = []
        backend_pid = []
        writer = None

        def worker():
            connections.close_all()
            try:
                with connections["default"].cursor() as cursor:
                    cursor.execute("SELECT pg_backend_pid()")
                    backend_pid.append(cursor.fetchone()[0])
                ready.set()
                self._save_side(self.north, self.north_players)
            except Exception as exc:
                errors.append(exc)
            finally:
                ready.set()
                connections.close_all()

        try:
            with transaction.atomic():
                Round.objects.select_for_update(of=("self",)).get(pk=self.round.pk)
                writer = threading.Thread(target=worker, name="lineup-lock-order-regression")
                writer.start()
                self.assertTrue(ready.wait(10), "Writer never established a connection")

                # Wait until the writer reaches the blocked row-lock request.
                # Do not infer safety merely from thread startup: the old code
                # could race this assertion before it acquires Match.
                blocked = False
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    with connection.cursor() as cursor:
                        cursor.execute(
                            "SELECT wait_event_type FROM pg_stat_activity WHERE pid = %s",
                            [backend_pid[0]],
                        )
                        row = cursor.fetchone()
                    if row and row[0] == "Lock":
                        blocked = True
                        break
                    time.sleep(0.05)
                self.assertTrue(blocked, "Lineup writer never blocked on Round")

                # If the writer locked Match before Round this NOWAIT query
                # raises on PostgreSQL. Correct Round-first order succeeds.
                Match.objects.select_for_update(of=("self",), nowait=True).get(
                    pk=self.match.pk
                )
        finally:
            if writer is not None:
                writer.join(timeout=15)

        self.assertFalse(writer.is_alive(), "Lineup writer remained blocked")
        self.assertEqual(errors, [])
        self.assertEqual(
            set(
                MatchPlayer.objects.filter(
                    match=self.match, team=self.north
                ).values_list("player_id", flat=True)
            ),
            {player.pk for player in self.north_players},
        )

    def test_two_concurrent_sides_save_without_deadlock(self):
        barrier = threading.Barrier(2)
        errors = []

        def worker(team, players):
            connections.close_all()
            try:
                barrier.wait(timeout=10)
                self._save_side(team, players)
            except Exception as exc:
                errors.append(exc)
            finally:
                connections.close_all()

        writers = [
            threading.Thread(target=worker, args=(self.north, self.north_players)),
            threading.Thread(target=worker, args=(self.south, self.south_players)),
        ]
        for writer in writers:
            writer.start()
        for writer in writers:
            writer.join(timeout=15)
            self.assertFalse(writer.is_alive(), "Concurrent lineup writer hung")

        self.assertEqual(errors, [])
        self.assertEqual(
            set(MatchPlayer.objects.filter(match=self.match).values_list("player_id", flat=True)),
            {player.pk for player in self.north_players + self.south_players},
        )
