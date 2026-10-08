from datetime import timedelta
from unittest.mock import patch

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from matches.models import Match
from matches.models_participant import TeamMatchParticipant
from teams.leaderboard_stats import bulk_player_leaderboard_stats
from teams.models import Player, PlayerProfile, Team
from tournaments.models import Tournament


class PlayerLeaderboardBulkStatsTests(TestCase):
    def setUp(self):
        self.team_a = Team.objects.create(name="Bulk Stats A")
        self.team_b = Team.objects.create(name="Bulk Stats B")
        self.player_a = Player.objects.create(name="Player A", team=self.team_a)
        self.player_b = Player.objects.create(name="Player B", team=self.team_b)
        self.profile_a = PlayerProfile.objects.create(player=self.player_a)
        self.profile_b = PlayerProfile.objects.create(player=self.player_b)

        now = timezone.now()
        self.tournament = Tournament.objects.create(
            name="Bulk Stats Tournament",
            format="round_robin",
            play_format="doublets",
            has_doublets=True,
            start_date=now,
            end_date=now + timedelta(hours=2),
        )

    def _completed_match(self, *, winner, loser):
        return Match.objects.create(
            tournament=self.tournament,
            team1=self.team_a,
            team2=self.team_b,
            team1_score=13 if winner == self.team_a else 8,
            team2_score=13 if winner == self.team_b else 8,
            status="completed",
            winner=winner,
            loser=loser,
            end_time=timezone.now(),
        )

    def test_bulk_projection_matches_existing_per_player_semantics(self):
        m1 = self._completed_match(winner=self.team_a, loser=self.team_b)
        m2 = self._completed_match(winner=self.team_b, loser=self.team_a)
        m3 = self._completed_match(winner=self.team_a, loser=self.team_b)

        TeamMatchParticipant.objects.create(
            match=m1, team=self.team_a, player=self.player_a,
            position="pointer", played=True,
        )
        TeamMatchParticipant.objects.create(
            match=m2, team=self.team_a, player=self.player_a,
            position="milieu", played=True,
        )
        TeamMatchParticipant.objects.create(
            match=m3, team=self.team_a, player=self.player_a,
            position="pointer", played=True,
        )

        TeamMatchParticipant.objects.create(
            match=m1, team=self.team_b, player=self.player_b,
            position="tirer", played=True,
        )
        TeamMatchParticipant.objects.create(
            match=m2, team=self.team_b, player=self.player_b,
            position="tirer", played=True,
        )

        projected = bulk_player_leaderboard_stats(
            [self.player_a.id, self.player_b.id]
        )

        old_overall_a = self.profile_a.get_accurate_statistics()
        old_positions_a = self.profile_a.get_position_stats()

        self.assertEqual(projected[self.player_a.id]["matches_played"], old_overall_a["matches_played"])
        self.assertEqual(projected[self.player_a.id]["matches_won"], old_overall_a["matches_won"])
        self.assertEqual(projected[self.player_a.id]["win_rate"], old_overall_a["win_rate"])
        self.assertEqual(projected[self.player_a.id]["position_stats"], old_positions_a)

        self.assertEqual(projected[self.player_b.id]["matches_played"], 2)
        self.assertEqual(projected[self.player_b.id]["matches_won"], 1)
        self.assertEqual(projected[self.player_b.id]["win_rate"], 50.0)
        self.assertEqual(
            projected[self.player_b.id]["position_stats"]["tirer"],
            {"matches_played": 2, "matches_won": 1, "win_rate": 50.0},
        )

    def test_bulk_projection_uses_one_query_for_many_players(self):
        players = []
        for index in range(40):
            player = Player.objects.create(
                name=f"Extra Player {index}",
                team=self.team_a if index % 2 == 0 else self.team_b,
            )
            PlayerProfile.objects.create(player=player)
            players.append(player)

        with CaptureQueriesContext(connection) as captured:
            stats = bulk_player_leaderboard_stats(player.id for player in players)
            # Force complete evaluation before leaving the query-count scope.
            self.assertEqual(len(stats), 40)

        self.assertEqual(len(captured), 1)

    def test_leaderboard_view_does_not_call_per_player_statistics_methods(self):
        for index in range(30):
            player = Player.objects.create(
                name=f"Leaderboard Player {index}",
                team=self.team_a if index % 2 == 0 else self.team_b,
            )
            PlayerProfile.objects.create(player=player)

        with (
            patch.object(
                PlayerProfile,
                "get_accurate_statistics",
                side_effect=AssertionError("per-player overall query path used"),
            ),
            patch.object(
                PlayerProfile,
                "get_position_stats",
                side_effect=AssertionError("per-player position query path used"),
            ),
            CaptureQueriesContext(connection) as captured,
        ):
            response = self.client.get(reverse("player_leaderboard"))

        self.assertEqual(response.status_code, 200)
        # Players + one grouped participation query + Team filter should remain
        # effectively constant as the roster grows.
        self.assertLessEqual(len(captured), 6)

    def test_incomplete_and_dnp_participations_do_not_count(self):
        completed = self._completed_match(winner=self.team_a, loser=self.team_b)
        pending = Match.objects.create(
            tournament=self.tournament,
            team1=self.team_a,
            team2=self.team_b,
            status="active",
        )
        TeamMatchParticipant.objects.create(
            match=completed, team=self.team_a, player=self.player_a,
            position="pointer", played=False,
        )
        TeamMatchParticipant.objects.create(
            match=pending, team=self.team_a, player=self.player_a,
            position="pointer", played=True,
        )

        projected = bulk_player_leaderboard_stats([self.player_a.id])
        self.assertEqual(projected[self.player_a.id]["matches_played"], 0)
        self.assertEqual(projected[self.player_a.id]["matches_won"], 0)
        self.assertEqual(projected[self.player_a.id]["position_stats"], {})
