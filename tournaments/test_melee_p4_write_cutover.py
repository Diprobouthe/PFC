from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from courts.models import Court
from friendly_games.models import PlayerCodename
from matches.melee_roster_resolution import players_for_match_team
from matches.models import Match, MatchActivation, MatchPlayer
from matches.rating_integration import get_players_with_profiles
from teams.models import Player, PlayerProfile, Team
from tournaments.admin_melee_swap import perform_melee_swap
from tournaments.melee_lifecycle import (
    delete_unreferenced_temporary_teams,
    restore_legacy_transferred_melee_players,
)
from tournaments.models import (
    MeleePlayer,
    MeleeRoundAssignment,
    Round,
    Stage,
    Tournament,
)
from tournaments.partnership_models import MeleePartnership, MeleeShuffleHistory
from tournaments.registration_services import register_melee_player_for_tournament
from tournaments.shuffle_utils import shuffle_melee_players


class MeleeP4WriteCutoverTests(TestCase):
    """End-to-end P4 coverage for affiliation-preserving Mêlée write paths."""

    def setUp(self):
        now = timezone.now()
        self.tournament = Tournament.objects.create(
            name="P4 Super Mêlée End-to-End",
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
        court = Court.objects.create(number=98101, is_available=True)
        self.tournament.courts.add(court)
        self.home_teams = [
            Team.objects.create(name=f"P4 Home Team {number}")
            for number in range(1, 5)
        ]
        self.players = []
        for number, home_team in enumerate(self.home_teams, start=1):
            player = Player.objects.create(
                name=f"P4 Player {number}",
                team=home_team,
                is_captain=(number == 1),
            )
            PlayerProfile.objects.create(player=player, value=100.0 + number)
            PlayerCodename.objects.create(player=player, codename=f"P4X{number:03d}")
            register_melee_player_for_tournament(
                tournament=self.tournament,
                player=player,
            )
            self.players.append(player)
        self.home_team_ids = {player.id: player.team_id for player in self.players}

    def _set_player_session(self, player):
        session = self.client.session
        session["player_codename"] = PlayerCodename.objects.get(player=player).codename
        session["session_active"] = True
        session["player_id"] = player.id
        session["team_id"] = player.team_id
        session["team_name"] = player.team.name
        session["team_pin"] = player.team.pin
        session.save()

    def _assert_home_affiliations_unchanged(self):
        for player in self.players:
            player.refresh_from_db()
            self.assertEqual(player.team_id, self.home_team_ids[player.id])

    def _assignment_players(self, round_obj, team):
        return list(
            MeleeRoundAssignment.objects.filter(
                tournament=self.tournament,
                round=round_obj,
                team=team,
                state=MeleeRoundAssignment.ASSIGNED,
            ).order_by("player_id").values_list("player_id", flat=True)
        )

    def _activate_both_sides_by_qr(self, match):
        team_one_players = list(players_for_match_team(match, match.team1))
        team_two_players = list(players_for_match_team(match, match.team2))
        self.assertEqual(len(team_one_players), 2)
        self.assertEqual(len(team_two_players), 2)
        self._set_player_session(team_one_players[0])
        session = self.client.session
        session["qr_resolved_codename"] = PlayerCodename.objects.get(
            player=team_two_players[0]
        ).codename
        session.save()
        response = self.client.post(
            reverse(
                "match_activate",
                kwargs={"match_id": match.id, "team_id": match.team1_id},
            ),
            {
                "pin": match.team1.pin,
                "players": [player.id for player in team_one_players],
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(MatchActivation.objects.filter(match=match, team=match.team1).exists())
        self.assertTrue(MatchActivation.objects.filter(match=match, team=match.team2).exists())
        self.assertEqual(
            set(
                MatchPlayer.objects.filter(match=match, team=match.team1)
                .values_list("player_id", flat=True)
            ),
            {player.id for player in team_one_players},
        )
        self.assertEqual(
            set(
                MatchPlayer.objects.filter(match=match, team=match.team2)
                .values_list("player_id", flat=True)
            ),
            {player.id for player in team_two_players},
        )

    def test_end_to_end_assignment_based_lifecycle_keeps_home_team(self):
        """Registration → Round 1 activation → shuffle → Round 2 → completion."""
        # This P4 lifecycle fixture deliberately completes the first Match
        # without a score/winner. Random keeps the test focused on affiliation
        # preservation; Snake Draft now correctly requires actual winner/loser
        # data for later Super Mêlée transitions.
        teams_created = self.tournament.generate_melee_teams("random")
        self.assertEqual(teams_created, 2)
        self.tournament.refresh_from_db()
        self.assertEqual(
            self.tournament.melee_roster_mode,
            Tournament.MELEE_ROSTER_MODE_ASSIGNMENT,
        )
        self._assert_home_affiliations_unchanged()

        round_one = Round.objects.get(
            tournament=self.tournament,
            stage=self.stage,
            number_in_stage=1,
        )
        self.assertEqual(
            MeleeRoundAssignment.objects.filter(
                tournament=self.tournament,
                round=round_one,
            ).count(),
            4,
        )
        for registration in self.tournament.tournamentteam_set.select_related("team"):
            self.assertTrue(registration.team.is_tournament_temp)
            self.assertEqual(registration.team.players.count(), 0)
        self.assertEqual(
            MeleePartnership.objects.filter(
                tournament=self.tournament,
                round=round_one,
            ).count(),
            2,
        )

        self.assertEqual(self.tournament.generate_matches(), 1)
        round_one_match = Match.objects.get(tournament=self.tournament, round=round_one)
        round_one_roster = {
            assignment.player_id: assignment.team_id
            for assignment in MeleeRoundAssignment.objects.filter(
                tournament=self.tournament,
                round=round_one,
            )
        }
        self._activate_both_sides_by_qr(round_one_match)
        round_one_snapshot = set(
            MatchPlayer.objects.filter(match=round_one_match).values_list(
                "player_id", "team_id"
            )
        )
        self._assert_home_affiliations_unchanged()

        # A completed Round can now shuffle into a concrete Round 2 without
        # changing Player.team. Scores are not material to the reshuffle test.
        Match.objects.filter(pk=round_one_match.pk).update(status="completed")
        with patch("tournaments.shuffle_utils.random.shuffle", side_effect=lambda values: values.reverse()):
            shuffle_result = shuffle_melee_players(
                tournament=self.tournament,
                shuffle_type="automatic",
                completed_round=round_one,
            )
        self.assertTrue(shuffle_result["success"], shuffle_result)
        round_two = Round.objects.get(
            tournament=self.tournament,
            stage=self.stage,
            number_in_stage=2,
        )
        self.assertTrue(
            MeleeShuffleHistory.objects.filter(
                tournament=self.tournament,
                round=round_one,
            ).exists()
        )
        self.assertEqual(
            MeleeRoundAssignment.objects.filter(
                tournament=self.tournament,
                round=round_two,
            ).count(),
            4,
        )
        self.assertEqual(
            round_one_roster,
            dict(
                MeleeRoundAssignment.objects.filter(
                    tournament=self.tournament,
                    round=round_one,
                ).values_list("player_id", "team_id")
            ),
        )
        self.assertEqual(
            round_one_snapshot,
            set(
                MatchPlayer.objects.filter(match=round_one_match).values_list(
                    "player_id", "team_id"
                )
            ),
        )
        self._assert_home_affiliations_unchanged()

        round_two_teams = list(
            self.tournament.tournamentteam_set.select_related("team")
            .filter(team__is_tournament_temp=True)
            .order_by("team_id")
        )
        round_two_match = Match.objects.create(
            tournament=self.tournament,
            stage=self.stage,
            round=round_two,
            team1=round_two_teams[0].team,
            team2=round_two_teams[1].team,
            status="pending",
        )
        self._activate_both_sides_by_qr(round_two_match)
        self.assertEqual(
            set(
                MatchPlayer.objects.filter(match=round_two_match, team=round_two_match.team1)
                .values_list("player_id", flat=True)
            ),
            set(self._assignment_players(round_two, round_two_match.team1)),
        )
        self._assert_home_affiliations_unchanged()

        Match.objects.filter(pk=round_two_match.pk).update(status="completed")
        self.assertTrue(self.tournament.is_tournament_complete())
        self.assertEqual(self.tournament.auto_restore_players_on_completion(), 0)
        self._assert_home_affiliations_unchanged()

    def test_rating_fallback_uses_exact_assignment_not_empty_temp_team_members(self):
        self.tournament.generate_melee_teams("balanced")
        round_one = Round.objects.get(
            tournament=self.tournament,
            stage=self.stage,
            number_in_stage=1,
        )
        team_one, team_two = [
            row.team
            for row in self.tournament.tournamentteam_set.select_related("team")
            .filter(team__is_tournament_temp=True)
            .order_by("team_id")
        ]
        match = Match.objects.create(
            tournament=self.tournament,
            stage=self.stage,
            round=round_one,
            team1=team_one,
            team2=team_two,
        )
        self.assertEqual(team_one.players.count(), 0)
        profiles = get_players_with_profiles(team_one, match)
        self.assertEqual(
            {profile.player_id for profile in profiles},
            set(self._assignment_players(round_one, team_one)),
        )

    def test_assignment_history_prevents_temporary_team_cleanup(self):
        self.tournament.generate_melee_teams("balanced")
        temporary_team_ids = set(
            self.tournament.tournamentteam_set.filter(team__is_tournament_temp=True)
            .values_list("team_id", flat=True)
        )
        deleted, retained = delete_unreferenced_temporary_teams(self.tournament)
        self.assertEqual(deleted, 0)
        self.assertEqual(retained, 2)
        self.assertEqual(
            temporary_team_ids,
            set(
                self.tournament.tournamentteam_set.filter(team__is_tournament_temp=True)
                .values_list("team_id", flat=True)
            ),
        )

    def test_simple_melee_generation_keeps_one_assignment_roster_without_shuffle(self):
        self.tournament.shuffle_players_after_round = False
        self.tournament.save(update_fields=["shuffle_players_after_round"])
        self.tournament.generate_melee_teams("random")
        round_one = Round.objects.get(
            tournament=self.tournament,
            stage=self.stage,
            number_in_stage=1,
        )
        self.assertEqual(
            MeleeRoundAssignment.objects.filter(
                tournament=self.tournament,
                round=round_one,
            ).count(),
            4,
        )
        self.assertFalse(MeleeShuffleHistory.objects.filter(tournament=self.tournament).exists())
        self._assert_home_affiliations_unchanged()

    def test_post_generation_swap_is_rejected_without_affiliation_or_history_change(self):
        self.tournament.generate_melee_teams("balanced")
        incoming_team = Team.objects.create(name="P4 Incoming Home Team")
        incoming = Player.objects.create(name="P4 Incoming", team=incoming_team)
        before_registrations = set(
            MeleePlayer.objects.filter(tournament=self.tournament).values_list("player_id", flat=True)
        )
        result = perform_melee_swap(
            self.tournament,
            self.players[0],
            incoming,
            admin_user=type("Admin", (), {"username": "p4-test"})(),
        )
        self.assertFalse(result["success"])
        self.assertIn("only before Mêlée teams are generated", result["message"])
        self.assertEqual(
            before_registrations,
            set(
                MeleePlayer.objects.filter(tournament=self.tournament)
                .values_list("player_id", flat=True)
            ),
        )
        self._assert_home_affiliations_unchanged()
        incoming.refresh_from_db()
        self.assertEqual(incoming.team_id, incoming_team.id)

    def test_registration_and_pre_generation_removal_preserve_affiliation(self):
        registration = MeleePlayer.objects.get(
            tournament=self.tournament,
            player=self.players[0],
        )
        session = self.client.session
        session["simple_tournament_info"] = {"tournament_id": self.tournament.id}
        session.save()
        response = self.client.post(
            reverse(
                "remove_simple_tournament_player",
                kwargs={
                    "tournament_id": self.tournament.id,
                    "melee_player_id": registration.id,
                },
            )
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(MeleePlayer.objects.filter(pk=registration.pk).exists())
        self._assert_home_affiliations_unchanged()

    def test_legacy_mode_restores_transferred_players_but_p4_mode_does_not(self):
        legacy = Tournament.objects.create(
            name="P4 Legacy Compatibility",
            format="multi_stage",
            play_format="doublets",
            is_melee=True,
            melee_format="doublets",
            melee_roster_mode=Tournament.MELEE_ROSTER_MODE_LEGACY,
            start_date=timezone.now(),
            end_date=timezone.now() + timedelta(hours=4),
        )
        home = Team.objects.create(name="P4 Legacy Home")
        temporary = Team.objects.create(name="P4 Legacy Temporary", is_tournament_temp=True)
        from tournaments.models import TournamentTeam
        TournamentTeam.objects.create(tournament=legacy, team=temporary)
        player = Player.objects.create(name="P4 Legacy Player", team=temporary)
        MeleePlayer.objects.create(
            tournament=legacy,
            player=player,
            original_team=home,
            assigned_team=temporary,
        )
        self.assertEqual(restore_legacy_transferred_melee_players(legacy), 1)
        player.refresh_from_db()
        self.assertEqual(player.team_id, home.id)

        self.tournament.generate_melee_teams("balanced")
        self.assertEqual(restore_legacy_transferred_melee_players(self.tournament), 0)
        self._assert_home_affiliations_unchanged()

    def test_legacy_super_melee_shuffle_retains_recovery_path(self):
        legacy = Tournament.objects.create(
            name="P4 Legacy Super Mêlée Shuffle",
            format="round_robin",
            play_format="doublets",
            is_melee=True,
            melee_format="doublets",
            shuffle_players_after_round=True,
            melee_teams_generated=True,
            melee_roster_mode=Tournament.MELEE_ROSTER_MODE_LEGACY,
            current_round_number=1,
            start_date=timezone.now(),
            end_date=timezone.now() + timedelta(hours=4),
        )
        from tournaments.models import TournamentTeam
        temporary_teams = [
            Team.objects.create(name=f"P4 Legacy Shuffle Team {number}", is_tournament_temp=True)
            for number in range(1, 3)
        ]
        for temporary in temporary_teams:
            TournamentTeam.objects.create(tournament=legacy, team=temporary)
        legacy_players = []
        home_by_player_id = {}
        for number in range(4):
            home = Team.objects.create(name=f"P4 Legacy Shuffle Home {number}")
            player = Player.objects.create(
                name=f"P4 Legacy Shuffle Player {number}",
                team=temporary_teams[number % 2],
            )
            MeleePlayer.objects.create(
                tournament=legacy,
                player=player,
                original_team=home,
                assigned_team=temporary_teams[number % 2],
            )
            legacy_players.append(player)
            home_by_player_id[player.id] = home.id
        round_one = Round.objects.create(
            tournament=legacy,
            number=1,
            number_in_stage=1,
            name="Round 1",
        )

        result = shuffle_melee_players(
            tournament=legacy,
            shuffle_type="automatic",
            completed_round=round_one,
        )
        self.assertTrue(result["success"], result)
        self.assertTrue(
            MeleeShuffleHistory.objects.filter(
                tournament=legacy,
                round=round_one,
            ).exists()
        )
        for player in legacy_players:
            player.refresh_from_db()
            self.assertIn(player.team_id, {team.id for team in temporary_teams})
        self.assertEqual(restore_legacy_transferred_melee_players(legacy), 4)
        for player in legacy_players:
            player.refresh_from_db()
            self.assertEqual(player.team_id, home_by_player_id[player.id])
