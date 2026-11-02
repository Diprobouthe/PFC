"""PostgreSQL-specific regression tests for tournament Match lifecycle locks.

These tests intentionally open separate database connections. They are skipped
under SQLite because ``select_for_update`` and partial uniqueness semantics are
not representative there.
"""

from __future__ import annotations

import threading
from datetime import timedelta
from unittest.mock import patch

from django.db import IntegrityError, OperationalError, connection, connections, transaction
from django.test import SimpleTestCase, TransactionTestCase, skipUnlessDBFeature
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
from teams.models import Player, PlayerProfile, Team
from tournaments.models import Round, RoundLifecycleTransition, Tournament
from tournaments.partnership_models import MeleePlayerStats
from matches.models_participant import TeamMatchParticipant


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

    def test_concurrent_vs_game_completions_preserve_both_awards(self):
        from tournaments.models import VSEncounter, TournamentTeam
        from tournaments.vs_utils import update_vs_encounter_points

        self.tournament.format = "independent_games"
        self.tournament.allowed_match_types = {"vs_mode": True}
        self.tournament.save(update_fields=["format", "allowed_match_types"])
        TournamentTeam.objects.create(tournament=self.tournament, team=self.team1)
        TournamentTeam.objects.create(tournament=self.tournament, team=self.team2)
        encounter = VSEncounter.objects.create(
            tournament=self.tournament, team1=self.team1, team2=self.team2
        )
        first = self._match(self.team1, self.team2, status="pending")
        second = self._match(self.team1, self.team2, status="pending")
        Match.objects.filter(pk__in=(first.pk, second.pk)).update(vs_encounter=encounter)

        def finish_and_recalculate(match_id, winner_id, points):
            with transaction.atomic():
                Match.objects.filter(pk=match_id).update(
                    status="completed", winner_id=winner_id, vs_points_value=points
                )
                update_vs_encounter_points(encounter)

        _outcomes, errors = self._run_concurrently(
            lambda: finish_and_recalculate(first.pk, self.team1.pk, 2),
            lambda: finish_and_recalculate(second.pk, self.team2.pk, 3),
        )
        self.assertEqual(errors, [None, None])
        encounter.refresh_from_db()
        self.assertTrue(encounter.is_complete)
        self.assertEqual((encounter.team1_points, encounter.team2_points), (2, 3))
        self.assertEqual(
            dict(TournamentTeam.objects.filter(tournament=self.tournament)
                 .values_list("team_id", "vs_points")),
            {self.team1.pk: 2, self.team2.pk: 3},
        )

    def test_concurrent_vs_captains_activate_exactly_once(self):
        import json
        from django.test import Client
        from django.urls import reverse
        from tournaments.models import VSEncounter
        from tournaments.models import VSLineup

        self.tournament.format = "independent_games"
        self.tournament.allowed_match_types = {
            "vs_mode": True,
            "allowed_match_types": ["tete_a_tete", "doublet", "triplet"],
        }
        self.tournament.save(update_fields=["format", "allowed_match_types"])
        encounter = VSEncounter.objects.create(
            tournament=self.tournament, team1=self.team1, team2=self.team2
        )
        match = self._match(self.team1, self.team2, status="pending")
        match.vs_encounter = encounter
        match.save(update_fields=["vs_encounter"])
        players = {
            team_id: MatchPlayer.objects.get(match=match, team_id=team_id).player_id
            for team_id in (self.team1.pk, self.team2.pk)
        }
        clients = []
        for team in (self.team1, self.team2):
            client = Client()
            session = client.session
            session[f"team_pin_{self.tournament.pk}"] = team.pin
            session.save()
            clients.append(client)
        url = reverse("vs_lineup_submit", args=[match.pk])

        outcomes, errors = self._run_concurrently(
            lambda: clients[0].post(
                url, data=json.dumps({"player_ids": [players[self.team1.pk]]}),
                content_type="application/json",
            ),
            lambda: clients[1].post(
                url, data=json.dumps({"player_ids": [players[self.team2.pk]]}),
                content_type="application/json",
            ),
        )
        self.assertEqual(errors, [None, None])
        self.assertEqual([response.status_code for response in outcomes], [200, 200])
        match.refresh_from_db()
        self.assertEqual(match.status, "active")
        self.assertEqual(match.vs_points_value, 2)
        self.assertEqual(match.activations.count(), 2)
        self.assertEqual(VSLineup.objects.filter(match=match, is_locked=True).count(), 2)
        self.assertEqual(
            set(MatchPlayer.objects.filter(match=match).values_list("team_id", flat=True)),
            {self.team1.pk, self.team2.pk},
        )

    def test_concurrent_result_validations_finalize_once(self):
        match = self._match(self.team1, self.team2, status="active", court=self.court)
        submit_official_result(
            match.pk, submitted_by_id=self.team1.pk, team1_score=13, team2_score=8
        )
        with patch("matches.lifecycle.process_tournament_transition", return_value=True):
            outcomes, errors = self._run_concurrently(
                lambda: validate_official_result(
                    match.pk, validating_team_id=self.team2.pk, agree=True
                ),
                lambda: validate_official_result(
                    match.pk, validating_team_id=self.team2.pk, agree=True
                ),
            )
        self.assertEqual(errors, [None, None])
        self.assertEqual(
            sorted(outcome.state for outcome in outcomes),
            ["completed", "not_waiting_validation"],
        )
        match.refresh_from_db()
        self.assertEqual(match.status, "completed")
        self.assertEqual(MatchLifecycleTransition.objects.filter(match=match).count(), 1)

    def test_database_vendor_is_postgresql(self):
        self.assertEqual(connection.vendor, "postgresql")


