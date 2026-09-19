from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from matches.models import Match, MatchPlayer
from teams.models import Player, PlayerProfile, Team
from tournaments.models import PlayerTournamentHistory, Tournament


class PlayerTournamentHistoryDetailTests(TestCase):
    def setUp(self):
        now = timezone.now()
        self.tournament = Tournament.objects.create(
            name="Historical Tournament",
            play_format="doublets",
            start_date=now,
            end_date=now + timedelta(hours=2),
        )
        self.home_team = Team.objects.create(name="Current Affiliation", pin="260001")
        self.historical_team = Team.objects.create(name="Historical Side", pin="260002")
        self.opponent = Team.objects.create(name="Historical Opponent", pin="260003")
        self.player = Player.objects.create(name="History Player", team=self.home_team)
        self.entry = PlayerTournamentHistory.objects.create(
            player=self.player,
            tournament=self.tournament,
            tournament_name=self.tournament.name,
            tournament_date=now.date(),
            tournament_format="Knockout · Doublets",
            represented_teams=[{"id": self.historical_team.id, "name": self.historical_team.name}],
            matches_played=12,
            wins=7,
            losses=5,
            points_scored=120,
            points_against=98,
            rating_change="4.50",
        )
        for index in range(12):
            match = Match.objects.create(
                tournament=self.tournament,
                team1=self.historical_team,
                team2=self.opponent,
                status="completed",
                team1_score=13,
                team2_score=index % 10,
                winner=self.historical_team,
                loser=self.opponent,
                end_time=now + timedelta(minutes=index),
            )
            MatchPlayer.objects.create(
                match=match,
                player=self.player,
                team=self.historical_team,
                role="pointer",
            )

    def test_detail_is_paginated_and_uses_historical_match_side_not_current_affiliation(self):
        url = reverse(
            "player_tournament_history_detail",
            args=[self.player.id, self.tournament.id],
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Tournament summary")
        self.assertContains(response, "Historical Side")
        self.assertContains(response, "Load more Matches")
        self.assertEqual(response.context["rows"].__len__(), 10)
        self.assertTrue(response.context["has_more"])

        more_response = self.client.get(f"{url}?offset=10&fragment=matches")
        self.assertEqual(more_response.status_code, 200)
        self.assertNotContains(more_response, "Tournament summary")
        self.assertEqual(more_response.context["rows"].__len__(), 2)
        self.assertFalse(more_response.context["has_more"])

    def test_initial_profile_renders_only_the_compact_history_card(self):
        response = self.client.get(
            reverse("player_profile", args=[self.player.id]),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-history-expand')
        self.assertNotContains(response, 'Load more Matches')

    def test_detail_respects_the_existing_hidden_statistics_boundary(self):
        profile, _created = PlayerProfile.objects.get_or_create(player=self.player)
        profile.hide_public_statistics = True
        profile.save(update_fields=["hide_public_statistics"])
        response = self.client.get(
            reverse(
                "player_tournament_history_detail",
                args=[self.player.id, self.tournament.id],
            )
        )
        self.assertEqual(response.status_code, 403)
