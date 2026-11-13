"""PETA PostgreSQL integration regression: only TWO miniature events.

Uses actual Django models, the MatchLifecycleTransition processor, frozen
certified ratings and end-of-event settlement. No production PFC data.
"""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from teams.models import Player, PlayerProfile, Team
from tournaments.models import Tournament, MeleePlayer
from matches.models import Match, MatchPlayer, MatchLifecycleTransition, LiveScoreboard, ScoreUpdate
from matches.lifecycle import process_tournament_transition
from friendly_games.models import PlayerCodename
from match_tracking.models import MatchTrackingSession, TrackingPracticeSession
from practice.models import PracticeSession, Shot

from cert_ratings.models import CertifyingEntity, CertRatingHistory, PlayerCertRating
from cert_ratings.peta_models import PetaSeries, PetaEvent, PetaEventEntry, PetaCompetitor
from cert_ratings.peta_service import _contributing_player_ids, freeze_peta_entries, settle_peta_tournament


class PetaTwoEventDatabaseTests(TestCase):
    def setUp(self):
        self.club = Team.objects.create(name="PETA test club")
        self.players = [
            Player.objects.create(name=f"Player {i}", team=self.club)
            for i in range(1, 5)
        ]
        for player, initial in zip(self.players, [155.0, 140.0, 116.0, 100.0]):
            PlayerProfile.objects.update_or_create(
                player=player, defaults={"value": initial})
        self.entity = CertifyingEntity.objects.create(
            name="PETA CI", rating_system="peta_algorithm")
        self.series = PetaSeries.objects.create(entity=self.entity, name="Two-event CI")

    def _event(self, number):
        now = timezone.now()
        tournament = Tournament.objects.create(
            name=f"PETA event {number}",
            play_format="doublets",
            start_date=now,
            end_date=now + timedelta(hours=3),
            is_melee=True,
            melee_format="doublets",
            certifying_entity=self.entity,
        )
        event = PetaEvent.objects.create(
            series=self.series, tournament=tournament,
            ordinal=number, include_podium=True)
        registrations = [
            MeleePlayer.objects.create(tournament=tournament, player=p)
            for p in self.players
        ]
        frozen = freeze_peta_entries(tournament, registrations)
        self.assertEqual(len(frozen), 4)
        # Re-freeze never mutates the already captured snapshot.
        self.assertEqual(freeze_peta_entries(tournament, registrations), frozen)
        return tournament, event, frozen

    def _completed_match(self, tournament, first_score=13, second_score=8):
        first_team = Team.objects.create(name="Synthetic first side", is_tournament_temp=True)
        second_team = Team.objects.create(name="Synthetic second side", is_tournament_temp=True)
        match = Match.objects.create(
            tournament=tournament, team1=first_team, team2=second_team,
            team1_score=first_score, team2_score=second_score,
            status="completed", winner=first_team if first_score > second_score else second_team,
            loser=second_team if first_score > second_score else first_team,
        )
        for player, side in zip(self.players, [first_team, first_team, second_team, second_team]):
            MatchPlayer.objects.create(match=match, player=player, team=side)
        MatchLifecycleTransition.objects.create(match=match, tournament=tournament)
        return match

    def _settle(self, tournament, event):
        tournament.automation_status = "completed"
        tournament.save(update_fields=["automation_status"])
        first = settle_peta_tournament(tournament)
        self.assertTrue(first["settled"])
        balances_before = dict(PetaCompetitor.objects.filter(
            series=self.series).values_list("player_id", "travel_points"))
        again = settle_peta_tournament(tournament)
        self.assertEqual(again["reason"], "Already settled")
        self.assertEqual(balances_before, dict(PetaCompetitor.objects.filter(
            series=self.series).values_list("player_id", "travel_points")))
        event.refresh_from_db()
        self.assertIsNotNone(event.settled_at)
        return first

    def test_be_helpful_requires_each_match_and_accepts_delegated_tracking(self):
        tournament, event, _ = self._event(1)
        first = self._completed_match(tournament)
        second = self._completed_match(tournament)
        player = self.players[0]
        code, _ = PlayerCodename.objects.get_or_create(player=player)
        scoreboard, _ = LiveScoreboard.objects.get_or_create(tournament_match=first)
        ScoreUpdate.objects.create(
            scoreboard=scoreboard, team1_score=1, team2_score=0,
            scorekeeper_codename=code.codename, update_type="increment")
        # One scored match cannot qualify a player who played twice.
        self.assertNotIn(
            player.pk, _contributing_player_ids(tournament, [player.pk]))
        tracking = MatchTrackingSession.objects.create(
            match_type="match", match_pk=second.pk)
        practice = PracticeSession.objects.create(
            player_codename=code.codename, practice_type="shooting", distance="ing")
        TrackingPracticeSession.objects.create(
            tracking_session=tracking, player=player,
            practice_session=practice, practice_type="shooting")
        # Authorization or an empty tracking session does not qualify.
        self.assertNotIn(
            player.pk, _contributing_player_ids(tournament, [player.pk]))
        Shot.objects.create(session=practice, outcome="miss")
        practice.update_statistics()
        # The credited player is the tracked target, regardless of operator.
        self.assertIn(
            player.pk, _contributing_player_ids(tournament, [player.pk]))

    def test_two_events_global_pfc_and_peta_ratings_are_independent(self):
        t1, event1, frozen1 = self._event(1)
        match1 = self._completed_match(t1)
        before = {
            p.pk: PlayerProfile.objects.get(player=p).value for p in self.players
        }
        self.assertTrue(process_tournament_transition(match1.pk))
        self.assertEqual(CertRatingHistory.objects.filter(
            entity=self.entity, match=match1).count(), 4)
        pfc_after = {
            p.pk: PlayerProfile.objects.get(player=p).value for p in self.players
        }
        self.assertTrue(any(pfc_after[pid] != before[pid] for pid in before))
        cert_after = dict(PlayerCertRating.objects.filter(
            entity=self.entity).values_list("player_id", "current_rating"))
        self.assertNotEqual(cert_after, before)
        self.assertTrue(process_tournament_transition(match1.pk))
        self.assertEqual(
            pfc_after, {p.pk: PlayerProfile.objects.get(player=p).value for p in self.players})
        self.assertEqual(
            cert_after, dict(PlayerCertRating.objects.filter(
                entity=self.entity).values_list("player_id", "current_rating")))

        # A genuine Live Score update credits the authenticated player.
        code3, _ = PlayerCodename.objects.get_or_create(player=self.players[2])
        scoreboard, _ = LiveScoreboard.objects.get_or_create(tournament_match=match1)
        ScoreUpdate.objects.create(
            scoreboard=scoreboard, team1_score=1, team2_score=0,
            scorekeeper_codename=code3.codename, update_type="increment")
        # Tracking credits the TARGET player even if another player operated the phone.
        code4, _ = PlayerCodename.objects.get_or_create(player=self.players[3])
        tracking = MatchTrackingSession.objects.create(match_type="match", match_pk=match1.pk)
        practice = PracticeSession.objects.create(
            player_codename=code4.codename, practice_type="shooting", distance="ing")
        TrackingPracticeSession.objects.create(
            tracking_session=tracking, player=self.players[3],
            practice_session=practice, practice_type="shooting")
        Shot.objects.create(session=practice, outcome="miss")
        practice.update_statistics()

        settled1 = self._settle(t1, event1)
        self.assertGreater(Decimal(settled1["pool"]), 0)
        credits1 = {
            row.player_id: row for row in PetaEventEntry.objects.filter(event=event1)}
        self.assertFalse(credits1[self.players[0].pk].eligible_for_dividend)
        self.assertTrue(credits1[self.players[2].pk].eligible_for_dividend)
        self.assertTrue(credits1[self.players[3].pk].eligible_for_dividend)

        # Deliberately lower one global PFC Rating, raise another.
        falling = self.players[2]
        rising = self.players[0]
        prior_falling = PetaCompetitor.objects.get(
            series=self.series, player=falling).last_end_rating
        prior_rising = PetaCompetitor.objects.get(
            series=self.series, player=rising).last_end_rating
        PlayerProfile.objects.filter(player=falling).update(value=prior_falling - 35)
        PlayerProfile.objects.filter(player=rising).update(value=prior_rising + 12)
        t2, event2, frozen2 = self._event(2)
        self.assertAlmostEqual(frozen2[falling.pk], prior_falling)
        self.assertAlmostEqual(frozen2[rising.pk], prior_rising)

        match2 = self._completed_match(t2, first_score=9, second_score=13)
        self.assertTrue(process_tournament_transition(match2.pk))
        self.assertEqual(CertRatingHistory.objects.filter(
            entity=self.entity, match=match2).count(), 4)
        self._settle(t2, event2)
        self.assertEqual(PetaEvent.objects.filter(
            series=self.series, settled_at__isnull=False).count(), 2)
        self.assertEqual(
            PetaEventEntry.objects.filter(event__series=self.series).count(), 8)
        self.assertEqual(
            CertRatingHistory.objects.filter(entity=self.entity).count(), 8)
        self.assertEqual(
            PetaCompetitor.objects.filter(series=self.series).count(), 4)


