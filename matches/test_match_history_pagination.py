from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from friendly_games.models import FriendlyGame
from matches.models import Match
from teams.models import Team
from tournaments.models import Tournament


class MatchHistoryPaginationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.team1 = Team.objects.create(name="History Team A")
        cls.team2 = Team.objects.create(name="History Team B")
        cls.other_team1 = Team.objects.create(name="Other History Team A")
        cls.other_team2 = Team.objects.create(name="Other History Team B")

        now = timezone.now()
        cls.tournament = Tournament.objects.create(
            name="History Tournament",
            format="knockout",
            play_format="doublets",
            start_date=now - timedelta(days=10),
            end_date=now + timedelta(days=1),
        )
        cls.other_tournament = Tournament.objects.create(
            name="Other History Tournament",
            format="knockout",
            play_format="doublets",
            start_date=now - timedelta(days=10),
            end_date=now + timedelta(days=1),
        )

        cls.matches = []
        for i in range(61):
            cls.matches.append(
                Match.objects.create(
                    tournament=cls.tournament,
                    team1=cls.team1,
                    team2=cls.team2,
                    status="completed",
                    team1_score=13,
                    team2_score=i % 13,
                    end_time=now - timedelta(minutes=i),
                )
            )

        cls.other_match = Match.objects.create(
            tournament=cls.other_tournament,
            team1=cls.other_team1,
            team2=cls.other_team2,
            status="completed",
            team1_score=13,
            team2_score=8,
            end_time=now + timedelta(minutes=1),
        )

        cls.friendlies = []
        for i in range(61):
            cls.friendlies.append(
                FriendlyGame.objects.create(
                    name=f"History Friendly {i}",
                    match_number=f"{1000 + i:04d}",
                    status="COMPLETED",
                    black_team_score=13,
                    white_team_score=i % 13,
                    completed_at=now - timedelta(minutes=i),
                )
            )

    def test_initial_match_list_keeps_full_counts_without_rendering_history(self):
        response = self.client.get(reverse("match_list"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["completed_count"], 62)
        self.assertEqual(response.context["friendly_completed_count"], 61)

        completed_url = reverse("match_detail", args=[self.matches[0].id])
        friendly_url = reverse(
            "friendly_games:game_detail",
            args=[self.friendlies[0].id],
        )
        self.assertNotContains(response, completed_url)
        self.assertNotContains(response, friendly_url)

        self.assertContains(response, 'id="tournament-history-list"')
        self.assertContains(response, 'id="friendly-history-list"')

    def test_tournament_history_every_record_remains_reachable(self):
        url = reverse("match_history_page")

        page1 = self.client.get(url, {"kind": "tournament", "page": 1}).json()
        page2 = self.client.get(url, {"kind": "tournament", "page": 2}).json()
        page3 = self.client.get(url, {"kind": "tournament", "page": 3}).json()

        self.assertEqual(page1["total"], 62)
        self.assertEqual(page1["html"].count('class="ml-card"'), 30)
        self.assertTrue(page1["has_next"])
        self.assertEqual(page1["next_page"], 2)

        self.assertEqual(page2["html"].count('class="ml-card"'), 30)
        self.assertTrue(page2["has_next"])
        self.assertEqual(page2["next_page"], 3)

        self.assertEqual(page3["html"].count('class="ml-card"'), 2)
        self.assertFalse(page3["has_next"])
        self.assertIsNone(page3["next_page"])

        oldest_url = reverse("match_detail", args=[self.matches[-1].id])
        self.assertIn(oldest_url, page3["html"])

    def test_tournament_scoped_history_preserves_scope_and_all_pages(self):
        url = reverse("match_history_page")

        page1 = self.client.get(
            url,
            {
                "kind": "tournament",
                "page": 1,
                "tournament_id": self.tournament.id,
            },
        ).json()
        page3 = self.client.get(
            url,
            {
                "kind": "tournament",
                "page": 3,
                "tournament_id": self.tournament.id,
            },
        ).json()

        self.assertEqual(page1["total"], 61)
        self.assertEqual(page3["html"].count('class="ml-card"'), 1)
        self.assertIn(
            reverse("match_detail", args=[self.matches[-1].id]),
            page3["html"],
        )
        self.assertNotIn(
            reverse("match_detail", args=[self.other_match.id]),
            page1["html"] + page3["html"],
        )

    def test_friendly_history_every_record_remains_reachable(self):
        url = reverse("match_history_page")

        page1 = self.client.get(url, {"kind": "friendly", "page": 1}).json()
        page2 = self.client.get(url, {"kind": "friendly", "page": 2}).json()
        page3 = self.client.get(url, {"kind": "friendly", "page": 3}).json()

        self.assertEqual(page1["total"], 61)
        self.assertEqual(page1["html"].count('class="ml-card"'), 30)
        self.assertTrue(page1["has_next"])
        self.assertEqual(page1["next_page"], 2)

        self.assertEqual(page2["html"].count('class="ml-card"'), 30)
        self.assertTrue(page2["has_next"])
        self.assertEqual(page2["next_page"], 3)

        self.assertEqual(page3["html"].count('class="ml-card"'), 1)
        self.assertFalse(page3["has_next"])
        self.assertIsNone(page3["next_page"])
        self.assertIn(
            reverse(
                "friendly_games:game_detail",
                args=[self.friendlies[-1].id],
            ),
            page3["html"],
        )

    def test_invalid_history_requests_fail_closed(self):
        url = reverse("match_history_page")
        self.assertEqual(self.client.get(url, {"kind": "unknown"}).status_code, 400)
        self.assertEqual(
            self.client.get(url, {"kind": "tournament", "page": 999}).status_code,
            400,
        )
        self.assertEqual(
            self.client.get(
                url,
                {"kind": "tournament", "tournament_id": "not-an-id"},
            ).status_code,
            400,
        )
