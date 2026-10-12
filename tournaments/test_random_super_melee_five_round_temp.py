from collections import defaultdict
from datetime import timedelta
from itertools import combinations

from django.test import TestCase
from django.utils import timezone

from teams.models import Player, Team
from tournaments.models import (
    MeleePlayer,
    MeleeRoundAssignment,
    Round,
    Stage,
    Tournament,
)
from tournaments.partnership_models import MeleePartnership
from tournaments.shuffle_utils import shuffle_melee_players


class RandomSuperMeleeFiveRoundIntegrationTests(TestCase):
    def _make(self, *, player_count, melee_format):
        now = timezone.now()
        tournament = Tournament.objects.create(
            name=f"Five Round Random {melee_format}",
            format="multi_stage",
            play_format="triplets" if melee_format == "triplets" else "doublets",
            has_triplets=melee_format == "triplets",
            has_doublets=melee_format == "doublets",
            is_melee=True,
            melee_format=melee_format,
            melee_team_algorithm=Tournament.MELEE_TEAM_ALGORITHM_RANDOM,
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
        for number in range(1, player_count + 1):
            home = Team.objects.create(name=f"Home {melee_format} {number}")
            player = Player.objects.create(
                name=f"Player {melee_format} {number}",
                team=home,
            )
            MeleePlayer.objects.create(
                tournament=tournament,
                player=player,
                original_team=home,
            )

        teams_created = tournament.generate_melee_teams("random")
        tournament.refresh_from_db()
        return tournament, stage, teams_created

    def _round_groups(self, tournament, round_obj):
        grouped = defaultdict(list)
        rows = MeleeRoundAssignment.objects.filter(
            tournament=tournament,
            round=round_obj,
            state=MeleeRoundAssignment.ASSIGNED,
        ).order_by("team_id", "player_id")
        for row in rows:
            grouped[row.team_id].append(row.player_id)
        return list(grouped.values())

    def _pair_set(self, groups):
        pairs = set()
        for group in groups:
            for pair in combinations(group, 2):
                pairs.add(tuple(sorted(pair)))
        return pairs

    def _run_five_rounds(self, *, player_count, melee_format, expected_team_size):
        tournament, stage, teams_created = self._make(
            player_count=player_count,
            melee_format=melee_format,
        )
        self.assertEqual(
            teams_created,
            player_count // expected_team_size,
        )

        seen_pairs = set()
        round_pair_counts = []

        for round_number in range(1, 6):
            round_obj = Round.objects.get(
                tournament=tournament,
                stage=stage,
                number_in_stage=round_number,
            )
            groups = self._round_groups(tournament, round_obj)

            self.assertEqual(
                len(groups),
                player_count // expected_team_size,
                f"Round {round_number} has the wrong Team count",
            )
            self.assertEqual(
                sorted(len(group) for group in groups),
                [expected_team_size] * (player_count // expected_team_size),
                f"Round {round_number} has an invalid Team size",
            )

            round_pairs = self._pair_set(groups)
            self.assertTrue(
                seen_pairs.isdisjoint(round_pairs),
                f"Round {round_number} repeated teammate pairs: {seen_pairs.intersection(round_pairs)}",
            )
            seen_pairs.update(round_pairs)
            round_pair_counts.append(len(round_pairs))

            persisted_pairs = set(
                tuple(sorted(pair))
                for pair in MeleePartnership.objects.filter(
                    tournament=tournament,
                    round=round_obj,
                ).values_list("player1_id", "player2_id")
            )
            self.assertEqual(
                persisted_pairs,
                round_pairs,
                f"Round {round_number} persisted partnership history does not match its roster",
            )

            if round_number < 5:
                result = shuffle_melee_players(
                    tournament=tournament,
                    shuffle_type="automatic",
                    completed_round=round_obj,
                )
                self.assertTrue(
                    result["success"],
                    f"Round {round_number} -> {round_number + 1} shuffle failed: {result}",
                )

        expected_pairs_per_round = (
            (player_count // expected_team_size)
            * (expected_team_size * (expected_team_size - 1) // 2)
        )
        self.assertEqual(
            round_pair_counts,
            [expected_pairs_per_round] * 5,
        )
        self.assertEqual(
            len(seen_pairs),
            expected_pairs_per_round * 5,
        )
        self.assertEqual(
            MeleePartnership.objects.filter(tournament=tournament).count(),
            expected_pairs_per_round * 5,
        )

    def test_twenty_player_doublets_five_real_shuffle_rounds_have_no_repeat_teammates(self):
        self._run_five_rounds(
            player_count=20,
            melee_format="doublets",
            expected_team_size=2,
        )

    def test_thirty_player_triplets_five_real_shuffle_rounds_have_no_repeat_teammates(self):
        self._run_five_rounds(
            player_count=30,
            melee_format="triplets",
            expected_team_size=3,
        )
