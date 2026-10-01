from datetime import timedelta
from time import perf_counter

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


class SnakeDraftIndividualByeFairnessTests(TestCase):
    """Focused regression coverage for 4k+2 Super Mêlée doubles scheduling."""

    def setUp(self):
        now = timezone.now()
        self.tournament = Tournament.objects.create(
            name="Snake Draft Individual BYE Fairness",
            format="multi_stage",
            play_format="doublets",
            is_melee=True,
            melee_format="doublets",
            shuffle_players_after_round=True,
            start_date=now,
            end_date=now + timedelta(hours=8),
        )
        self.stage = Stage.objects.create(
            tournament=self.tournament,
            stage_number=1,
            format="swiss",
            num_qualifiers=1,
            num_rounds_in_stage=3,
        )
        self.court = Court.objects.create(number=97631, is_available=True)
        self.tournament.courts.add(self.court)
        self.players = []
        for number in range(1, 7):
            home_team = Team.objects.create(name=f"Snake BYE Home {number}")
            player = Player.objects.create(
                name=f"Snake BYE Player {number}",
                team=home_team,
            )
            PlayerProfile.objects.create(player=player, value=100.0 + number)
            MeleePlayer.objects.create(tournament=self.tournament, player=player)
            self.players.append(player)

    def _round(self, number):
        return Round.objects.get(
            tournament=self.tournament,
            stage=self.stage,
            number_in_stage=number,
        )

    def _complete_round_match(self, round_obj):
        match = Match.objects.get(tournament=self.tournament, round=round_obj)
        Match.objects.filter(pk=match.pk).update(
            status="completed",
            winner=match.team1,
            loser=match.team2,
            team1_score=13,
            team2_score=0,
        )

    def _generate_prepared_round_matches(self, number):
        teams = list(
            TournamentTeam.objects.filter(
                tournament=self.tournament,
                current_stage_number=self.stage.stage_number,
                is_active=True,
            ).select_related("team").order_by("team_id")
        )
        self.tournament.refresh_from_db()
        generated = TournamentEngine(self.tournament).generate_stage_round(
            self.stage,
            teams,
            number,
        )
        self.assertTrue(generated)

    def _bye_player_ids(self, round_obj):
        bye = MeleeRoundTeamBye.objects.get(
            tournament=self.tournament,
            round=round_obj,
        )
        return set(
            MeleeRoundAssignment.objects.filter(
                tournament=self.tournament,
                round=round_obj,
                team_id=bye.team_id,
                state=MeleeRoundAssignment.ASSIGNED,
            ).values_list("player_id", flat=True)
        )

    def test_six_players_receive_one_individual_bye_each_over_three_rounds(self):
        self.assertEqual(self.tournament.generate_melee_teams("snake_draft"), 3)
        self.tournament.refresh_from_db()
        self.assertEqual(
            self.tournament.melee_team_algorithm,
            Tournament.MELEE_TEAM_ALGORITHM_SNAKE_DRAFT,
        )
        self.assertEqual(self.tournament.generate_matches(), 1)

        round_one = self._round(1)
        self._complete_round_match(round_one)
        shuffle_one = shuffle_melee_players(
            tournament=self.tournament,
            shuffle_type="automatic",
            completed_round=round_one,
        )
        self.assertTrue(shuffle_one["success"], shuffle_one)
        self.assertEqual(len(self._bye_player_ids(round_one)), 2)

        round_two = self._round(2)
        self._generate_prepared_round_matches(2)
        self.assertEqual(Match.objects.filter(tournament=self.tournament, round=round_two).count(), 1)
        self._complete_round_match(round_two)
        shuffle_two = shuffle_melee_players(
            tournament=self.tournament,
            shuffle_type="automatic",
            completed_round=round_two,
        )
        self.assertTrue(shuffle_two["success"], shuffle_two)

        round_three = self._round(3)
        self._generate_prepared_round_matches(3)
        self.assertEqual(Match.objects.filter(tournament=self.tournament, round=round_three).count(), 1)

        bye_counts = {player.id: 0 for player in self.players}
        for round_obj in (round_one, round_two, round_three):
            bye_ids = self._bye_player_ids(round_obj)
            self.assertEqual(len(bye_ids), 2)
            for player_id in bye_ids:
                bye_counts[player_id] += 1

        self.assertEqual(set(bye_counts.values()), {1})
        self.assertEqual(
            {
                player.id: 3 - bye_counts[player.id]
                for player in self.players
            },
            {player.id: 2 for player in self.players},
        )

    def test_divisible_by_four_players_need_no_planned_bye(self):
        for number in range(7, 9):
            home_team = Team.objects.create(name=f"Snake Even Home {number}")
            player = Player.objects.create(
                name=f"Snake Even Player {number}",
                team=home_team,
            )
            PlayerProfile.objects.create(player=player, value=100.0 + number)
            MeleePlayer.objects.create(tournament=self.tournament, player=player)

        self.assertEqual(self.tournament.generate_melee_teams("snake_draft"), 4)
        self.assertEqual(self.tournament.generate_matches(), 2)
        round_one = self._round(1)
        for match in Match.objects.filter(tournament=self.tournament, round=round_one):
            Match.objects.filter(pk=match.pk).update(
                status="completed",
                winner=match.team1,
                loser=match.team2,
                team1_score=13,
                team2_score=0,
            )

        result = shuffle_melee_players(
            tournament=self.tournament,
            shuffle_type="automatic",
            completed_round=round_one,
        )
        self.assertTrue(result["success"], result)
        self.assertFalse(
            MeleeRoundTeamBye.objects.filter(
                tournament=self.tournament,
                round=self._round(2),
            ).exists()
        )


