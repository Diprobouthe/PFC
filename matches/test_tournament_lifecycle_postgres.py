"""PostgreSQL-specific regression tests for tournament Match lifecycle locks.

These tests intentionally open separate database connections. They are skipped
under SQLite because ``select_for_update`` and partial uniqueness semantics are
not representative there.
"""

from __future__ import annotations

import threading
from datetime import timedelta
from unittest.mock import patch

from django.db import IntegrityError, connection, connections, transaction
from django.test import TransactionTestCase, skipUnlessDBFeature
from django.utils import timezone

from courts.models import Court
from matches.lifecycle import (
    activate_verified_match,
    process_round_transition,
    process_tournament_transition,
    submit_official_result,
    validate_official_result,
)
from matches.models import Match, MatchLifecycleTransition, MatchPlayer
from teams.models import Player, Team
from tournaments.models import Round, RoundLifecycleTransition, Tournament


@skipUnlessDBFeature("has_select_for_update")
class TournamentLifecyclePostgreSQLTests(TransactionTestCase):
    """Separate-connection tests that require actual PostgreSQL row locking."""

    reset_sequences = True

    def setUp(self):
        now = timezone.now()
        self.tournament = Tournament.objects.create(
            name="Lifecycle PostgreSQL",
            format="swiss",
            play_format="doublets",
            start_date=now,
            end_date=now + timedelta(hours=4),
        )
        self.team1 = Team.objects.create(name="Lifecycle North", pin="861001")
        self.team2 = Team.objects.create(name="Lifecycle South", pin="861002")
        self.team3 = Team.objects.create(name="Lifecycle East", pin="861003")
        self.team4 = Team.objects.create(name="Lifecycle West", pin="861004")
        self.court = Court.objects.create(number=86101, is_available=True)
        self.tournament.courts.add(self.court)

    def _match(self, team1, team2, *, status="pending_verification", court=None):
        match = Match.objects.create(
            tournament=self.tournament,
            team1=team1,
            team2=team2,
            status=status,
            court=court,
        )
        for team, suffix in ((team1, "a"), (team2, "b")):
            player = Player.objects.create(name=f"{team.name}-{suffix}", team=team)
            MatchPlayer.objects.create(match=match, player=player, team=team)
        return match

    def _run_concurrently(self, *calls):
        barrier = threading.Barrier(len(calls))
        results = [None] * len(calls)
        errors = [None] * len(calls)

        def worker(index, call):
            connections.close_all()
            try:
                barrier.wait(timeout=10)
                results[index] = call()
            except Exception as exc:  # asserted by callers
                errors[index] = exc
            finally:
                connections.close_all()

        threads = [threading.Thread(target=worker, args=(i, call)) for i, call in enumerate(calls)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)
            self.assertFalse(thread.is_alive(), "PostgreSQL lifecycle thread did not finish")
        return results, errors

    def test_only_one_concurrent_match_claims_one_court(self):
        first = self._match(self.team1, self.team2)
        second = self._match(self.team3, self.team4)

        outcomes, errors = self._run_concurrently(
            lambda: activate_verified_match(first.id),
            lambda: activate_verified_match(second.id),
        )
        self.assertEqual(errors, [None, None])
        self.assertEqual(sum(outcome.activated for outcome in outcomes), 1)

        live = Match.objects.filter(status__in=("active", "waiting_validation"), court=self.court)
        self.assertEqual(live.count(), 1)
        self.court.refresh_from_db()
        self.assertFalse(self.court.is_available)

    def test_partial_unique_constraint_rejects_bypassed_live_court_write(self):
        first = self._match(self.team1, self.team2, status="active", court=self.court)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self._match(self.team3, self.team4, status="waiting_validation", court=self.court)
        self.assertTrue(Match.objects.filter(pk=first.pk).exists())

    def test_result_submission_is_idempotent_under_concurrency(self):
        match = self._match(self.team1, self.team2, status="active", court=self.court)

        outcomes, errors = self._run_concurrently(
            lambda: submit_official_result(
                match.id,
                submitted_by_id=self.team1.id,
                team1_score=13,
                team2_score=7,
            ),
            lambda: submit_official_result(
                match.id,
                submitted_by_id=self.team1.id,
                team1_score=13,
                team2_score=7,
            ),
        )
        self.assertEqual(errors, [None, None])
        self.assertEqual(sorted(outcome.state for outcome in outcomes), ["already_submitted", "submitted"])
        match.refresh_from_db()
        self.assertEqual(match.status, "waiting_validation")
        self.assertEqual(match.result.submitted_by_id, self.team1.id)

    @patch("matches.rating_integration.update_tournament_match_ratings")
    def test_only_one_match_transition_claims_match_projection(
        self,
        update_ratings,
    ):
        match = self._match(self.team1, self.team2, status="active", court=self.court)
        submit_official_result(
            match.id,
            submitted_by_id=self.team1.id,
            team1_score=13,
            team2_score=7,
        )
        with patch("matches.lifecycle.process_tournament_transition", return_value=True):
            validation = validate_official_result(
                match.id,
                validating_team_id=self.team2.id,
                agree=True,
            )
        self.assertEqual(validation.state, "completed")

        outcomes, errors = self._run_concurrently(
            lambda: process_tournament_transition(match.id),
            lambda: process_tournament_transition(match.id),
        )
        self.assertEqual(errors, [None, None])
        self.assertEqual(outcomes, [True, True])
        transition = MatchLifecycleTransition.objects.get(match=match)
        self.assertEqual(transition.status, MatchLifecycleTransition.COMPLETED)
        self.assertEqual(transition.attempts, 1)
        self.assertEqual(update_ratings.call_count, 1)

    @patch("leaderboards.views.publish_tournament_leaderboard")
    @patch("tournaments.automation_engine.TournamentEngine.process_automation", return_value=True)
    def test_only_one_final_match_claims_round_transition(self, process_automation, publish):
        round_obj = Round.objects.create(tournament=self.tournament, number=1)
        match = self._match(self.team1, self.team2, status="completed")
        match.round = round_obj
        match.save(update_fields=["round", "status", "updated_at"])

        outcomes, errors = self._run_concurrently(
            lambda: process_round_transition(round_obj.id),
            lambda: process_round_transition(round_obj.id),
        )
        self.assertEqual(errors, [None, None])
        self.assertEqual(outcomes, [True, True])
        transition = RoundLifecycleTransition.objects.get(round=round_obj)
        self.assertEqual(transition.status, RoundLifecycleTransition.COMPLETED)
        self.assertEqual(transition.attempts, 1)
        self.assertEqual(process_automation.call_count, 1)
        self.assertEqual(publish.call_count, 1)

    def test_round_identity_constraints_apply_on_postgresql(self):
        from tournaments.models import Round

        Round.objects.create(tournament=self.tournament, number=1, number_in_stage=1)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Round.objects.create(tournament=self.tournament, number=1, number_in_stage=2)
        Round.objects.create(tournament=self.tournament, number=2, number_in_stage=1)

    def test_concurrent_leaderboard_rebuilds_leave_one_consistent_ranking(self):
        from leaderboards.models import Leaderboard, LeaderboardEntry
        from leaderboards.views import update_tournament_leaderboard
        from tournaments.models import TournamentTeam

        TournamentTeam.objects.create(tournament=self.tournament, team=self.team1)
        TournamentTeam.objects.create(tournament=self.tournament, team=self.team2)
        TournamentTeam.objects.create(tournament=self.tournament, team=self.team3)

        _outcomes, errors = self._run_concurrently(
            lambda: update_tournament_leaderboard(self.tournament),
            lambda: update_tournament_leaderboard(self.tournament),
        )
        self.assertEqual(errors, [None, None])
        leaderboard = Leaderboard.objects.get(tournament=self.tournament)
        entries = list(LeaderboardEntry.objects.filter(leaderboard=leaderboard))
        self.assertEqual(len(entries), 3)
        self.assertEqual(len({entry.position for entry in entries}), 3)
        self.assertEqual(len({entry.team_id for entry in entries}), 3)

    def test_database_vendor_is_postgresql(self):
        self.assertEqual(connection.vendor, "postgresql")
