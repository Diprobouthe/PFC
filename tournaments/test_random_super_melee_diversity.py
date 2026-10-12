import random
from collections import Counter
from itertools import combinations
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from datetime import timedelta

from teams.models import Player, Team
from tournaments.models import (
    MeleePlayer,
    MeleeRoundAssignment,
    Round,
    Stage,
    Tournament,
    TournamentTeam,
)
from tournaments.partnership_models import MeleePartnership
from tournaments.random_melee import (
    _partition_score,
    _zero_repeat_partition,
    build_random_diversity_plan,
)
from tournaments.shuffle_utils import shuffle_melee_players


class RandomSuperMeleeDiversityTests(TestCase):
    def _make_tournament(self, *, player_count, melee_format):
        now = timezone.now()
        play_format = "triplets" if melee_format == "triplets" else "doublets"
        tournament = Tournament.objects.create(
            name=f"Random Diversity {melee_format} {player_count}",
            format="multi_stage",
            play_format=play_format,
            has_triplets=melee_format == "triplets",
            has_doublets=melee_format == "doublets",
            is_melee=True,
            melee_format=melee_format,
            shuffle_players_after_round=True,
            start_date=now,
            end_date=now + timedelta(hours=8),
        )
        stage = Stage.objects.create(
            tournament=tournament,
            stage_number=1,
            format="swiss",
            num_qualifiers=1,
            num_rounds_in_stage=5,
        )
        players = []
        for number in range(1, player_count + 1):
            home_team = Team.objects.create(name=f"Random Home {melee_format} {number}")
            player = Player.objects.create(
                name=f"Random Player {melee_format} {number}",
                team=home_team,
            )
            MeleePlayer.objects.create(
                tournament=tournament,
                player=player,
                original_team=home_team,
            )
            players.append(player)

        with patch("tournaments.models.random.shuffle", side_effect=lambda rows: None):
            teams_created = tournament.generate_melee_teams("random")

        tournament.refresh_from_db()
        round_one = Round.objects.get(
            tournament=tournament,
            stage=stage,
            number_in_stage=1,
        )
        teams = list(
            TournamentTeam.objects.filter(
                tournament=tournament,
                team__is_tournament_temp=True,
            ).select_related("team").order_by("team_id")
        )
        return tournament, stage, players, [row.team for row in teams], round_one, teams_created

    def _historical_pair_set(self, tournament):
        return {
            tuple(sorted(pair))
            for pair in MeleePartnership.objects.filter(
                tournament=tournament,
            ).values_list("player1_id", "player2_id")
        }

    def _plan_groups(self, plan):
        grouped = {}
        for player_id, team in plan["assignments"].items():
            if team is not None:
                grouped.setdefault(team.id, []).append(player_id)
        return list(grouped.values())

    def test_doublets_next_random_round_avoids_all_previous_teammates_when_possible(self):
        tournament, _stage, _players, teams, round_one, teams_created = self._make_tournament(
            player_count=8,
            melee_format="doublets",
        )
        self.assertEqual(teams_created, 4)
        historical_pairs = self._historical_pair_set(tournament)
        self.assertEqual(len(historical_pairs), 4)

        melee_players = list(
            MeleePlayer.objects.filter(tournament=tournament)
            .select_related("player")
            .order_by("player_id")
        )
        plan = build_random_diversity_plan(
            tournament=tournament,
            melee_players=melee_players,
            teams=teams,
            completed_round=round_one,
            rng=random.Random(101),
        )

        self.assertTrue(plan["success"], plan)
        self.assertTrue(plan["zero_repeat_found"], plan)
        self.assertEqual(plan["diversity_score"][0], 0)
        self.assertEqual(plan["sitout_player_ids"], set())

        for group in self._plan_groups(plan):
            self.assertEqual(len(group), 2)
            for pair in combinations(group, 2):
                self.assertNotIn(tuple(sorted(pair)), historical_pairs)

    def test_triplets_next_random_round_avoids_all_previous_teammates_when_possible(self):
        tournament, _stage, _players, teams, round_one, teams_created = self._make_tournament(
            player_count=9,
            melee_format="triplets",
        )
        self.assertEqual(teams_created, 3)
        historical_pairs = self._historical_pair_set(tournament)
        self.assertEqual(len(historical_pairs), 9)

        melee_players = list(
            MeleePlayer.objects.filter(tournament=tournament)
            .select_related("player")
            .order_by("player_id")
        )
        plan = build_random_diversity_plan(
            tournament=tournament,
            melee_players=melee_players,
            teams=teams,
            completed_round=round_one,
            rng=random.Random(202),
        )

        self.assertTrue(plan["success"], plan)
        self.assertTrue(plan["zero_repeat_found"], plan)
        self.assertEqual(plan["diversity_score"][0], 0)
        for group in self._plan_groups(plan):
            self.assertEqual(len(group), 3)
            for pair in combinations(group, 2):
                self.assertNotIn(tuple(sorted(pair)), historical_pairs)

    def test_triplet_remainder_never_creates_four_player_team_and_rotates_sitout(self):
        tournament, _stage, _players, teams, round_one, teams_created = self._make_tournament(
            player_count=10,
            melee_format="triplets",
        )
        self.assertEqual(teams_created, 3)

        previous_waitlisted = set(
            MeleeRoundAssignment.objects.filter(
                tournament=tournament,
                round=round_one,
                state=MeleeRoundAssignment.WAITLISTED,
            ).values_list("player_id", flat=True)
        )
        self.assertEqual(len(previous_waitlisted), 1)

        melee_players = list(
            MeleePlayer.objects.filter(tournament=tournament)
            .select_related("player")
            .order_by("player_id")
        )
        plan = build_random_diversity_plan(
            tournament=tournament,
            melee_players=melee_players,
            teams=teams,
            completed_round=round_one,
            rng=random.Random(303),
        )

        self.assertTrue(plan["success"], plan)
        self.assertEqual(len(plan["sitout_player_ids"]), 1)
        self.assertTrue(plan["sitout_player_ids"].isdisjoint(previous_waitlisted))
        groups = self._plan_groups(plan)
        self.assertEqual(sorted(len(group) for group in groups), [3, 3, 3])
        self.assertEqual(
            sum(team is None for team in plan["assignments"].values()),
            1,
        )

    def test_random_shuffle_integration_writes_zero_repeat_round_two(self):
        tournament, stage, _players, _teams, round_one, _teams_created = self._make_tournament(
            player_count=8,
            melee_format="doublets",
        )
        historical_pairs = self._historical_pair_set(tournament)

        result = shuffle_melee_players(
            tournament=tournament,
            shuffle_type="automatic",
            completed_round=round_one,
        )
        self.assertTrue(result["success"], result)

        round_two = Round.objects.get(
            tournament=tournament,
            stage=stage,
            number_in_stage=2,
        )
        assignments = list(
            MeleeRoundAssignment.objects.filter(
                tournament=tournament,
                round=round_two,
                state=MeleeRoundAssignment.ASSIGNED,
            ).order_by("team_id", "player_id")
        )
        self.assertEqual(len(assignments), 8)

        by_team = {}
        for assignment in assignments:
            by_team.setdefault(assignment.team_id, []).append(assignment.player_id)
        self.assertEqual(sorted(len(group) for group in by_team.values()), [2, 2, 2, 2])
        for group in by_team.values():
            pair = tuple(sorted(group))
            self.assertNotIn(pair, historical_pairs)

    def test_core_doublets_simulation_keeps_five_rounds_pair_unique(self):
        partnership_counts = Counter()
        player_ids = list(range(1, 21))

        for round_number in range(1, 6):
            groups = _zero_repeat_partition(
                player_ids=player_ids,
                team_size=2,
                partnership_counts=partnership_counts,
                rng=random.Random(1000 + round_number),
            )
            self.assertIsNotNone(groups, f"Round {round_number} repeated a teammate unnecessarily")
            self.assertEqual(_partition_score(groups, partnership_counts)[0], 0)
            for group in groups:
                for pair in combinations(group, 2):
                    partnership_counts[tuple(sorted(pair))] += 1

        self.assertEqual(len(partnership_counts), 50)
        self.assertEqual(set(partnership_counts.values()), {1})

    def test_core_triplets_simulation_keeps_five_rounds_pair_unique(self):
        partnership_counts = Counter()
        player_ids = list(range(1, 31))

        for round_number in range(1, 6):
            groups = _zero_repeat_partition(
                player_ids=player_ids,
                team_size=3,
                partnership_counts=partnership_counts,
                rng=random.Random(2000 + round_number),
            )
            self.assertIsNotNone(groups, f"Round {round_number} repeated a teammate unnecessarily")
            self.assertEqual(_partition_score(groups, partnership_counts)[0], 0)
            self.assertEqual(sorted(len(group) for group in groups), [3] * 10)
            for group in groups:
                for pair in combinations(group, 2):
                    partnership_counts[tuple(sorted(pair))] += 1

        self.assertEqual(len(partnership_counts), 150)
        self.assertEqual(set(partnership_counts.values()), {1})

    def test_random_diversity_planner_is_not_used_by_snake_doublets(self):
        tournament, stage, _players, _teams, round_one, _teams_created = self._make_tournament(
            player_count=8,
            melee_format="doublets",
        )
        tournament.melee_team_algorithm = Tournament.MELEE_TEAM_ALGORITHM_SNAKE_DRAFT
        tournament.save(update_fields=["melee_team_algorithm"])

        # The actual Snake planner needs completed Match result snapshots. We
        # stop it at its own planner boundary and prove Random is never entered.
        with patch(
            "tournaments.random_melee.build_random_diversity_plan"
        ) as random_planner, patch(
            "tournaments.snake_draft.build_winner_loser_doubles_plan",
            return_value={"success": False, "message": "snake sentinel"},
        ) as snake_planner:
            result = shuffle_melee_players(
                tournament=tournament,
                shuffle_type="automatic",
                completed_round=round_one,
            )

        self.assertFalse(result["success"])
        self.assertEqual(result["message"], "snake sentinel")
        snake_planner.assert_called_once()
        random_planner.assert_not_called()
        self.assertFalse(
            MeleeRoundAssignment.objects.filter(
                tournament=tournament,
                round__stage=stage,
                round__number_in_stage=2,
            ).exists()
        )