class SuperMeleeFiftyPlayerPerformanceSmokeTests(TestCase):
    """Benchmark a realistic 50-player Super Mêlée round transition."""

    def test_fifty_player_generation_and_shuffle_timing(self):
        now = timezone.now()
        tournament = Tournament.objects.create(
            name="50 Player Super Mêlée Performance",
            format="multi_stage",
            play_format="doublets",
            is_melee=True,
            melee_format="doublets",
            shuffle_players_after_round=True,
            start_date=now,
            end_date=now + timedelta(hours=8),
        )
        stage = Stage.objects.create(
            tournament=tournament,
            stage_number=1,
            format="swiss",
            num_qualifiers=1,
            num_rounds_in_stage=2,
        )
        court = Court.objects.create(number=97650, is_available=True)
        tournament.courts.add(court)

        for number in range(1, 51):
            home_team = Team.objects.create(name=f"Bench50 Home {number}")
            player = Player.objects.create(
                name=f"Bench50 Player {number}",
                team=home_team,
            )
            PlayerProfile.objects.create(player=player, value=100.0 + number)
            MeleePlayer.objects.create(tournament=tournament, player=player)

        generation_started = perf_counter()
        teams_created = tournament.generate_melee_teams("random")
        generation_ms = (perf_counter() - generation_started) * 1000
        self.assertEqual(teams_created, 25)

        matches_created = tournament.generate_matches()
        self.assertEqual(matches_created, 12)
        round_one = Round.objects.get(
            tournament=tournament,
            stage=stage,
            number_in_stage=1,
        )
        round_one_matches = list(
            Match.objects.filter(tournament=tournament, round=round_one)
        )
        self.assertEqual(len(round_one_matches), 12)
        for match in round_one_matches:
            Match.objects.filter(pk=match.pk).update(
                status="completed",
                winner=match.team1,
                loser=match.team2,
                team1_score=13,
                team2_score=0,
            )

        shuffle_started = perf_counter()
        shuffle_result = shuffle_melee_players(
            tournament=tournament,
            shuffle_type="automatic",
            completed_round=round_one,
        )
        shuffle_ms = (perf_counter() - shuffle_started) * 1000
        self.assertTrue(shuffle_result["success"], shuffle_result)

        round_two = Round.objects.get(
            tournament=tournament,
            stage=stage,
            number_in_stage=2,
        )
        round_two_assignments = MeleeRoundAssignment.objects.filter(
            tournament=tournament,
            round=round_two,
        ).count()
        self.assertEqual(round_two_assignments, 50)

        print(
            "BENCHMARK50 "
            f"generation_ms={generation_ms:.1f} "
            f"shuffle_ms={shuffle_ms:.1f} "
            f"total_ms={generation_ms + shuffle_ms:.1f} "
            f"teams={teams_created} "
            f"round1_matches={len(round_one_matches)} "
            f"round2_assignments={round_two_assignments}"
        )
