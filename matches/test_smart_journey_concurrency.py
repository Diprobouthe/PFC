"""Current-head release gate for the 20-player Great Journey Super Mêlée.

Unlike the historical Smart A/B workflow, tests the code actually proposed in
the PR, real Mêlée side resolution and independent browser session cookies.
Requires PostgreSQL for the concurrent case (as in GitHub Actions).
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from statistics import median
from time import perf_counter

from django.db import close_old_connections, connection
from django.test import Client, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from friendly_games.models import PlayerCodename
from matches.models import Match, MatchPlayer
from practice.models import PracticeSession
from teams.models import Team, Player
from tournaments.models import (
    MeleePlayer, MeleeRoundAssignment, Round, Stage, Tournament,
)


class JourneySmartTwentyPlayerGate(TransactionTestCase):
    reset_sequences = False

    def setUp(self):
        now = timezone.now()
        t = Tournament.objects.create(
            name="CI synthetic Great Journey 20-player Smart gate",
            format="multi_stage", play_format="doublets", is_melee=True,
            melee_format="doublets", shuffle_players_after_round=True,
            start_date=now, end_date=now + timedelta(days=1),
        )
        stage = Stage.objects.create(
            tournament=t, stage_number=1, format="swiss",
            num_qualifiers=1, num_rounds_in_stage=5,
        )
        round_one = Round.objects.create(
            tournament=t, stage=stage, number=1, number_in_stage=1,
        )
        self.actors = []
        for court in range(5):
            sides = [
                Team.objects.create(
                    name=f"Journey test court {court + 1}, side {side + 1}",
                    is_tournament_temp=True,
                ) for side in range(2)
            ]
            match = Match.objects.create(
                tournament=t, stage=stage, round=round_one,
                team1=sides[0], team2=sides[1],
                status="active", start_time=None,
            )
            for position in range(4):
                idx = court * 4 + position
                side = sides[position // 2]
                # Deliberately unrelated legacy membership tests exact Mêlée roster.
                home = Team.objects.create(name=f"Journey home {idx}")
                player = Player.objects.create(name=f"Journey participant {idx}", team=home)
                codename = f"JRN{idx:04d}"
                PlayerCodename.objects.create(player=player, codename=codename)
                MeleePlayer.objects.create(tournament=t, player=player, original_team=home)
                MeleeRoundAssignment.objects.create(
                    tournament=t, round=round_one, player=player,
                    team=side, state=MeleeRoundAssignment.ASSIGNED,
                )
                MatchPlayer.objects.create(match=match, team=side, player=player)
                if idx % 2 == 0:
                    PracticeSession.objects.create(
                        player_codename=codename, practice_type="shooting",
                    )
                client = Client()
                session = client.session
                session["player_codename"] = codename
                session["session_active"] = True
                session.save()
                self.actors.append((client, reverse("match_detail", args=[match.pk])))

    @staticmethod
    def _click_repeatedly(actor):
        close_old_connections()
        client, expected = actor
        samples = []
        try:
            for _ in range(5):
                start = perf_counter()
                response = client.get(reverse("my_active_matches"))
                elapsed = (perf_counter() - start) * 1000
                samples.append(elapsed)
                if response.status_code != 302 or response.get("Location") != expected:
                    return (False, response.status_code, response.get("Location"),
                            expected, samples)
            return (True, 302, expected, expected, samples)
        finally:
            close_old_connections()

    def test_20_simultaneous_players_five_smart_requests_each(self):
        if connection.vendor != "postgresql":
            self.skipTest("Concurrent Smart release gate requires PostgreSQL")
        with ThreadPoolExecutor(max_workers=20) as pool:
            outputs = list(pool.map(self._click_repeatedly, self.actors))
        failures = [o[:4] for o in outputs if not o[0]]
        durations = sorted(v for result in outputs for v in result[4])
        p95 = durations[int((len(durations) - 1) * .95)]
        print(
            f"CURRENT_HEAD_JOURNEY_SMART players=20 requests={len(durations)} "
            f"p50_ms={median(durations):.1f} p95_ms={p95:.1f} "
            f"bad_destinations={len(failures)}",
            flush=True,
        )
        self.assertFalse(failures, failures)
        self.assertEqual(len(durations), 100)
