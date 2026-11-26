import json
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from django.test import TestCase, override_settings
from django.urls import reverse

from player_auth.models import PFCUser


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.payload).encode()


@override_settings(GOOGLE_OAUTH_CLIENT_ID="test-client",
                   GOOGLE_OAUTH_CLIENT_SECRET="test-secret",
                   GOOGLE_OAUTH_REDIRECT_URI="https://www.pfc.events/player-auth/google/callback/")
class GoogleOAuthSecurityTests(TestCase):
    def begin(self):
        response = self.client.get(reverse("player_auth:google_login"))
        query = parse_qs(urlparse(response.url).query)
        self.assertEqual(query["code_challenge_method"], ["S256"])
        self.assertNotIn("access_type", query)
        self.assertEqual(query["redirect_uri"], ["https://www.pfc.events/player-auth/google/callback/"])
        return query["state"][0]

    def callback(self, state, **profile):
        data = {"email": "player@gmail.com", "sub": "subject-1",
                "email_verified": True, "name": "Google Name"}
        data.update(profile)
        with patch("player_auth.views.urllib.request.urlopen", side_effect=[
            FakeResponse({"access_token": "token"}), FakeResponse(data)
        ]) as network:
            response = self.client.get(reverse("player_auth:google_callback"),
                                       {"state": state, "code": "code"})
        return response, network

    def test_missing_state_rejected_without_network(self):
        with patch("player_auth.views.urllib.request.urlopen") as network:
            response = self.client.get(reverse("player_auth:google_callback"), {"code": "code"})
        self.assertRedirects(response, reverse("player_auth:login"), fetch_redirect_response=False)
        network.assert_not_called()

    def test_wrong_state_is_consumed(self):
        state = self.begin()
        for value in ("wrong", state):
            response, network = self.callback(value)
            self.assertRedirects(response, reverse("player_auth:login"), fetch_redirect_response=False)
            network.assert_not_called()

    def test_expired_state_rejected(self):
        state = self.begin()
        session = self.client.session
        session["pauth_oauth_started"] = 0
        session.save()
        response, network = self.callback(state)
        self.assertEqual(network.call_count, 0)
        self.assertRedirects(response, reverse("player_auth:login"), fetch_redirect_response=False)

    def test_unverified_or_missing_subject_rejected(self):
        for profile in ({"email_verified": False}, {"email_verified": "true"}, {"sub": ""}):
            response, _ = self.callback(self.begin(), **profile)
            self.assertRedirects(response, reverse("player_auth:login"), fetch_redirect_response=False)
        self.assertFalse(PFCUser.objects.exists())

    def test_success_and_replay(self):
        state = self.begin()
        verifier = self.client.session["pauth_oauth_verifier"]
        response, network = self.callback(state)
        self.assertRedirects(response, "/", fetch_redirect_response=False)
        self.assertEqual(parse_qs(network.call_args_list[0].args[0].data.decode())["code_verifier"], [verifier])
        self.assertTrue(self.client.session["session_active"])
        response, network = self.callback(state)
        network.assert_not_called()
        self.assertEqual(PFCUser.objects.count(), 1)

    def test_existing_email_account_links_without_replacing_player_name(self):
        user = PFCUser.objects.create(email="player@gmail.com", provider="email")
        player = user.create_and_link_player(name="Chosen Name")
        response, _ = self.callback(self.begin())
        self.assertRedirects(response, "/", fetch_redirect_response=False)
        user.refresh_from_db()
        player.refresh_from_db()
        self.assertEqual(user.google_sub, "subject-1")
        self.assertEqual(user.player_id, player.pk)
        self.assertEqual(player.name, "Chosen Name")

    def test_different_subject_cannot_take_over_existing_account(self):
        user = PFCUser.objects.create(email="player@gmail.com", provider="google", google_sub="other-subject")
        response, _ = self.callback(self.begin())
        self.assertRedirects(response, reverse("player_auth:login"), fetch_redirect_response=False)
        user.refresh_from_db()
        self.assertEqual(user.google_sub, "other-subject")
        self.assertFalse(self.client.session.get("session_active"))

    def test_third_party_email_cannot_link_existing_account(self):
        user = PFCUser.objects.create(email="player@example.com", provider="email")
        response, _ = self.callback(self.begin(), email=user.email)
        self.assertRedirects(response, reverse("player_auth:login"), fetch_redirect_response=False)
        user.refresh_from_db()
        self.assertIsNone(user.google_sub)

    def test_inactive_account_cannot_login(self):
        PFCUser.objects.create(email="player@gmail.com", provider="google", google_sub="subject-1", is_active=False)
        response, _ = self.callback(self.begin())
        self.assertRedirects(response, reverse("player_auth:login"), fetch_redirect_response=False)
        self.assertFalse(self.client.session.get("session_active"))

    @override_settings(GOOGLE_OAUTH_CLIENT_SECRET="")
    def test_incomplete_configuration_disables_login(self):
        response = self.client.get(reverse("player_auth:google_login"))
        self.assertRedirects(response, reverse("player_auth:login"), fetch_redirect_response=False)
