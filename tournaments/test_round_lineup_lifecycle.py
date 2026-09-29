from datetime import timedelta

from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from courts.models import Court
from matches.models import Match, MatchPlayer
from teams.models import Player, Team
from tournaments.lineup_lifecycle import (
    finalize_round_lineups,
    open_round_lineup_window,
    save_match_lineup,
)
from tournaments.models import Round, Stage, Tournament


class RoundLineupLifecycleTests(TestCase):
    def setUp(self):
        now = timezone.now()
        self.tournament = Tournament.objects.create(
            name="Round lineup lifecycle",
            format="swiss",
            play_format="doublets",
            allowed_match_types={"allowed_match_types": ["doublet"]},
            lineup_selection_seconds=30,
            start_date=now,
            end_date=now + timedelta(hours=3),
        )
        self.team1 = Team.objects.create(name="Lineup North", pin="930001")
        self.team2 = Team.objects.create(name="Lineup South", pin="930002")
        self.players1 = [
            Player.objects.create(name=f"North {index}", team=self.team1)
            for index in range(1, 3)
        ]
        self.players2 = [
            Player.objects.create(name=f"South {index}", team=self.team2)
            for index in range(1, 3)
        ]
        self.court = Court.objects.create(number=93001, is_available=True)
        self.tournament.courts.add(self.court)
        self.round = Round.objects.create(tournament=self.tournament, number=1)
        self.match = Match.objects.create(
            tournament=self.tournament,
            round=self.round,
            team1=self.team1,
            team2=self.team2,
            status="pending",
        )

    def _expire_window(self):
        open_round_lineup_window(self.round.id)
        self.round.refresh_from_db()
        self.round.lineup_deadline_at = timezone.now() - timedelta(seconds=1)
        self.round.save(update_fields=["lineup_deadline_at"])

    def test_deadline_materializes_only_safe_defaults_and_allocates_ready_match(self):
        self._expire_window()

        outcome = finalize_round_lineups(self.round.id)

        self.assertTrue(outcome.frozen)
        self.assertEqual(outcome.ready_match_ids, (self.match.id,))
        self.assertEqual(outcome.blocked_match_ids, ())
        self.match.refresh_from_db()
        self.round.refresh_from_db()
        self.assertEqual(self.match.status, "active")
        self.assertEqual(self.match.court_id, self.court.id)
        self.assertIsNotNone(self.round.lineups_frozen_at)
        self.assertEqual(
            set(MatchPlayer.objects.filter(match=self.match, team=self.team1).values_list("player_id", flat=True)),
            {player.id for player in self.players1},
        )
        self.assertEqual(
            set(MatchPlayer.objects.filter(match=self.match, team=self.team2).values_list("player_id", flat=True)),
            {player.id for player in self.players2},
        )

    def test_unsafe_default_leaves_round_open_without_activation(self):
        self.players2[-1].delete()
        self._expire_window()

        outcome = finalize_round_lineups(self.round.id)

        self.assertFalse(outcome.frozen)
        self.assertEqual(outcome.ready_match_ids, ())
        self.assertEqual(outcome.blocked_match_ids, (self.match.id,))
        self.match.refresh_from_db()
        self.round.refresh_from_db()
        self.assertEqual(self.match.status, "pending")
        self.assertIsNone(self.round.lineups_frozen_at)
        self.assertFalse(MatchPlayer.objects.filter(match=self.match).exists())

    def test_repeated_finalization_is_idempotent(self):
        self._expire_window()
        first = finalize_round_lineups(self.round.id)
        second = finalize_round_lineups(self.round.id)

        self.assertTrue(first.frozen)
        self.assertTrue(second.frozen)
        self.assertEqual(second.ready_match_ids, ())
        self.assertEqual(MatchPlayer.objects.filter(match=self.match).count(), 4)

    def test_side_can_replace_its_saved_selection_before_deadline(self):
        replacement = Player.objects.create(name="North 3", team=self.team1)
        open_round_lineup_window(self.round.id)

        save_match_lineup(
            match_id=self.match.id,
            acting_team_id=self.team1.id,
            player_ids=[self.players1[0].id, self.players1[1].id],
            roles_by_player_id={},
        )
        save_match_lineup(
            match_id=self.match.id,
            acting_team_id=self.team1.id,
            player_ids=[self.players1[0].id, replacement.id],
            roles_by_player_id={},
        )

        self.assertEqual(
            set(MatchPlayer.objects.filter(match=self.match, team=self.team1).values_list("player_id", flat=True)),
            {self.players1[0].id, replacement.id},
        )

    def test_legacy_unstaged_round_number_in_stage_is_not_a_false_conflict(self):
        Round.objects.create(tournament=self.tournament, number=2, number_in_stage=1)
        Round.objects.create(tournament=self.tournament, number=3, number_in_stage=1)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Round.objects.create(tournament=self.tournament, number=2, number_in_stage=2)

        stage = Stage.objects.create(
            tournament=self.tournament,
            stage_number=1,
            format="swiss",
            num_qualifiers=0,
        )
        Round.objects.create(
            tournament=self.tournament,
            stage=stage,
            number=4,
            number_in_stage=1,
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Round.objects.create(
                    tournament=self.tournament,
                    stage=stage,
                    number=5,
                    number_in_stage=1,
                )
