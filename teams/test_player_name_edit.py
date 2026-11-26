from django.test import TestCase
from django.urls import reverse

from friendly_games.models import PlayerCodename
from player_auth.models import PFCUser
from teams.models import Player, PlayerProfile, Team


class PlayerNameEditTests(TestCase):
    def setUp(self):
        team = Team.objects.create(name="Name Edit Test Team")
        self.player = Player.objects.create(name="email-prefix", team=team)
        self.other = Player.objects.create(name="Other Player", team=team)
        self.profile = PlayerProfile.objects.create(
            player=self.player, email="profile@example.com", value=145.0
        )
        self.account = PFCUser.objects.create(
            email="login@example.com", provider=PFCUser.PROVIDER_EMAIL,
            player=self.player,
        )
        self.code = PlayerCodename.objects.create(
            player=self.player, codename="NAM001"
        )
        self.url = reverse("edit_player_profile")

    def sign_in(self, active=True):
        session = self.client.session
        session["player_codename"] = self.code.codename
        session["session_active"] = active
        session["pauth_user_id"] = self.account.pk
        session.save()

    def test_edit_page_shows_current_name(self):
        self.sign_in()
        response = self.client.get(self.url)
        self.assertContains(response, 'id="ep-player-name-input"')
        self.assertContains(response, 'value="email-prefix"')

    def test_updates_only_own_name_and_preserves_identity(self):
        self.sign_in()
        response = self.client.post(self.url, {
            "action": "update_name", "name": "  Μαρία Παπαδοπούλου  ",
            "player_id": self.other.pk, "email": "changed@example.com",
            "codename": "NEW999",
        })
        self.assertRedirects(response, self.url, fetch_redirect_response=False)
        self.player.refresh_from_db()
        self.other.refresh_from_db()
        self.account.refresh_from_db()
        self.profile.refresh_from_db()
        self.code.refresh_from_db()
        self.assertEqual(self.player.name, "Μαρία Παπαδοπούλου")
        self.assertEqual(self.other.name, "Other Player")
        self.assertEqual(self.account.email, "login@example.com")
        self.assertEqual(self.account.player_id, self.player.pk)
        self.assertEqual(self.profile.email, "profile@example.com")
        self.assertEqual(self.profile.value, 145.0)
        self.assertEqual(self.code.codename, "NAM001")

    def test_invalid_names_do_not_change_player(self):
        self.sign_in()
        for name in ("", "   ", "a" * 101, "bad\x00name"):
            with self.subTest(name=name):
                self.client.post(self.url, {"action": "update_name", "name": name})
                self.player.refresh_from_db()
                self.assertEqual(self.player.name, "email-prefix")

    def test_logged_out_cannot_change_name(self):
        self.client.post(self.url, {
            "action": "update_name", "name": "Unauthorized",
            "player_id": self.player.pk,
        })
        self.player.refresh_from_db()
        self.assertEqual(self.player.name, "email-prefix")

    def test_inactive_session_cannot_change_name(self):
        self.sign_in(active=False)
        self.client.post(self.url, {
            "action": "update_name", "name": "Unauthorized",
        })
        self.player.refresh_from_db()
        self.assertEqual(self.player.name, "email-prefix")
