from datetime import timedelta

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from friendly_games.models import FriendlyGame, FriendlyGamePlayer
from matches.models import Match, MatchPlayer
from matches.models_participant import TeamMatchParticipant
from teams.models import Player, PlayerProfile, Team
from tournaments.models import Tournament


class PlayerProfileMatchHistoryPaginationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        now = timezone.now()
        cls.team = Team.objects.create(name="History Team", pin="270001")
        cls.opponent = Team.objects.create(name="History Opponent", pin="270002")
        cls.player = Player.objects.create(name="Heavy History Player", team=cls.team)
        cls.profile, _created = PlayerProfile.objects.get_or_create(player=cls.player)

        cls.tournament = Tournament.objects.create(
            name="Profile History Tournament",
            play_format="doublets",
            start_date=now - timedelta(days=10),
            end_date=now + timedelta(days=1),
        )

        cls.matches = []
        for index in range(61):
            match = Match.objects.create(
                tournament=cls.tournament,
                team1=cls.team,
                team2=cls.opponent,
                status="completed",
                team1_score=13,
                team2_score=index % 13,
                winner=cls.team,
                loser=cls.opponent,
                end_time=now - timedelta(minutes=index),
            )
            TeamMatchParticipant.objects.create(
                match=match,
                team=cls.team,
                player=cls.player,
                position="pointer",
                played=True,
            )
            MatchPlayer.objects.create(
                match=match,
                player=cls.player,
                team=cls.team,
                role="pointer",
            )
            cls.matches.append(match)

        cls.friendlies = []
        for index in range(61):
            game = FriendlyGame.objects.create(
                name=f"Profile Friendly {index}",
                match_number=f"{2000 + index:04d}",
                status="COMPLETED",
                black_team_score=13,
                white_team_score=index % 13,
                completed_at=now - timedelta(minutes=index),
            )
            FriendlyGame.objects.filter(pk=game.pk).update(
                created_at=now - timedelta(minutes=index)
            )
            game.refresh_from_db()
            FriendlyGamePlayer.objects.create(
                game=game,
                player=cls.player,
                team="BLACK",
                position="POINTEUR",
                codename_verified=True,
                games_won=1,
            )
            cls.friendlies.append(game)

    def test_initial_profile_does_not_render_full_match_history(self):
        response = self.client.get(
            reverse("player_profile", args=[self.player.id]),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["tournament_match_history_count"], 61)
        self.assertEqual(response.context["friendly_match_history_count"], 61)
        self.assertContains(response, 'id="player-overall-tournament-history"')
        self.assertContains(response, 'id="player-overall-friendly-history"')
        self.assertContains(response, 'id="player-friendly-tab-friendly-history"')

        self.assertNotContains(
            response,
            reverse("match_detail", args=[self.matches[-1].id]),
        )
        self.assertNotContains(
            response,
            reverse(
                "friendly_games:game_detail",
                args=[self.friendlies[-1].id],
            ),
        )

    def test_tournament_history_every_match_remains_reachable(self):
        url = reverse("player_match_history_page", args=[self.player.id])

        page1 = self.client.get(url, {"kind": "tournament", "page": 1}).json()
        page2 = self.client.get(url, {"kind": "tournament", "page": 2}).json()
        page3 = self.client.get(url, {"kind": "tournament", "page": 3}).json()

        self.assertEqual(page1["total"], 61)
        self.assertEqual(page1["html"].count('class="mh-card'), 30)
        self.assertTrue(page1["has_next"])
        self.assertEqual(page1["next_page"], 2)

        self.assertEqual(page2["html"].count('class="mh-card'), 30)
        self.assertTrue(page2["has_next"])
        self.assertEqual(page2["next_page"], 3)

        self.assertEqual(page3["html"].count('class="mh-card'), 1)
        self.assertFalse(page3["has_next"])
        self.assertIsNone(page3["next_page"])
        self.assertIn(
            reverse("match_detail", args=[self.matches[-1].id]),
            page3["html"],
        )

    def test_friendly_history_every_game_remains_reachable(self):
        url = reverse("player_match_history_page", args=[self.player.id])

        page1 = self.client.get(url, {"kind": "friendly", "page": 1}).json()
        page2 = self.client.get(url, {"kind": "friendly", "page": 2}).json()
        page3 = self.client.get(url, {"kind": "friendly", "page": 3}).json()

        self.assertEqual(page1["total"], 61)
        self.assertEqual(page1["html"].count('class="mh-card'), 30)
        self.assertTrue(page1["has_next"])
        self.assertEqual(page1["next_page"], 2)

        self.assertEqual(page2["html"].count('class="mh-card'), 30)
        self.assertTrue(page2["has_next"])
        self.assertEqual(page2["next_page"], 3)

        self.assertEqual(page3["html"].count('class="mh-card'), 1)
        self.assertFalse(page3["has_next"])
        self.assertIsNone(page3["next_page"])
        self.assertIn(
            reverse(
                "friendly_games:game_detail",
                args=[self.friendlies[-1].id],
            ),
            page3["html"],
        )

    def test_history_pages_are_bounded_and_avoid_n_plus_one_queries(self):
        url = reverse("player_match_history_page", args=[self.player.id])

        with CaptureQueriesContext(connection) as captured:
            response = self.client.get(
                url,
                {"kind": "tournament", "page": 1},
            )
            self.assertEqual(response.status_code, 200)
        self.assertLessEqual(
            len(captured),
            4,
            msg="Tournament history should be player + COUNT + page + MatchPlayer map.",
        )

        with CaptureQueriesContext(connection) as captured:
            response = self.client.get(
                url,
                {"kind": "friendly", "page": 1},
            )
            self.assertEqual(response.status_code, 200)
        self.assertLessEqual(
            len(captured),
            3,
            msg="Friendly history should be player + COUNT + one bounded page query.",
        )

    def test_hidden_statistics_boundary_applies_to_lazy_history(self):
        self.profile.hide_public_statistics = True
        self.profile.save(update_fields=["hide_public_statistics"])

        response = self.client.get(
            reverse("player_match_history_page", args=[self.player.id]),
            {"kind": "tournament", "page": 1},
        )
        self.assertEqual(response.status_code, 403)

    def test_invalid_history_requests_fail_closed(self):
        url = reverse("player_match_history_page", args=[self.player.id])
        self.assertEqual(self.client.get(url, {"kind": "bad"}).status_code, 400)
        self.assertEqual(
            self.client.get(
                url,
                {"kind": "tournament", "page": 999},
            ).status_code,
            400,
        )