class MatchDeadlockDetectionTests(SimpleTestCase):
    """Pure checks: only PostgreSQL deadlock code 40P01 is retryable."""

    def test_postgres_deadlock_is_detected_through_django_wrapper(self):
        from matches.lifecycle import _is_postgres_deadlock

        db_error = RuntimeError("deadlock detected")
        db_error.pgcode = "40P01"
        wrapper = RuntimeError("django database operation failed")
        wrapper.__cause__ = db_error

        self.assertTrue(_is_postgres_deadlock(wrapper))

    def test_other_operational_errors_are_not_retried(self):
        from matches.lifecycle import _is_postgres_deadlock

        db_error = RuntimeError("lock timeout")
        db_error.pgcode = "55P03"
        self.assertFalse(_is_postgres_deadlock(db_error))


class MatchDeadlockRecoveryTests(TransactionTestCase):
    """Exercise actual DB rollback before a bounded deadlock retry.

    A synthetic PostgreSQL SQLSTATE is injected *after* the ordinary rating
    update, so a failure would expose duplicate ratings or match participants.
    These tests must run against the PostgreSQL CI service.
    """

    def setUp(self):
        now = timezone.now()
        self.tournament = Tournament.objects.create(
            name="Deadlock Recovery Mêlée",
            format="swiss",
            play_format="doublets",
            is_melee=True,
            melee_format="doublets",
            start_date=now,
            end_date=now + timedelta(hours=2),
        )
        one = Team.objects.create(name="Deadlock Team One", is_tournament_temp=True)
        two = Team.objects.create(name="Deadlock Team Two", is_tournament_temp=True)
        self.players = []
        self.match = Match.objects.create(
            tournament=self.tournament,
            team1=one,
            team2=two,
            status="pending",
        )
        for team in (one, two):
            for number in range(2):
                player = Player.objects.create(
                    name=f"{team.name} Player {number}", team=team,
                )
                PlayerProfile.objects.create(
                    player=player, value=100.0, is_active=True, rating_history=[],
                )
                MeleePlayerStats.objects.create(
                    tournament=self.tournament, player=player, starting_rating=100.0,
                )
                MatchPlayer.objects.create(match=self.match, team=team, player=player)
                self.players.append(player)
        Match.objects.filter(pk=self.match.pk).update(
            status="completed",
            team1_score=13,
            team2_score=4,
            winner=one,
            loser=two,
        )
        self.match.refresh_from_db()
        MatchLifecycleTransition.objects.create(
            match=self.match, tournament=self.tournament,
        )

    @staticmethod
    def _database_error(code="40P01"):
        original = RuntimeError("PostgreSQL transaction failed")
        original.pgcode = code
        wrapped = OperationalError("deadlock detected" if code == "40P01" else "lock error")
        wrapped.__cause__ = original
        return wrapped

    def test_one_deadlock_rolls_back_ratings_then_retries_exactly_once(self):
        from tournaments.melee_stats_updater import (
            update_melee_player_stats_from_match as actual_update,
        )

        calls = []

        def fail_once_then_update(match):
            calls.append(match.id)
            if len(calls) == 1:
                raise self._database_error()
            return actual_update(match)

        with patch(
            "tournaments.melee_stats_updater.update_melee_player_stats_from_match",
            side_effect=fail_once_then_update,
        ):
            self.assertTrue(process_tournament_transition(self.match.id))

        self.assertEqual(calls, [self.match.id, self.match.id])
        transition = MatchLifecycleTransition.objects.get(match=self.match)
        self.assertEqual(transition.status, MatchLifecycleTransition.COMPLETED)
        self.assertEqual(TeamMatchParticipant.objects.filter(match=self.match).count(), 4)
        stats = MeleePlayerStats.objects.filter(tournament=self.tournament)
        self.assertEqual(stats.count(), 4)
        self.assertTrue(all(value == 1 for value in stats.values_list("matches_played", flat=True)))
        for player in self.players:
            profile = PlayerProfile.objects.get(player=player)
            match_history = [
                item for item in profile.rating_history or []
                if item.get("match_id") == self.match.id
            ]
            self.assertEqual(len(match_history), 1, player.name)

        # A repeated request after success remains idempotent.
        self.assertTrue(process_tournament_transition(self.match.id))
        self.assertEqual(TeamMatchParticipant.objects.filter(match=self.match).count(), 4)
        self.assertEqual(
            sum(MeleePlayerStats.objects.filter(
                tournament=self.tournament
            ).values_list("matches_played", flat=True)), 4,
        )
        for player in self.players:
            profile = PlayerProfile.objects.get(player=player)
            self.assertEqual(
                sum(item.get("match_id") == self.match.id for item in profile.rating_history or []),
                1,
            )

    def test_three_deadlocks_leave_failed_state_and_no_partial_writes(self):
        with patch(
            "tournaments.melee_stats_updater.update_melee_player_stats_from_match",
            side_effect=self._database_error(),
        ) as update:
            self.assertFalse(process_tournament_transition(self.match.id))
        self.assertEqual(update.call_count, 3)  # initial + two retries
        transition = MatchLifecycleTransition.objects.get(match=self.match)
        self.assertEqual(transition.status, MatchLifecycleTransition.FAILED)
        self.assertIn("deadlock", transition.last_error.lower())
        self.assertEqual(TeamMatchParticipant.objects.filter(match=self.match).count(), 0)
        self.assertEqual(
            sum(MeleePlayerStats.objects.filter(
                tournament=self.tournament
            ).values_list("matches_played", flat=True)), 0,
        )
        for player in self.players:
            self.assertEqual(PlayerProfile.objects.get(player=player).rating_history, [])

    def test_non_deadlock_does_not_retry(self):
        with patch(
            "tournaments.melee_stats_updater.update_melee_player_stats_from_match",
            side_effect=self._database_error("55P03"),
        ) as update:
            self.assertFalse(process_tournament_transition(self.match.id))
        self.assertEqual(update.call_count, 1)
        self.assertEqual(
            MatchLifecycleTransition.objects.get(match=self.match).status,
            MatchLifecycleTransition.FAILED,
        )

    @skipUnlessDBFeature("has_select_for_update")
    def test_real_postgresql_deadlock_between_two_match_projections_recovers(self):
        """Two real connections deadlock on Player rows, not mocked SQLSTATEs.

        Both Match transitions must finish; one is selected as PostgreSQL's
        deadlock victim and transparently retries after its rollback.
        """
        from matches.lifecycle import _is_postgres_deadlock as real_is_deadlock

        first = self.match
        second = Match.objects.create(
            tournament=self.tournament,
            team1=first.team1,
            team2=first.team2,
            status="pending",
        )
        for participant in MatchPlayer.objects.filter(match=first):
            MatchPlayer.objects.create(
                match=second, player=participant.player, team=participant.team,
            )
        Match.objects.filter(pk=second.pk).update(
            status="completed",
            team1_score=13,
            team2_score=4,
            winner=first.team1,
            loser=first.team2,
        )
        MatchLifecycleTransition.objects.create(
            match=second, tournament=self.tournament,
        )

        # The two first attempts deliberately take these real PostgreSQL
        # row locks in opposite order, forming a wait-for cycle.
        player_ids = [self.players[0].pk, self.players[1].pk]
        opposing_orders = {
            first.pk: (player_ids[0], player_ids[1]),
            second.pk: (player_ids[1], player_ids[0]),
        }
        each_holds_first_lock = threading.Barrier(2)
        call_guard = threading.Lock()
        attempts = {first.pk: 0, second.pk: 0}
        seen_deadlock_codes = []
        create_participants = TeamMatchParticipant.create_from_match_players

        def force_real_deadlock(match):
            with call_guard:
                attempts[match.pk] += 1
                number = attempts[match.pk]
            if number == 1:
                with connection.cursor() as cursor:
                    # Lower detection latency on these test connections only.
                    cursor.execute("SET LOCAL deadlock_timeout = '200ms'")
                    cursor.execute(
                        "SELECT id FROM teams_player WHERE id = %s FOR UPDATE",
                        [opposing_orders[match.pk][0]],
                    )
                each_holds_first_lock.wait(timeout=12)
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT id FROM teams_player WHERE id = %s FOR UPDATE",
                        [opposing_orders[match.pk][1]],
                    )
            return create_participants(match)

        def track_deadlock(exc):
            result = real_is_deadlock(exc)
            if result:
                with call_guard:
                    seen_deadlock_codes.append("40P01")
            return result

        outcomes = {}
        errors = {}
        def worker(match_id):
            connections.close_all()
            try:
                outcomes[match_id] = process_tournament_transition(match_id)
            except Exception as exc:
                errors[match_id] = exc
            finally:
                connections.close_all()

        with patch(
            "matches.models_participant.TeamMatchParticipant.create_from_match_players",
            side_effect=force_real_deadlock,
        ), patch("matches.lifecycle._is_postgres_deadlock", side_effect=track_deadlock):
            workers = [
                threading.Thread(target=worker, args=(match_id,))
                for match_id in (first.pk, second.pk)
            ]
            for thread in workers:
                thread.start()
            for thread in workers:
                thread.join(timeout=25)
                self.assertFalse(thread.is_alive(), "Real PostgreSQL deadlock test hung")

        self.assertEqual(errors, {})
        self.assertEqual(outcomes, {first.pk: True, second.pk: True})
        self.assertTrue(seen_deadlock_codes, "No real 40P01 deadlock was observed")
        self.assertEqual(sorted(attempts.values()), [1, 2])
        self.assertEqual(
            set(MatchLifecycleTransition.objects.filter(
                match_id__in=[first.pk, second.pk],
            ).values_list("status", flat=True)),
            {MatchLifecycleTransition.COMPLETED},
        )
        self.assertEqual(TeamMatchParticipant.objects.filter(match=first).count(), 4)
        self.assertEqual(TeamMatchParticipant.objects.filter(match=second).count(), 4)
        stats = MeleePlayerStats.objects.filter(tournament=self.tournament)
        self.assertEqual(stats.count(), 4)
        self.assertEqual(
            list(stats.values_list("matches_played", flat=True)), [2] * 4,
        )
        for player in self.players:
            history = PlayerProfile.objects.get(player=player).rating_history or []
            for match_id in (first.pk, second.pk):
                self.assertEqual(
                    sum(item.get("match_id") == match_id for item in history),
                    1,
                    (player.name, match_id),
                )
