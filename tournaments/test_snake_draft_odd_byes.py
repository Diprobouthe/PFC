from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from courts.models import Court
from matches.models import Match
from teams.models import Player, PlayerProfile, Team
from tournaments.automation_engine import TournamentEngine
from tournaments.models import (
    MeleePlayer,
    MeleeRoundAssignment,
    MeleeRoundTeamBye,
    Round,
    Stage,
    Tournament,
    TournamentTeam,
)
from tournaments.shuffle_utils import shuffle_melee_players


class SnakeDraftOddPlayerByeTests(TestCase):
    def _make_tournament(self, player_count):
        now = timezone.now()
        tournament = Tournament.objects.create(
            name=f'Odd BYE scheduler fixture {player_count}',
            format='multi_stage',
            play_format='doublets',
            is_melee=True,
            melee_format='doublets',
            shuffle_players_after_round=True,
            start_date=now,
            end_date=now + timedelta(hours=8),
        )
        stage = Stage.objects.create(
            tournament=tournament,
            stage_number=1,
            format='swiss',
            num_qualifiers=1,
            num_rounds_in_stage=3,
        )
        court = Court.objects.create(number=85000 + player_count, is_available=True)
        tournament.courts.add(court)
        for number in range(player_count):
            home_team = Team.objects.create(
                name=f'Odd BYE {player_count} home {number}',
            )
            player = Player.objects.create(
                name=f'Odd BYE {player_count} player {number}',
                team=home_team,
            )
            PlayerProfile.objects.create(player=player, value=100.0 + number)
            MeleePlayer.objects.create(tournament=tournament, player=player)
        return tournament, stage

    @staticmethod
    def _round(tournament, stage, number):
        return Round.objects.get(
            tournament=tournament,
            stage=stage,
            number_in_stage=number,
        )

    @staticmethod
    def _complete_round(round_obj):
        for match in Match.objects.filter(round=round_obj):
            Match.objects.filter(pk=match.pk).update(
                status='completed',
                winner=match.team1,
                loser=match.team2,
                team1_score=13,
                team2_score=0,
            )

    @staticmethod
    def _generate_prepared_round(tournament, stage, number):
        teams = list(
            TournamentTeam.objects.filter(
                tournament=tournament,
                current_stage_number=stage.stage_number,
                is_active=True,
            ).select_related('team').order_by('team_id')
        )
        return TournamentEngine(tournament).generate_stage_round(stage, teams, number)

    def _assert_next_round(self, player_count, expected_matches, expected_individual_byes, expected_team_bye):
        tournament, stage = self._make_tournament(player_count)
        self.assertGreater(tournament.generate_melee_teams('snake_draft'), 0)
        self.assertEqual(tournament.generate_matches(), player_count // 4)
        round_one = self._round(tournament, stage, 1)
        self._complete_round(round_one)

        transition = shuffle_melee_players(
            tournament=tournament,
            shuffle_type='automatic',
            completed_round=round_one,
        )
        self.assertTrue(transition['success'], transition)

        round_two = self._round(tournament, stage, 2)
        assignments = MeleeRoundAssignment.objects.filter(
            tournament=tournament,
            round=round_two,
        )
        self.assertEqual(assignments.count(), player_count)
        self.assertEqual(
            assignments.values('player_id').distinct().count(),
            player_count,
        )
        self.assertEqual(
            assignments.filter(state=MeleeRoundAssignment.BYE).count(),
            expected_individual_byes,
        )
        self.assertEqual(
            MeleeRoundTeamBye.objects.filter(
                tournament=tournament,
                round=round_two,
            ).exists(),
            expected_team_bye,
        )

        self.assertTrue(self._generate_prepared_round(tournament, stage, 2))
        matches = Match.objects.filter(tournament=tournament, round=round_two)
        self.assertEqual(matches.count(), expected_matches)
        scheduled_player_ids = set()
        for match in matches:
            for team_id in (match.team1_id, match.team2_id):
                roster = assignments.filter(
                    team_id=team_id,
                    state=MeleeRoundAssignment.ASSIGNED,
                )
                self.assertEqual(roster.count(), 2)
                scheduled_player_ids.update(roster.values_list('player_id', flat=True))
        self.assertEqual(len(scheduled_player_ids), expected_matches * 4)
        self.assertFalse(
            scheduled_player_ids.intersection(
                assignments.filter(state=MeleeRoundAssignment.BYE).values_list(
                    'player_id', flat=True
                )
            )
        )

    def test_seven_players_schedule_one_match_and_three_individual_byes(self):
        self._assert_next_round(
            player_count=7,
            expected_matches=1,
            expected_individual_byes=1,
            expected_team_bye=True,
        )

    def test_nine_players_schedule_two_matches_and_one_individual_bye(self):
        self._assert_next_round(
            player_count=9,
            expected_matches=2,
            expected_individual_byes=1,
            expected_team_bye=False,
        )

    def test_eight_players_remain_a_no_bye_control(self):
        self._assert_next_round(
            player_count=8,
            expected_matches=2,
            expected_individual_byes=0,
            expected_team_bye=False,
        )
