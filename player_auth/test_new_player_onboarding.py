import json
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from friendly_games.models import PlayerCodename
from player_auth.models import EmailOTP, PFCUser
from teams.models import PlayerProfile


class NewPlayerOnboardingTests(TestCase):
    def _verify_email(self, email):
        otp = EmailOTP.create_for_email(email)
        session = self.client.session
        session["pauth_pending_email"] = email
        session.save()
        return self.client.post(
            reverse("player_auth:email_verify"),
            {"code": otp.code},
        )

    def test_brand_new_email_account_skips_legacy_link_screen(self):
        response = self._verify_email("brand-new@example.com")

        self.assertRedirects(response, "/", fetch_redirect_response=False)
        user = PFCUser.objects.get(email="brand-new@example.com")
        self.assertIsNotNone(user.player_id)
        self.assertTrue(user.legacy_link_skipped)
        self.assertFalse(user.legacy_codename_linked)

        self.assertTrue(
            PlayerProfile.objects.filter(
                player_id=user.player_id,
                is_active=True,
            ).exists()
        )
        codename = PlayerCodename.objects.get(player_id=user.player_id).codename
        session = self.client.session
        self.assertTrue(session.get("session_active"))
        self.assertEqual(session.get("player_codename"), codename)
        self.assertNotIn("pauth_user_id", session)

    def test_brand_new_google_account_skips_legacy_link_screen(self):
        class FakeResponse:
            def __init__(self, payload):
                self.payload = payload

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return json.dumps(self.payload).encode()

        session = self.client.session
        session["pauth_oauth_state"] = "expected-state"
        session.save()

        responses = [
            FakeResponse({"access_token": "test-token"}),
            FakeResponse({
                "email": "brand-new-google@example.com",
                "sub": "google-sub-new-player",
                "name": "Brand New Google Player",
                "picture": "",
            }),
        ]
        with patch("player_auth.views.urllib.request.urlopen", side_effect=responses):
            response = self.client.get(
                reverse("player_auth:google_callback"),
                {"state": "expected-state", "code": "test-code"},
            )

        self.assertRedirects(response, "/", fetch_redirect_response=False)
        user = PFCUser.objects.get(email="brand-new-google@example.com")
        self.assertIsNotNone(user.player_id)
        self.assertEqual(user.player.name, "Brand New Google Player")
        self.assertTrue(user.legacy_link_skipped)
        self.assertFalse(user.legacy_codename_linked)
        self.assertTrue(self.client.session.get("session_active"))

    def test_existing_unlinked_account_keeps_legacy_link_fallback(self):
        user = PFCUser.objects.create(
            email="old-unlinked@example.com",
            provider=PFCUser.PROVIDER_EMAIL,
        )

        response = self._verify_email(user.email)

        self.assertRedirects(
            response,
            reverse("player_auth:link"),
            fetch_redirect_response=False,
        )
        user.refresh_from_db()
        self.assertIsNone(user.player_id)
        self.assertFalse(user.legacy_link_skipped)
        self.assertFalse(user.legacy_codename_linked)

        session = self.client.session
        self.assertEqual(session.get("pauth_user_id"), user.id)
        self.assertFalse(session.get("session_active", False))

    def test_existing_linked_account_login_behavior_is_unchanged(self):
        user = PFCUser.objects.create(
            email="linked@example.com",
            provider=PFCUser.PROVIDER_EMAIL,
            display_name="Linked Player",
        )
        player = user.create_and_link_player()
        codename = PlayerCodename.objects.get(player=player).codename

        response = self._verify_email(user.email)

        self.assertRedirects(response, "/", fetch_redirect_response=False)
        user.refresh_from_db()
        self.assertEqual(user.player_id, player.id)
        session = self.client.session
        self.assertTrue(session.get("session_active"))
        self.assertEqual(session.get("player_codename"), codename)

    def test_new_account_creation_is_idempotent_at_login_boundary(self):
        user = PFCUser.objects.create(
            email="already-created@example.com",
            provider=PFCUser.PROVIDER_EMAIL,
        )
        first_player = user.create_and_link_player()

        response = self._verify_email(user.email)

        self.assertRedirects(response, "/", fetch_redirect_response=False)
        user.refresh_from_db()
        self.assertEqual(user.player_id, first_player.id)
        self.assertEqual(
            PlayerCodename.objects.filter(player_id=first_player.id).count(),
            1,
        )
