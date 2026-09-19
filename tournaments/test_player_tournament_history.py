from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from friendly_games.models import PlayerCodename
from matches.models import Match, MatchPlayer
from teams.models import Player, PlayerProfile, Team
from tournaments.models import (
    PlayerTournamentAchievement,
    PlayerTournamentHistory,
    Round,
    Stage,
    Tournament,
    TournamentTeam,
)
from tournaments.partnership_models import MeleePlayerStats
from tournaments.player_history import record_finalized_tournament_history


class PlayerTournamentHistoryTests(TestCase):
    def setUp(self):
        now = timezone.now()
        self.tournament = Tournament.objects.create(
            name="Completed Team History",
            format="round_robin",
            play_format="doublets",
            start_date=now,
            end_date=now + timedelta(hours=2),
        )
        self.winners = Team.objects.create(name="Historic Winners")
        self.runners_up = Team.objects.create(name="Historic Runners Up")
        TournamentTeam.objects.create(tournament=self.tournament, team=self.winners)
        TournamentTeam.objects.create(tournament=self.tournament, team=self.runners_up)

        self.winner_players = [
            Player.objects.create(name=f"Winner {index}", team=self.winners)
            for index in range(1, 3)
        ]
        self.runner_players = [
            Player.objects.create(name=f"Runner {index}", team=self.runners_up)
            for index in range(1, 3)
        ]
        for player in self.winner_players + self.runner_players:
            PlayerProfile.objects.create(player=player, value=100.0, rating_history=[])

        self.match = Match.objects.create(
            tournament=self.tournament,
            team1=self.winners,
            team2=self.runners_up,
            status="pending",
        )
        Match.objects.filter(pk=self.match.pk).update(
            status="completed",
            team1_score=13,
            team2_score=7,
            winner=self.winners,
            loser=self.runners_up,
        )
        self.match.refresh_from_db()
        for player in self.winner_players:
            MatchPlayer.objects.create(match=self.match, player=player, team=self.winners)
        for player in self.runner_players:
            MatchPlayer.objects.create(match=self.match, player=player, team=self.runners_up)

        # History entries are explicitly linked to the completed Match rather
        # than to a player's mutable affiliation.
        profile = self.winner_players[0].profile
        profile.rating_history = [
            {"match_id": self.match.id, "change": 4.25},
            {"match_id": 999999, "change": 50},
        ]
        profile.save(update_fields=["rating_history"])

    def test_final_history_and_medals_use_match_snapshots_and_are_idempotent(self):
        replacement_affiliation = Team.objects.create(name="Later Home Team")
        player = self.winner_players[0]
        player.team = replacement_affiliation
        player.save(update_fields=["team"])

        first = record_finalized_tournament_history(self.tournament)
        second = record_finalized_tournament_history(self.tournament)

        self.assertTrue(first["recorded"])
        self.assertEqual(first["history_rows_created"], 4)
        self.assertEqual(first["medals_created"], 4)
        self.assertEqual(second["history_rows_created"], 0)
        self.assertEqual(second["medals_created"], 0)
        self.assertEqual(
            PlayerTournamentHistory.objects.filter(tournament=self.tournament).count(),
            4,
        )
        entry = PlayerTournamentHistory.objects.get(player=player, tournament=self.tournament)
        self.assertEqual(entry.matches_played, 1)
        self.assertEqual(entry.wins, 1)
        self.assertEqual(entry.losses, 0)
        self.assertEqual(entry.points_scored, 13)
        self.assertEqual(entry.points_against, 7)
        self.assertEqual(entry.rating_change, Decimal("4.25"))
        self.assertEqual(entry.represented_teams, [{"id": self.winners.id, "name": self.winners.name}])
        self.assertFalse(any(team["id"] == replacement_affiliation.id for team in entry.represented_teams))
        self.assertTrue(
            PlayerTournamentAchievement.objects.filter(
                player=player,
                tournament=self.tournament,
                award_type=PlayerTournamentAchievement.MEDAL_GOLD,
                historical_team=self.winners,
            ).exists()
        )
        self.assertEqual(
            PlayerTournamentAchievement.objects.filter(
                tournament=self.tournament,
                award_type=PlayerTournamentAchievement.MEDAL_BRONZE,
            ).count(),
            0,
        )

    def test_hidden_statistics_hide_history_until_the_player_opens_own_profile(self):
        player = self.winner_players[0]
        player.profile.hide_public_statistics = True
        player.profile.save(update_fields=["hide_public_statistics"])
        PlayerTournamentHistory.objects.create(
            player=player,
            tournament=self.tournament,
            tournament_name=self.tournament.name,
            tournament_date=self.tournament.start_date.date(),
            tournament_format="Round Robin · Doublets",
            represented_teams=[{"id": self.winners.id, "name": self.winners.name}],
            matches_played=1,
            wins=1,
            losses=0,
            points_scored=13,
            points_against=7,
        )

        profile_url = reverse("player_profile", kwargs={"player_id": player.id})
        public_response = self.client.get(profile_url)
        self.assertEqual(public_response.status_code, 200)
        self.assertEqual(list(public_response.context["tournament_history"]), [])
        self.assertNotContains(public_response, self.tournament.name)

        codename = PlayerCodename.objects.create(player=player, codename="HISTORY001")
        session = self.client.session
        session["player_codename"] = codename.codename
        session["session_active"] = True
        session.save()
        own_response = self.client.get(profile_url)
        self.assertEqual(own_response.status_code, 200)
        self.assertEqual(len(own_response.context["tournament_history"]), 1)
        self.assertContains(own_response, self.tournament.name)

    def test_alternate_complete_match_path_projects_final_history(self):
        now = timezone.now()
        tournament = Tournament.objects.create(
            name="Alternate Completion History",
            format="round_robin",
            play_format="doublets",
            start_date=now,
            end_date=now + timedelta(hours=2),
        )
        team_one = Team.objects.create(name="Alternate Team One")
        team_two = Team.objects.create(name="Alternate Team Two")
        TournamentTeam.objects.create(tournament=tournament, team=team_one)
        TournamentTeam.objects.create(tournament=tournament, team=team_two)
        player_one = Player.objects.create(name="Alternate Player One", team=team_one)
        player_two = Player.objects.create(name="Alternate Player Two", team=team_two)
        match = Match.objects.create(
            tournament=tournament,
            team1=team_one,
            team2=team_two,
            status="pending",
        )
        MatchPlayer.objects.create(match=match, player=player_one, team=team_one)
        MatchPlayer.objects.create(match=match, player=player_two, team=team_two)

        match.complete_match(13, 9)

        self.assertTrue(
            PlayerTournamentHistory.objects.filter(
                player=player_one,
                tournament=tournament,
                matches_played=1,
                wins=1,
                points_scored=13,
            ).exists()
        )
        self.assertTrue(
            PlayerTournamentAchievement.objects.filter(
                player=player_one,
                tournament=tournament,
                award_type=PlayerTournamentAchievement.MEDAL_GOLD,
            ).exists()
        )


