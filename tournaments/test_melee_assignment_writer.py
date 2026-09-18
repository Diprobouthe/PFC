from datetime import timedelta
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from courts.models import Court
from matches.models import Match
from teams.models import Player, PlayerProfile, Team
from tournaments.melee_assignments import (
    MeleeRoundAssignmentInput,
    MeleeRoundAssignmentWriteConflict,
    MeleeRoundAssignmentWriter,
)
from tournaments.melee_roster import MeleeRoundRosterService
from tournaments.models import (
    MeleePlayer,
    MeleeRoundAssignment,
    Round,
    Stage,
    Tournament,
    TournamentTeam,
)
from tournaments.shuffle_utils import shuffle_melee_players


class MeleeRoundAssignmentWriterTests(TestCase):
    """P2: assignment writes are validated and dual-written from legacy flows."""

    def setUp(self):
        now = timezone.now()
        self.tournament = Tournament.objects.create(
            name='P2 Assignment Writer Tournament',
            format='multi_stage',
            play_format='doublets',
            is_melee=True,
            melee_format='doublets',
            shuffle_players_after_round=True,
            start_date=now,
            end_date=now + timedelta(days=1),
        )
        self.stage = Stage.objects.create(
            tournament=self.tournament,
            stage_number=1,
            format='swiss',
            num_qualifiers=1,
            num_rounds_in_stage=3,
        )
        self.court = Court.objects.create(number=97001, is_available=True)
        self.tournament.courts.add(self.court)
        self.home_teams = [
            Team.objects.create(name=f'P2 Home Team {index}') for index in range(1, 5)
        ]
        self.players = []
        for index, home_team in enumerate(self.home_teams, start=1):
            player = Player.objects.create(
                name=f'P2 Player {index}', team=home_team, is_captain=(index == 1)
            )
            PlayerProfile.objects.create(player=player, value=100.0 + index)
            MeleePlayer.objects.create(
                tournament=self.tournament,
                player=player,
                original_team=home_team,
            )
            self.players.append(player)

    def _initial_round(self):
        return MeleeRoundAssignmentWriter.initial_round_for_generation(
            tournament=self.tournament
        )

    def _writer_inputs(self, first_team, second_team):
        return [
            MeleeRoundAssignmentInput(
                player=self.players[0],
                team=first_team,
                state=MeleeRoundAssignment.ASSIGNED,
            ),
            MeleeRoundAssignmentInput(
                player=self.players[1],
                team=first_team,
                state=MeleeRoundAssignment.ASSIGNED,
            ),
            MeleeRoundAssignmentInput(
                player=self.players[2],
                team=second_team,
                state=MeleeRoundAssignment.ASSIGNED,
            ),
            MeleeRoundAssignmentInput(
                player=self.players[3],
                team=second_team,
                state=MeleeRoundAssignment.ASSIGNED,
            ),
        ]

    def test_writer_calls_full_clean_before_each_assignment_save(self):
        """P2 does not rely on Django's default Model.save validation behavior."""
        first_team = Team.objects.create(name='P2 Writer Temp One', is_tournament_temp=True)
        second_team = Team.objects.create(name='P2 Writer Temp Two', is_tournament_temp=True)
        TournamentTeam.objects.create(tournament=self.tournament, team=first_team)
        TournamentTeam.objects.create(tournament=self.tournament, team=second_team)
        round_obj = self._initial_round()
        events = []
        original_full_clean = MeleeRoundAssignment.full_clean
        original_save = MeleeRoundAssignment.save

        def tracked_full_clean(instance, *args, **kwargs):
            events.append(('clean', instance.player_id))
            return original_full_clean(instance, *args, **kwargs)

        def tracked_save(instance, *args, **kwargs):
            self.assertIn(('clean', instance.player_id), events)
            events.append(('save', instance.player_id))
            return original_save(instance, *args, **kwargs)

        with patch.object(MeleeRoundAssignment, 'full_clean', new=tracked_full_clean), patch.object(
            MeleeRoundAssignment, 'save', new=tracked_save
        ):
            assignment_rows = MeleeRoundAssignmentWriter.write_complete_round(
                tournament=self.tournament,
                round=round_obj,
                assignments=self._writer_inputs(first_team, second_team),
            )

        self.assertEqual(len(assignment_rows), 4)
        for player in self.players:
            self.assertIn(('clean', player.id), events)
            self.assertIn(('save', player.id), events)
            self.assertLess(
                events.index(('clean', player.id)), events.index(('save', player.id))
            )

    def test_writer_rejects_cross_tournament_round_before_any_save(self):
        """The P2 writer enforces P1's cross-table Round/Tournament check itself."""
        foreign_tournament = Tournament.objects.create(
            name='P2 Foreign Tournament',
            format='multi_stage',
            play_format='doublets',
            is_melee=True,
            melee_format='doublets',
            start_date=timezone.now(),
            end_date=timezone.now() + timedelta(days=1),
        )
        foreign_stage = Stage.objects.create(
            tournament=foreign_tournament,
            stage_number=1,
            format='swiss',
            num_qualifiers=1,
            num_rounds_in_stage=1,
        )
        foreign_round = Round.objects.create(
            tournament=foreign_tournament,
            stage=foreign_stage,
            number=1,
            number_in_stage=1,
        )
        first_team = Team.objects.create(name='P2 Cross Temp One', is_tournament_temp=True)
        second_team = Team.objects.create(name='P2 Cross Temp Two', is_tournament_temp=True)
        TournamentTeam.objects.create(tournament=self.tournament, team=first_team)
        TournamentTeam.objects.create(tournament=self.tournament, team=second_team)

        with patch.object(MeleeRoundAssignment, 'save', autospec=True) as save_mock:
            with self.assertRaises(ValidationError):
                MeleeRoundAssignmentWriter.write_complete_round(
                    tournament=self.tournament,
                    round=foreign_round,
                    assignments=self._writer_inputs(first_team, second_team),
                )

        save_mock.assert_not_called()
        self.assertFalse(MeleeRoundAssignment.objects.exists())

    def test_writer_is_idempotent_but_rejects_a_different_existing_roster(self):
        """P2 cannot replace a round roster after the first successful write."""
        first_team = Team.objects.create(name='P2 Idempotent Temp One', is_tournament_temp=True)
        second_team = Team.objects.create(name='P2 Idempotent Temp Two', is_tournament_temp=True)
        TournamentTeam.objects.create(tournament=self.tournament, team=first_team)
        TournamentTeam.objects.create(tournament=self.tournament, team=second_team)
        round_obj = self._initial_round()
        inputs = self._writer_inputs(first_team, second_team)

        first_rows = MeleeRoundAssignmentWriter.write_complete_round(
            tournament=self.tournament,
            round=round_obj,
            assignments=inputs,
        )
        idempotent_rows = MeleeRoundAssignmentWriter.write_complete_round(
            tournament=self.tournament,
            round=round_obj,
            assignments=inputs,
        )
        self.assertEqual(
            sorted(row.id for row in first_rows),
            sorted(row.id for row in idempotent_rows),
        )

        conflicting_inputs = list(inputs)
        conflicting_inputs[0] = MeleeRoundAssignmentInput(
            player=self.players[0],
            team=second_team,
            state=MeleeRoundAssignment.ASSIGNED,
        )
        with self.assertRaises(MeleeRoundAssignmentWriteConflict):
            MeleeRoundAssignmentWriter.write_complete_round(
                tournament=self.tournament,
                round=round_obj,
                assignments=conflicting_inputs,
            )
        self.assertEqual(
            MeleeRoundAssignment.objects.filter(
                tournament=self.tournament, round=round_obj, team=first_team
            ).count(),
            2,
        )

    def test_initial_generation_writes_round_one_without_player_team_transfer(self):
        """P4 creates competition assignments while retaining home affiliation."""
        original_team_ids = {player.id: player.team_id for player in self.players}

        teams_created = self.tournament.generate_melee_teams(algorithm='balanced')

        self.assertEqual(teams_created, 2)
        round_one = Round.objects.get(
            tournament=self.tournament,
            stage=self.stage,
            number_in_stage=1,
        )
        assignments = list(
            MeleeRoundAssignment.objects.filter(
                tournament=self.tournament,
                round=round_one,
            ).select_related('player', 'team')
        )
        self.assertEqual(len(assignments), 4)
        self.assertTrue(
            all(assignment.state == MeleeRoundAssignment.ASSIGNED for assignment in assignments)
        )
        self.assertTrue(all(assignment.team.is_tournament_temp for assignment in assignments))

        # The existing Match generator must reuse P2's concrete Round rather
        # than create a competing Stage/local round identity.
        matches_created = self.tournament.generate_matches()
        self.assertEqual(matches_created, 1)
        self.assertEqual(
            Match.objects.get(tournament=self.tournament).round_id,
            round_one.id,
        )

        for assignment in assignments:
            melee_player = MeleePlayer.objects.get(
                tournament=self.tournament,
                player=assignment.player,
            )
            self.assertEqual(melee_player.assigned_team_id, assignment.team_id)
            self.assertEqual(melee_player.original_team_id, original_team_ids[assignment.player_id])
            assignment.player.refresh_from_db()
            self.assertEqual(assignment.player.team_id, original_team_ids[assignment.player_id])

        for temporary_team in self.tournament.tournamentteam_set.select_related('team').values_list(
            'team', flat=True
        ):
            team = Team.objects.get(pk=temporary_team)
            self.assertEqual(
                list(
                    MeleeRoundRosterService.players_for_team(
                        tournament=self.tournament,
                        round=round_one,
                        team=team,
                    ).values_list('id', flat=True)
                ),
                list(
                    MeleeRoundAssignment.objects.filter(
                        tournament=self.tournament,
                        round=round_one,
                        team=team,
                        state=MeleeRoundAssignment.ASSIGNED,
                    ).order_by('player__name', 'player_id').values_list('player_id', flat=True)
                ),
            )

    def test_initial_generation_records_incomplete_remainder_as_waitlisted(self):
        """P2 classifies legacy unassigned remainder Players explicitly."""
        extra_player = Player.objects.create(
            name='P2 Remainder Player', team=self.home_teams[0]
        )
        MeleePlayer.objects.create(
            tournament=self.tournament,
            player=extra_player,
            original_team=extra_player.team,
        )

        self.tournament.generate_melee_teams(algorithm='random')

        round_one = Round.objects.get(
            tournament=self.tournament,
            stage=self.stage,
            number_in_stage=1,
        )
        assignments = MeleeRoundAssignment.objects.filter(
            tournament=self.tournament, round=round_one
        )
        self.assertEqual(assignments.count(), 5)
        self.assertEqual(
            assignments.filter(state=MeleeRoundAssignment.WAITLISTED, team__isnull=True).count(),
            1,
        )
        self.assertEqual(assignments.filter(state=MeleeRoundAssignment.ASSIGNED).count(), 4)

    def test_initial_generation_rolls_back_if_assignment_writer_rejects_data(self):
        """A failed P2 write cannot leave the legacy Team projection half-written."""
        original_team_ids = {player.id: player.team_id for player in self.players}

        with patch.object(
            MeleeRoundAssignmentWriter,
            'write_current_generation_assignments',
            side_effect=ValidationError('P2 assignment validation failed'),
        ):
            with self.assertRaises(ValidationError):
                self.tournament.generate_melee_teams(algorithm='balanced')

        self.tournament.refresh_from_db()
        self.assertFalse(self.tournament.melee_teams_generated)
        self.assertFalse(
            TournamentTeam.objects.filter(tournament=self.tournament).exists()
        )
        self.assertFalse(
            MeleeRoundAssignment.objects.filter(tournament=self.tournament).exists()
        )
        for player in self.players:
            player.refresh_from_db()
            self.assertEqual(player.team_id, original_team_ids[player.id])

    def test_snake_generation_dual_writes_one_complete_round_roster(self):
        """Snake Draft retains its existing algorithm while also writing P2 data."""
        teams_created = self.tournament.generate_melee_teams(algorithm='snake_draft')

        self.assertEqual(teams_created, 2)
        round_one = Round.objects.get(
            tournament=self.tournament,
            stage=self.stage,
            number_in_stage=1,
        )
        assignments = MeleeRoundAssignment.objects.filter(
            tournament=self.tournament,
            round=round_one,
        )
        self.assertEqual(assignments.count(), 4)
        self.assertEqual(
            assignments.filter(state=MeleeRoundAssignment.ASSIGNED).count(),
            4,
        )

    def test_super_melee_shuffle_writes_exact_next_round_without_player_team_transfer(self):
        """P4 shuffle updates assignment state while retaining home affiliation."""
        original_team_ids = {player.id: player.team_id for player in self.players}
        self.tournament.generate_melee_teams(algorithm='balanced')
        round_one = Round.objects.get(
            tournament=self.tournament,
            stage=self.stage,
            number_in_stage=1,
        )
        first_round_team_ids = dict(
            MeleeRoundAssignment.objects.filter(
                tournament=self.tournament, round=round_one
            ).values_list('player_id', 'team_id')
        )

        def reverse_players(players):
            players.reverse()

        with patch('tournaments.shuffle_utils.random.shuffle', side_effect=reverse_players):
            result = shuffle_melee_players(
                tournament=self.tournament,
                shuffle_type='automatic',
                round_number=round_one.number,
                completed_round=round_one,
            )

        self.assertTrue(result['success'], result)
        round_two = Round.objects.get(
            tournament=self.tournament,
            stage=self.stage,
            number_in_stage=2,
        )
        second_round_assignments = list(
            MeleeRoundAssignment.objects.filter(
                tournament=self.tournament,
                round=round_two,
            ).select_related('player', 'team')
        )
        self.assertEqual(len(second_round_assignments), 4)
        self.assertTrue(
            all(assignment.state == MeleeRoundAssignment.ASSIGNED for assignment in second_round_assignments)
        )
        second_round_team_ids = {
            assignment.player_id: assignment.team_id
            for assignment in second_round_assignments
        }
        self.assertNotEqual(first_round_team_ids, second_round_team_ids)

        for assignment in second_round_assignments:
            assignment.player.refresh_from_db()
            self.assertEqual(
                assignment.player.team_id,
                original_team_ids[assignment.player_id],
            )
            self.assertEqual(
                MeleeRoundRosterService.assigned_team_for_player(
                    tournament=self.tournament,
                    round=round_two,
                    player=assignment.player,
                ).id,
                assignment.team_id,
            )
