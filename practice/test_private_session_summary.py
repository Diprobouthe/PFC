"""Practice summaries are private even with public aggregate opt-in.

The existing QR delegation flow retains its authorized single-session view
while active and for a narrowly scoped 15-minute window after completion.
"""
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from friendly_games.models import PlayerCodename
from practice.models import PracticeSession, Shot
from practice.views import (
    PRACTICE_DELEGATION_KEY,
    PRACTICE_SUMMARY_GRANT_KEY,
    PRACTICE_SUMMARY_GRANT_SECONDS,
)
from teams.models import Player, PlayerProfile, Team


class PracticePrivateSessionSummaryTests(TestCase):
    def setUp(self):
        team = Team.objects.create(name="Summary authorization tests", pin="779922")
        player = Player.objects.create(name="Summary privacy owner", team=team)
        profile, _ = PlayerProfile.objects.get_or_create(player=player)
        profile.share_practice_statistics = True
        profile.save(update_fields=["share_practice_statistics"])
        PlayerCodename.objects.create(player=player, codename="TARGET")
        self.session = PracticeSession.objects.create(
            player_codename="TARGET", practice_type="shooting", is_active=True,
        )
        Shot.objects.create(session=self.session, outcome="hit")
        self.url = reverse("practice:session_summary", args=[self.session.pk])

    def _login(self, code):
        s = self.client.session
        s["player_codename"] = code
        s["session_active"] = True
        s.save()

    def test_public_consent_never_makes_raw_session_public(self):
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_unrelated_logged_in_player_cannot_open_session(self):
        self._login("OTHER1")
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_owner_can_still_see_complete_session(self):
        self._login("TARGET")
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_qr_delegate_can_see_only_granted_active_session(self):
        grant = {
            "session_id": str(self.session.pk),
            "codename": "TARGET",
            "practice_type": "shooting",
        }
        s = self.client.session
        s[PRACTICE_DELEGATION_KEY] = grant
        s.save()
        self.assertEqual(self.client.get(self.url).status_code, 200)
        different = PracticeSession.objects.create(
            player_codename="TARGET", practice_type="shooting", is_active=True,
        )
        self.assertEqual(
            self.client.get(reverse("practice:session_summary", args=[different.pk])).status_code,
            403,
        )

    def test_qr_delegate_keeps_short_lived_summary_after_ending(self):
        s = self.client.session
        s[PRACTICE_DELEGATION_KEY] = {
            "session_id": str(self.session.pk),
            "codename": "TARGET",
            "practice_type": "shooting",
        }
        s.save()
        result = self.client.post(reverse("practice:end_session"))
        self.assertEqual(result.status_code, 200)
        self.assertTrue(result.json()["success"])
        s = self.client.session
        self.assertNotIn(PRACTICE_DELEGATION_KEY, s)
        self.assertIn(PRACTICE_SUMMARY_GRANT_KEY, s)
        self.assertEqual(self.client.get(self.url).status_code, 200)

        grant = s[PRACTICE_SUMMARY_GRANT_KEY]
        grant["issued_at"] = int(timezone.now().timestamp()) - PRACTICE_SUMMARY_GRANT_SECONDS - 1
        s[PRACTICE_SUMMARY_GRANT_KEY] = grant
        s.save()
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_wrong_or_unbound_qr_grant_is_denied(self):
        s = self.client.session
        s[PRACTICE_DELEGATION_KEY] = {
            "session_id": str(self.session.pk),
            "codename": "VIEWER",
            "practice_type": "shooting",
        }
        s.save()
        self.assertEqual(self.client.get(self.url).status_code, 403)
