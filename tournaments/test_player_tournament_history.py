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

        codename = PlayerCodename.objects.create(player=player, codename="HIS001")
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

        Match.objects.filter(pk=match.pk).update(status="active")
        match.refresh_from_db()
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
    def test_incomplete_melee_stats_never_freeze_podium_or_awards(self):
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
            best_performance=3,
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
        self.assertEqual(result["melee_awards_created"], 0)
        self.assertFalse(
            PlayerTournamentAchievement.objects.filter(
                tournament=tournament, player=player_one
            ).exists()
        )
        self.assertFalse(
            PlayerTournamentAchievement.objects.filter(
                tournament=tournament,
                award_type__startswith="medal_",
            ).exists()
        )


class MeleeFireAwardTests(TestCase):
    """The fire badge honours the best streak reached, not the final streak."""

    def test_last_round_loss_does_not_erase_earned_fire(self):
        from types import SimpleNamespace
        from tournaments.melee_leaderboard_view import calculate_melee_badges

        def stats(pid, best, current, wins=3, games=4):
            return SimpleNamespace(
                player=SimpleNamespace(id=pid),
                starting_rating=100,
                current_rating=100,
                best_performance=best,
                current_streak=current,
                wins=wins,
                matches_played=games,
                points_scored=15,
            )

        first = stats(1, best=3, current=-1)
        second = stats(2, best=2, current=2, wins=2)
        badges = calculate_melee_badges([first, second])

        self.assertEqual(
            [badge["type"] for badge in badges[1] if badge["type"] == "streak"],
            ["streak"],
        )
        self.assertEqual(
            [badge["title"] for badge in badges[1] if badge["type"] == "streak"],
            ["Win Streak: 3"],
        )
        self.assertFalse(any(badge["type"] == "streak" for badge in badges[2]))

    def test_shared_best_streak_awards_both_players(self):
        from types import SimpleNamespace
        from tournaments.melee_leaderboard_view import calculate_melee_badges

        def stats(pid, current):
            return SimpleNamespace(
                player=SimpleNamespace(id=pid),
                starting_rating=100,
                current_rating=100,
                best_performance=4,
                current_streak=current,
                wins=4,
                matches_played=5,
                points_scored=18,
            )

        badges = calculate_melee_badges([stats(1, -1), stats(2, 4)])
        self.assertTrue(all(
            any(badge["type"] == "streak" for badge in badges[pid])
            for pid in (1, 2)
        ))

    def test_no_fire_under_three_consecutive_wins(self):
        from types import SimpleNamespace
        from tournaments.melee_leaderboard_view import calculate_melee_badges

        stats = SimpleNamespace(
            player=SimpleNamespace(id=1),
            starting_rating=100,
            current_rating=100,
            best_performance=2,
            current_streak=2,
            wins=2,
            matches_played=3,
            points_scored=10,
        )
        badges = calculate_melee_badges([stats])
        self.assertFalse(any(badge["type"] == "streak" for badge in badges[1]))


class FrozenMeleePodiumTests(TestCase):
    """Archived standings and player podium medals survive unrelated ratings."""

    def setUp(self):
        now = timezone.now()
        self.tournament = Tournament.objects.create(
            name="Frozen Mêlée",
            format="multi_stage",
            play_format="doublets",
            is_melee=True,
            melee_format="doublets",
            start_date=now,
            end_date=now + timedelta(hours=2),
        )
        self.stage = Stage.objects.create(
            tournament=self.tournament,
            stage_number=1,
            format="swiss",
            num_qualifiers=1,
            num_rounds_in_stage=1,
        )
        self.round = Round.objects.create(
            tournament=self.tournament,
            stage=self.stage,
            number=1,
            number_in_stage=1,
            is_complete=True,
        )
        teams = [
            Team.objects.create(name=f"Frozen Team {number}", is_tournament_temp=True)
            for number in (1, 2)
        ]
        self.match = Match.objects.create(
            tournament=self.tournament,
            stage=self.stage,
            round=self.round,
            team1=teams[0],
            team2=teams[1],
            status="pending",
        )
        Match.objects.filter(pk=self.match.pk).update(
            status="completed",
            team1_score=13,
            team2_score=4,
            winner=teams[0],
            loser=teams[1],
        )
        self.players = []
        for idx, delta in enumerate((5, 4, -3, -4)):
            team = teams[0] if idx < 2 else teams[1]
            player = Player.objects.create(name=f"Frozen Player {idx}", team=team)
            PlayerProfile.objects.create(
                player=player,
                value=100 + delta,
                rating_history=[{"match_id": self.match.pk, "change": delta}],
            )
            MatchPlayer.objects.create(match=self.match, team=team, player=player)
            MeleePlayerStats.objects.create(
                tournament=self.tournament,
                player=player,
                starting_rating=100,
                wins=int(idx < 2),
                losses=int(idx >= 2),
                matches_played=1,
                points_scored=13 if idx < 2 else 4,
                points_against=4 if idx < 2 else 13,
                best_performance=int(idx < 2),
            )
            self.players.append(player)

    def test_freeze_podium_and_profile_medals_ignore_later_friendly_ratings(self):
        result = record_finalized_tournament_history(
            self.tournament, include_melee_awards=True
        )
        self.assertTrue(result["recorded"])
        self.assertEqual(result["medals_created"], 3)
        self.assertEqual(
            list(
                PlayerTournamentHistory.objects.filter(
                    tournament=self.tournament
                ).order_by("melee_final_rank").values_list(
                    "melee_final_rank", flat=True
                )
            ), [1, 2, 3, 4]
        )
        medal_types = [
            PlayerTournamentAchievement.MEDAL_GOLD,
            PlayerTournamentAchievement.MEDAL_SILVER,
            PlayerTournamentAchievement.MEDAL_BRONZE,
        ]
        for player, award_type in zip(self.players, medal_types):
            self.assertTrue(
                PlayerTournamentAchievement.objects.filter(
                    player=player,
                    tournament=self.tournament,
                    award_type=award_type,
                ).exists()
            )

        # An unrelated future Friendly Game may change global rating arbitrarily.
        profile = self.players[3].profile
        profile.value = 999
        profile.rating_history = list(profile.rating_history) + [
            {"match_id": 999999, "change": 903}
        ]
        profile.save(update_fields=["value", "rating_history"])

        leaderboard = self.client.get(
            reverse("melee_leaderboard", args=[self.tournament.pk])
        )
        self.assertEqual(leaderboard.status_code, 200)
        self.assertTrue(leaderboard.context["is_frozen"])
        rows = leaderboard.context["leaderboard_data"]
        self.assertEqual([row["player"].pk for row in rows], [p.pk for p in self.players])
        self.assertEqual([row["rating_change"] for row in rows], [5, 4, -3, -4])
        self.assertEqual([row["current_rating"] for row in rows], [105, 104, 97, 96])

        profile_page = self.client.get(
            reverse("player_profile", kwargs={"player_id": self.players[0].pk})
        )
        self.assertEqual(profile_page.status_code, 200)
        self.assertContains(profile_page, "🥇")
        self.assertContains(profile_page, "Gold medal")

        repeat = record_finalized_tournament_history(
            self.tournament, include_melee_awards=True
        )
        self.assertEqual(repeat["medals_created"], 0)
        self.assertEqual(
            PlayerTournamentAchievement.objects.filter(
                tournament=self.tournament, award_type__startswith="medal_"
            ).count(), 3,
        )
