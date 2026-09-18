from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from matches.models import Match
from teams.models import Player, Team
from tournaments.melee_roster import MeleeRoundRosterService
from tournaments.models import (
    MeleePlayer,
    MeleeRoundAssignment,
    Round,
    Stage,
    Tournament,
    TournamentTeam,
)


class MeleeRoundAssignmentFoundationTests(TestCase):
    """P1: explicit, round-scoped Mêlée roster data with no Player.team writes."""

    def setUp(self):
        now = timezone.now()
        self.tournament = Tournament.objects.create(
            name='P1 Assignment Foundation Tournament',
            format='multi_stage',
            play_format='doublets',
            is_melee=True,
            melee_format='doublets',
            start_date=now,
            end_date=now + timedelta(days=1),
        )
        self.stage = Stage.objects.create(
            tournament=self.tournament,
            stage_number=1,
            format='swiss',
            num_qualifiers=1,
            num_rounds_in_stage=2,
        )
        self.round_one = Round.objects.create(
            tournament=self.tournament,
            stage=self.stage,
            number=1,
            number_in_stage=1,
        )
        self.round_two = Round.objects.create(
            tournament=self.tournament,
            stage=self.stage,
            number=2,
            number_in_stage=2,
        )

        self.home_team_a = Team.objects.create(name='P1 Original Team A')
        self.home_team_b = Team.objects.create(name='P1 Original Team B')
        self.other_real_team = Team.objects.create(name='P1 Other Real Team')
        self.temp_team_one = Team.objects.create(
            name='P1 Temporary Team One', is_tournament_temp=True
        )
        self.temp_team_two = Team.objects.create(
            name='P1 Temporary Team Two', is_tournament_temp=True
        )
        TournamentTeam.objects.create(
            tournament=self.tournament, team=self.temp_team_one
        )
        TournamentTeam.objects.create(
            tournament=self.tournament, team=self.temp_team_two
        )

        self.player_a = Player.objects.create(
            name='P1 Player A', team=self.home_team_a, is_captain=True
        )
        self.player_b = Player.objects.create(
            name='P1 Player B', team=self.home_team_b
        )
        self.player_c = Player.objects.create(
            name='P1 Player C', team=self.home_team_a
        )
        for player in (self.player_a, self.player_b, self.player_c):
            MeleePlayer.objects.create(
                tournament=self.tournament,
                player=player,
                original_team=player.team,
            )

    def _assign(self, *, round, player, team, state=MeleeRoundAssignment.ASSIGNED):
        return MeleeRoundAssignment.objects.create(
            tournament=self.tournament,
            round=round,
            player=player,
            team=team,
            state=state,
        )

    def test_assignment_preserves_original_player_team_and_match_ids(self):
        """P1 adds roster context without changing Player, Team, or Match identity."""
        match = Match.objects.create(
            tournament=self.tournament,
            stage=self.stage,
            round=self.round_one,
            team1=self.temp_team_one,
            team2=self.temp_team_two,
        )
        original_team_id = self.player_a.team_id
        original_match_side_ids = (match.team1_id, match.team2_id)
        original_temp_team_ids = (self.temp_team_one.id, self.temp_team_two.id)

        assignment = self._assign(
            round=self.round_one,
            player=self.player_a,
            team=self.temp_team_one,
        )

        self.player_a.refresh_from_db()
        match.refresh_from_db()
        self.assertEqual(self.player_a.team_id, original_team_id)
        self.assertTrue(self.player_a.is_captain)
        self.assertEqual((match.team1_id, match.team2_id), original_match_side_ids)
        self.assertEqual(
            (self.temp_team_one.id, self.temp_team_two.id), original_temp_team_ids
        )
        self.assertEqual(assignment.team_id, self.temp_team_one.id)

    def test_player_can_change_temporary_team_in_a_later_round(self):
        """A later round may have a different competition assignment safely."""
        first_assignment = self._assign(
            round=self.round_one,
            player=self.player_a,
            team=self.temp_team_one,
        )
        second_assignment = self._assign(
            round=self.round_two,
            player=self.player_a,
            team=self.temp_team_two,
        )

        self.player_a.refresh_from_db()
        self.assertEqual(self.player_a.team_id, self.home_team_a.id)
        self.assertEqual(first_assignment.team_id, self.temp_team_one.id)
        self.assertEqual(second_assignment.team_id, self.temp_team_two.id)
        self.assertEqual(
            MeleeRoundRosterService.assigned_team_for_player(
                tournament=self.tournament,
                round=self.round_one,
                player=self.player_a,
            ),
            self.temp_team_one,
        )
        self.assertEqual(
            MeleeRoundRosterService.assigned_team_for_player(
                tournament=self.tournament,
                round=self.round_two,
                player=self.player_a,
            ),
            self.temp_team_two,
        )

    def test_one_player_cannot_receive_conflicting_round_states(self):
        """The database constraint prevents conflicting Team/state assignments."""
        self._assign(
            round=self.round_one,
            player=self.player_a,
            team=self.temp_team_one,
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MeleeRoundAssignment.objects.bulk_create(
                    [
                        MeleeRoundAssignment(
                            tournament=self.tournament,
                            round=self.round_one,
                            player=self.player_a,
                            team=None,
                            state=MeleeRoundAssignment.BYE,
                        )
                    ]
                )

        self.assertEqual(
            MeleeRoundAssignment.objects.filter(
                tournament=self.tournament,
                round=self.round_one,
                player=self.player_a,
            ).count(),
            1,
        )

    def test_bye_state_is_unambiguous_without_a_temporary_team(self):
        """A non-complete Team state is represented without a fabricated roster."""
        assignment = self._assign(
            round=self.round_one,
            player=self.player_c,
            team=None,
            state=MeleeRoundAssignment.BYE,
        )

        self.assertEqual(assignment.state, MeleeRoundAssignment.BYE)
        self.assertIsNone(assignment.team)
        self.assertIsNone(
            MeleeRoundRosterService.assigned_team_for_player(
                tournament=self.tournament,
                round=self.round_one,
                player=self.player_c,
            )
        )

    def test_roster_resolution_ignores_current_player_team(self):
        """The resolver returns round assignments after affiliation changes."""
        self._assign(
            round=self.round_one,
            player=self.player_a,
            team=self.temp_team_one,
        )
        self._assign(
            round=self.round_one,
            player=self.player_b,
            team=self.temp_team_one,
        )
        self._assign(
            round=self.round_one,
            player=self.player_c,
            team=self.temp_team_two,
        )

        # This direct fixture change proves the service does not use Player.team
        # or the Team.players reverse relation as its roster source.
        self.player_a.team = self.other_real_team
        self.player_a.save(update_fields=['team'])
        self.player_b.team = self.other_real_team
        self.player_b.save(update_fields=['team'])

        assignments = list(
            MeleeRoundRosterService.assignments_for_team(
                tournament=self.tournament,
                round=self.round_one,
                team=self.temp_team_one,
            )
        )
        roster = list(
            MeleeRoundRosterService.players_for_team(
                tournament=self.tournament,
                round=self.round_one,
                team=self.temp_team_one,
            )
        )

        self.assertEqual(
            [assignment.player_id for assignment in assignments],
            [self.player_a.id, self.player_b.id],
        )
        self.assertEqual([player.id for player in roster], [self.player_a.id, self.player_b.id])
        self.assertEqual(self.temp_team_one.players.count(), 0)
        self.assertEqual(self.player_a.team_id, self.other_real_team.id)
        self.assertEqual(self.player_b.team_id, self.other_real_team.id)

    def test_validation_rejects_unregistered_players_and_invalid_context(self):
        """P1 cannot silently create a cross-tournament or non-enrolled roster row."""
        unregistered_player = Player.objects.create(
            name='P1 Unregistered Player', team=self.home_team_b
        )
        assignment = MeleeRoundAssignment(
            tournament=self.tournament,
            round=self.round_one,
            player=unregistered_player,
            team=self.temp_team_one,
            state=MeleeRoundAssignment.ASSIGNED,
        )

        with self.assertRaises(ValidationError):
            assignment.full_clean()

        unrelated_tournament = Tournament.objects.create(
            name='P1 Unrelated Tournament',
            format='multi_stage',
            play_format='doublets',
            is_melee=True,
            melee_format='doublets',
            start_date=timezone.now(),
            end_date=timezone.now() + timedelta(days=1),
        )
        with self.assertRaises(ValidationError):
            MeleeRoundRosterService.assignments_for_team(
                tournament=unrelated_tournament,
                round=self.round_one,
                team=self.temp_team_one,
            )