class PetaConcurrentProjectionTests(__import__("django.test", fromlist=["TransactionTestCase"]).TransactionTestCase):
    """Two real PostgreSQL connections racing to project the same completed match."""

    def test_concurrent_projection_writes_each_player_once(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from django.db import close_old_connections
        from cert_ratings.peta_service import process_peta_match

        # Reuse the established four-player fixture, but TransactionTestCase
        # commits setup rows so independent connections can actually see them.
        PetaTwoEventDatabaseTests.setUp(self)
        tournament, _, _ = PetaTwoEventDatabaseTests._event(self, 1)
        match = PetaTwoEventDatabaseTests._completed_match(self, tournament)
        barrier = Barrier(2)

        def project(_):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return process_peta_match(
                    Match.objects.get(pk=match.pk),
                    CertifyingEntity.objects.get(pk=self.entity.pk),
                )
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(project, range(2)))
        self.assertTrue(all(result["success"] for result in results), results)
        self.assertEqual(
            sorted(len(result["updates"]) for result in results), [0, 4]
        )
        self.assertEqual(
            CertRatingHistory.objects.filter(
                entity=self.entity, match=match
            ).count(), 4
        )
        self.assertEqual(
            list(PlayerCertRating.objects.filter(
                entity=self.entity, player__in=self.players
            ).values_list("matches_played", flat=True)),
            [1] * 4,
        )
