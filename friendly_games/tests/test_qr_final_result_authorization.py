from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from friendly_games.models import (
    FriendlyGame,
    FriendlyGamePlayer,
    FriendlyGameResult,
    PlayerCodename,
)
from matches.models import LiveScoreboard
from teams.models import Player, Team


class FriendlyQrFinalResultAuthorizationTests(TestCase):
    def setUp(self):
        self.scanner_team = Team.objects.create(name="QR Scanner Team")
        self.black_affiliation = Team.objects.create(name="QR Black Affiliation")
        self.white_affiliation = Team.objects.create(name="QR White Affiliation")

        self.scanner = Player.objects.create(name="NPC18 Scanner", team=self.scanner_team)
        self.black_player = Player.objects.create(name="NPC PFC6", team=self.black_affiliation)
        self.white_player = Player.objects.create(name="NPC PFC8", team=self.white_affiliation)

        PlayerCodename.objects.create(player=self.scanner, codename="SCAN18")
        PlayerCodename.objects.create(player=self.black_player, codename="BLACK1")
        PlayerCodename.objects.create(player=self.white_player, codename="WHITE1")

        self.game = FriendlyGame.objects.create(
            name="QR final result test",
            match_number="9193",
            status="ACTIVE",
            creator_player=self.scanner,
        )
        FriendlyGamePlayer.objects.create(
            game=self.game,
            player=self.black_player,
            team="BLACK",
            position="MILIEU",
            provided_codename="QR",
            codename_verified=True,
        )
        FriendlyGamePlayer.objects.create(
            game=self.game,
            player=self.white_player,
            team="WHITE",
            position="MILIEU",
            provided_codename="QR",
            codename_verified=True,
        )
        self.scoreboard, _ = LiveScoreboard.objects.get_or_create(
            friendly_game=self.game,
        )

        self._login_as(self.scanner)

    def _login_as(self, player):
        session = self.client.session
        session["player_codename"] = player.codename_profile.codename
        session["session_active"] = True
        session.save()

    def _scan_for_smart_action(self, player):
        session = self.client.session
        session["qr_resolved_codename"] = player.codename_profile.codename
        session.save()
        response = self.client.post(reverse("pfc_qr_next_action"))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        return payload["next_url"]

    @staticmethod
    def _token_from_url(url):
        return parse_qs(urlparse(url).query)["qr_action"][0]

    @patch("pfc_events.push_notifications.notify_match_action_required")
    def test_scanned_participant_survives_scoreboard_to_final_result_handoff(self, _notify):
        # The phone holder is deliberately NOT a participant. The scanned card
        # belongs to the Black-side participant, matching the production failure.
        scoreboard_url = self._scan_for_smart_action(self.black_player)
        parsed = urlparse(scoreboard_url)
        self.assertEqual(
            parsed.path,
            reverse("scoreboard_detail", args=[self.scoreboard.pk]),
        )
        self.assertTrue(self._token_from_url(scoreboard_url))

        scoreboard_page = self.client.get(scoreboard_url)
        self.assertEqual(scoreboard_page.status_code, 200)
        child_token = scoreboard_page.context["qr_submit_action_token"]
        self.assertTrue(child_token)

        submit_url = reverse("friendly_games:submit_score", args=[self.game.pk])
        final_page = self.client.get(f"{submit_url}?qr_action={child_token}")
        self.assertEqual(final_page.status_code, 200)
        self.assertEqual(final_page.context["auto_team"], "BLACK")
        self.assertEqual(
            final_page.context["submitter_player_name"],
            self.black_player.name,
        )

        # Internal codenames must not be rendered on the final-result page.
        self.assertNotContains(final_page, self.scanner.codename_profile.codename)
        self.assertNotContains(final_page, self.black_player.codename_profile.codename)
        self.assertContains(final_page, self.black_player.name)

        result_response = self.client.post(
            submit_url,
            {
                "black_score": "13",
                "white_score": "8",
                "qr_action": child_token,
                # Deliberately forged legacy fields: the server must ignore both.
                "submitter_codename": self.scanner.codename_profile.codename,
                "submitting_team": "WHITE",
            },
        )
        self.assertEqual(result_response.status_code, 302)

        result = FriendlyGameResult.objects.get(game=self.game)
        self.assertEqual(result.submitter_codename, self.black_player.codename_profile.codename)
        self.assertEqual(result.submitted_by_team, "BLACK")
        self.game.refresh_from_db()
        self.assertEqual(self.game.status, "PENDING_VALIDATION")

    @patch("pfc_events.push_notifications.notify_match_action_required")
    def test_normal_logged_in_participant_identity_is_server_side(self, _notify):
        self._login_as(self.black_player)
        response = self.client.post(
            reverse("friendly_games:submit_score", args=[self.game.pk]),
            {
                "black_score": "13",
                "white_score": "7",
                # These browser values must never choose the actor or side.
                "submitter_codename": self.white_player.codename_profile.codename,
                "submitting_team": "WHITE",
            },
        )
        self.assertEqual(response.status_code, 302)

        result = FriendlyGameResult.objects.get(game=self.game)
        self.assertEqual(result.submitter_codename, self.black_player.codename_profile.codename)
        self.assertEqual(result.submitted_by_team, "BLACK")

    def test_nonparticipant_cannot_forge_participant_codename(self):
        response = self.client.post(
            reverse("friendly_games:submit_score", args=[self.game.pk]),
            {
                "black_score": "13",
                "white_score": "6",
                "submitter_codename": self.black_player.codename_profile.codename,
                "submitting_team": "BLACK",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(FriendlyGameResult.objects.filter(game=self.game).exists())
        self.game.refresh_from_db()
        self.assertEqual(self.game.status, "ACTIVE")

    def test_submit_page_shows_player_name_not_internal_codename(self):
        self._login_as(self.black_player)
        page = self.client.get(
            reverse("friendly_games:submit_score", args=[self.game.pk])
        )
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.context["submitter_player_name"], self.black_player.name)
        self.assertEqual(page.context["auto_team"], "BLACK")
        self.assertContains(page, self.black_player.name)
        self.assertNotContains(page, self.black_player.codename_profile.codename)