class MeleeTournamentAchievementTests(TestCase):
    def test_melee_awards_use_existing_calculator_and_never_create_team_medals(self):
        now = timezone.now()
        tournament = Tournament.objects.create(
            name="Final Mêlée Awards",
            format="multi_stage",
            play_format="doublets",
            is_melee=True,
            melee_format="doublets",
            start_date=now,
            end_date=now + timedelta(hours=2),
        )
        stage = Stage.objects.create(
            tournament=tournament,
            stage_number=1,
            format="swiss",
            num_qualifiers=1,
            num_rounds_in_stage=1,
        )
        round_obj = Round.objects.create(
            tournament=tournament,
            stage=stage,
            number=1,
            number_in_stage=1,
            is_complete=True,
        )
        team_one = Team.objects.create(name="Mêlée Historic One", is_tournament_temp=True)
        team_two = Team.objects.create(name="Mêlée Historic Two", is_tournament_temp=True)
        player_one = Player.objects.create(name="Mêlée Award One", team=team_one)
        player_two = Player.objects.create(name="Mêlée Award Two", team=team_two)
        PlayerProfile.objects.create(player=player_one, value=120.0)
        PlayerProfile.objects.create(player=player_two, value=100.0)
        match = Match.objects.create(
            tournament=tournament,
            stage=stage,
            round=round_obj,
            team1=team_one,
            team2=team_two,
            status="pending",
        )
        Match.objects.filter(pk=match.pk).update(
            status="completed",
            team1_score=13,
            team2_score=5,
            winner=team_one,
            loser=team_two,
        )
        MatchPlayer.objects.create(match=match, player=player_one, team=team_one)
        MatchPlayer.objects.create(match=match, player=player_two, team=team_two)
        MeleePlayerStats.objects.create(
            tournament=tournament,
            player=player_one,
            starting_rating=100,
            matches_played=3,
            wins=3,
            losses=0,
            points_scored=30,
            points_against=10,
            current_streak=3,
        )
        MeleePlayerStats.objects.create(
            tournament=tournament,
            player=player_two,
            starting_rating=100,
            matches_played=3,
            wins=1,
            losses=2,
            points_scored=10,
            points_against=30,
            current_streak=0,
        )

        result = record_finalized_tournament_history(tournament, include_melee_awards=True)

        self.assertTrue(result["recorded"])
        self.assertEqual(result["history_rows_created"], 2)
        self.assertEqual(result["medals_created"], 0)
        self.assertEqual(result["melee_awards_created"], 4)
        self.assertEqual(
            set(
                PlayerTournamentAchievement.objects.filter(
                    tournament=tournament,
                    player=player_one,
                ).values_list("award_type", flat=True)
            ),
            {
                PlayerTournamentAchievement.MOST_IMPROVED,
                PlayerTournamentAchievement.WIN_STREAK,
                PlayerTournamentAchievement.TOP_SCORER,
                PlayerTournamentAchievement.BEST_WIN_RATE,
            },
        )
        self.assertFalse(
            PlayerTournamentAchievement.objects.filter(
                tournament=tournament,
                award_type__startswith="medal_",
            ).exists()
        )
