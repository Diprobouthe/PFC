import json

from django.test import TestCase
from django.urls import reverse

from friendly_games.models import (
    FriendlyGame,
    FriendlyGamePlayer,
    FriendlyGameStatistics,
    PlayerCodename,
)
from matches.models import LiveScoreboard
from teams.models import Player, PlayerProfile, Team


class FriendlyLegacyJoinAffiliationTests(TestCase):
    """Regression coverage for the legacy join route's player identity boundary."""

    def setUp(self):
        self.home_team = Team.objects.create(name="Legacy Join Home Team")
        self.other_team = Team.objects.create(name="Legacy Join Other Team")
        self.holding_team = Team.objects.create(name="Friendly Games")

        self.creator = self._player("Creator", self.home_team, "LGC001", captain=True)
        self.same_team_opponent = self._player(
            "Same Team Opponent", self.home_team, "LGC002"
        )
        self.other_team_player = self._player(
            "Other Team Player", self.other_team, "LGC003"
        )
        self.holding_player = self._player(
            "Holding Team Player", self.holding_team, "LGC004"
        )
        self.qr_player = self._player("QR Player", self.other_team, "LGC005")
        self.setup_one = self._player("Setup One", self.home_team, "LGC006")
        self.setup_two = self._player("Setup Two", self.other_team, "LGC007")
        self.same_named_existing_player = self._player(
            "Existing Name Only", self.other_team, "LGC008"
        )

    def _player(self, name, team, codename, captain=False):
        player = Player.objects.create(name=name, team=team, is_captain=captain)
        PlayerCodename.objects.create(player=player, codename=codename)
        PlayerProfile.objects.create(player=player, value=100.0)
        return player

    def _login_as(self, player):
        codename = player.codename_profile.codename
        session = self.client.session
        session["player_codename"] = codename
        session["session_active"] = True
        session.save()

    def _join(self, game, player, side, *, qr=False):
        if qr:
            session = self.client.session
            session["qr_resolved_codename"] = player.codename_profile.codename
            session.save()
            codename = ""
        else:
            codename = player.codename_profile.codename
        return self.client.post(
            reverse("friendly_games:join_game"),
            {
                "match_number": game.match_number,
                "team": side,
                "position": "MILIEU",
                "player_name": player.name,
                "codename": codename,
            },
        )

    def _game_with_creator(self, name):
        game = FriendlyGame.objects.create(name=name, creator_player=self.creator)
        FriendlyGamePlayer.objects.create(
            game=game,
            player=self.creator,
            team="BLACK",
            position="MILIEU",
            provided_codename=self.creator.codename_profile.codename,
            codename_verified=True,
        )
        return game

    def _team_ids(self, *players):
        return {player.pk: Player.objects.get(pk=player.pk).team_id for player in players}

    def test_existing_players_join_and_complete_without_affiliation_changes(self):
        """Codename joins retain affiliations across the full Friendly lifecycle."""
        game = self._game_with_creator("Legacy join affiliation lifecycle")
        participants = (
            self.creator,
            self.same_team_opponent,
            self.other_team_player,
            self.holding_player,
        )
        expected_team_ids = self._team_ids(*participants)
        original_captain = self.creator.is_captain

        # Players from one real Team may oppose each other. Players from another
        # real Team and the existing holding Team may join the same Friendly.
        for player, side in (
            (self.same_team_opponent, "WHITE"),
            (self.other_team_player, "BLACK"),
            (self.holding_player, "WHITE"),
        ):
            response = self._join(game, player, side)
            self.assertEqual(response.status_code, 302)

        self.assertEqual(
            set(
                FriendlyGamePlayer.objects.filter(game=game).values_list(
                    "player_id", "team"
                )
            ),
            {
                (self.creator.pk, "BLACK"),
                (self.other_team_player.pk, "BLACK"),
                (self.same_team_opponent.pk, "WHITE"),
                (self.holding_player.pk, "WHITE"),
            },
        )
        self.assertEqual(self._team_ids(*participants), expected_team_ids)
        self.creator.refresh_from_db()
        self.assertEqual(self.creator.is_captain, original_captain)

        # Replaying a legacy join retains the existing duplicate protection and
        # cannot create another participation or mutate the existing Player.
        duplicate_response = self._join(game, self.other_team_player, "BLACK")
        self.assertEqual(duplicate_response.status_code, 302)
        self.assertEqual(
            FriendlyGamePlayer.objects.filter(
                game=game, player=self.other_team_player
            ).count(),
            1,
        )
        self.assertEqual(self._team_ids(*participants), expected_team_ids)

        self._login_as(self.creator)
        start_response = self.client.get(
            reverse("friendly_games:start_match", args=[game.pk])
        )
        self.assertEqual(start_response.status_code, 302)
        game.refresh_from_db()
        self.assertEqual(game.status, "ACTIVE")
        self.assertEqual(self._team_ids(*participants), expected_team_ids)

        scoreboard = LiveScoreboard.objects.get(friendly_game=game)
        self._login_as(self.holding_player)
        router_response = self.client.post(reverse("pfc_next_url"))
        self.assertEqual(router_response.status_code, 200)
        self.assertEqual(
            router_response.json()["next_url"],
            reverse("scoreboard_detail", args=[scoreboard.pk]),
        )

        live_score_response = self.client.post(
            reverse("update_scoreboard", args=[scoreboard.pk]),
            data=json.dumps(
                {
                    "team1_score": 0,
                    "team2_score": 2,
                    "codename": self.holding_player.codename_profile.codename,
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(live_score_response.status_code, 200)
        self.assertTrue(live_score_response.json()["success"])

        score_response = self.client.post(
            reverse("friendly_games:submit_score", args=[game.pk]),
            {
                "black_score": "13",
                "white_score": "8",
                "submitting_team": "BLACK",
                "submitter_codename": self.creator.codename_profile.codename,
            },
        )
        self.assertEqual(score_response.status_code, 302)
        game.refresh_from_db()
        self.assertEqual(game.status, "PENDING_VALIDATION")

        self._login_as(self.same_team_opponent)
        validation_response = self.client.post(
            reverse("friendly_games:validate_result", args=[game.pk]),
            {"validation_action": "agree"},
        )
        self.assertEqual(validation_response.status_code, 302)
        game.refresh_from_db()
        self.assertEqual(game.status, "COMPLETED")
        self.assertEqual(self._team_ids(*participants), expected_team_ids)
        self.creator.refresh_from_db()
        self.assertEqual(self.creator.is_captain, original_captain)

        for player in participants:
            statistics = FriendlyGameStatistics.objects.get(player=player)
            self.assertEqual(statistics.total_games, 1)

    def test_qr_join_and_creator_setup_modes_preserve_existing_affiliations(self):
        """QR-based legacy join and all creator setup modes remain game-scoped."""
        qr_game = self._game_with_creator("QR legacy join")
        expected_qr_team_id = self.qr_player.team_id

        qr_response = self._join(qr_game, self.qr_player, "WHITE", qr=True)
        self.assertEqual(qr_response.status_code, 302)
        self.qr_player.refresh_from_db()
        self.assertEqual(self.qr_player.team_id, expected_qr_team_id)
        self.assertTrue(
            FriendlyGamePlayer.objects.filter(
                game=qr_game, player=self.qr_player, team="WHITE"
            ).exists()
        )

        expected_setup_team_ids = self._team_ids(self.creator, self.setup_one, self.setup_two)
        for mode in ("manual", "random", "balanced"):
            game = self._game_with_creator(f"Creator {mode} setup")
            self._login_as(self.creator)
            session = self.client.session
            session["friendly_qr_scanned_player_ids"] = [
                self.setup_one.pk,
                self.setup_two.pk,
            ]
            session.save()
            if mode == "manual":
                payload = {
                    "mode": mode,
                    "assignments": [
                        {"id": self.setup_one.pk, "team": "WHITE"},
                        {"id": self.setup_two.pk, "team": "BLACK"},
                    ],
                }
            else:
                payload = {
                    "mode": mode,
                    "player_ids": [self.setup_one.pk, self.setup_two.pk],
                }
            response = self.client.post(
                reverse("friendly_games:creator_assign_players", args=[game.pk]),
                data=json.dumps(payload),
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 200, mode)
            self.assertTrue(response.json()["ok"], mode)
            self.assertEqual(
                FriendlyGamePlayer.objects.filter(
                    game=game,
                    player_id__in=[self.setup_one.pk, self.setup_two.pk],
                ).count(),
                2,
                mode,
            )
            self.assertEqual(
                self._team_ids(self.creator, self.setup_one, self.setup_two),
                expected_setup_team_ids,
                mode,
            )

    def test_name_only_join_does_not_claim_an_existing_player(self):
        """A name without codename/QR proof cannot attach a real existing Player."""
        game = self._game_with_creator("Name-only guest join")
        existing_team_id = self.same_named_existing_player.team_id

        response = self.client.post(
            reverse("friendly_games:join_game"),
            {
                "match_number": game.match_number,
                "team": "WHITE",
                "position": "MILIEU",
                "player_name": self.same_named_existing_player.name,
                "codename": "",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.same_named_existing_player.refresh_from_db()
        self.assertEqual(self.same_named_existing_player.team_id, existing_team_id)
        participation = FriendlyGamePlayer.objects.get(game=game, team="WHITE")
        self.assertNotEqual(participation.player_id, self.same_named_existing_player.pk)
        self.assertEqual(participation.player.team_id, self.holding_team.pk)
