"""Focused QR practice delegation regressions; independent of PETA."""
import json
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from practice.models import PracticeSession
from practice.views import PRACTICE_DELEGATION_KEY


class DelegatedPracticeQrTests(TestCase):
    def setUp(self):
        self.owner = "PRACT1"
        self.other = "OTHER1"
        self.shooting = PracticeSession.objects.create(
            player_codename=self.owner, practice_type="shooting")
        self.pointing = PracticeSession.objects.create(
            player_codename=self.other, practice_type="pointing")

    def _qr(self, codename, practice_type="shooting"):
        session = self.client.session
        session["qr_resolved_codename"] = codename
        session.save()
        with patch("friendly_games.models.PlayerCodename.objects.filter") as players:
            players.return_value.exists.return_value = True
            return self.client.post(
                reverse("practice:authorize_practice_qr"),
                data=json.dumps({"practice_type": practice_type}),
                content_type="application/json")

    def test_qr_proof_required(self):
        response = self.client.post(
            reverse("practice:authorize_practice_qr"),
            data=json.dumps({"practice_type": "shooting"}),
            content_type="application/json")
        self.assertEqual(response.status_code, 403)

    def test_shooting_delegation_records_only_for_qr_owner(self):
        response = self._qr(self.owner)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("qr_resolved_codename", self.client.session)
        response = self.client.post(
            reverse("practice:record_shot"),
            data=json.dumps({"outcome": "hit"}), content_type="application/json")
        self.assertEqual(response.status_code, 200, response.content)
        self.shooting.refresh_from_db()
        self.pointing.refresh_from_db()
        self.assertEqual(self.shooting.total_shots, 1)
        self.assertEqual(self.pointing.total_shots, 0)
        self.client.post(reverse("practice:leave_delegated_practice"))
        response = self.client.post(
            reverse("practice:record_shot"),
            data=json.dumps({"outcome": "hit"}), content_type="application/json")
        self.assertEqual(response.status_code, 401)

    def test_pointing_delegation_and_expiry(self):
        self.assertEqual(self._qr(self.other, "pointing").status_code, 200)
        response = self.client.post(
            reverse("practice:record_shot"),
            data=json.dumps({"outcome": "good"}), content_type="application/json")
        self.assertEqual(response.status_code, 200, response.content)
        self.pointing.refresh_from_db()
        self.assertEqual(self.pointing.total_shots, 1)
        self.pointing.end_session()
        response = self.client.post(
            reverse("practice:record_shot"),
            data=json.dumps({"outcome": "good"}), content_type="application/json")
        self.assertEqual(response.status_code, 404)
        self.assertNotIn(PRACTICE_DELEGATION_KEY, self.client.session)

    def test_qr_delegate_can_start_practice(self):
        self.assertEqual(self._qr("NEWONE", "shooting").status_code, 200)
        response = self.client.post(
            reverse("practice:start_session"),
            data=json.dumps({"practice_type": "shooting", "distance": "7m"}),
            content_type="application/json")
        self.assertEqual(response.status_code, 200, response.content)
        created = PracticeSession.objects.get(player_codename="NEWONE")
        self.assertEqual(
            self.client.session[PRACTICE_DELEGATION_KEY]["session_id"],
            str(created.pk))


class SmartPracticeRoutingTests(TestCase):
    """Smart CTA resumes the practice selected by the server's QR-aware owner resolver."""

    def _login(self, codename="SELF01"):
        session = self.client.session
        session["player_codename"] = codename
        session["session_active"] = True
        session.save()

    def _smart(self, tournament_candidates=None):
        from types import SimpleNamespace

        with (patch("pfc_core.smart_router._session_player",
                    return_value=SimpleNamespace(pk=1, id=1)),
              patch("pfc_core.smart_router._resolve_tournament_matches",
                    return_value=tournament_candidates or []),
              patch("pfc_core.smart_router._resolve_friendly_games",
                    return_value=[]),
              patch("pfc_core.smart_router._resolve_nearby_friendly_games",
                    return_value=None)):
            return self.client.get(reverse("my_active_matches"))

    def test_smart_resumes_own_active_shooting_practice(self):
        self._login()
        PracticeSession.objects.create(player_codename="SELF01", practice_type="shooting")
        response = self._smart()
        self.assertRedirects(response, reverse("practice:shooting_practice"),
                             fetch_redirect_response=False)

    def test_smart_resumes_own_active_pointing_practice(self):
        self._login()
        PracticeSession.objects.create(player_codename="SELF01", practice_type="pointing")
        response = self._smart()
        self.assertRedirects(response, reverse("practice:pointing_practice"),
                             fetch_redirect_response=False)

    def test_smart_ignores_completed_practice(self):
        self._login()
        PracticeSession.objects.create(player_codename="SELF01",
                                       practice_type="shooting", is_active=False)
        response = self._smart()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_count"], 0)

    def test_smart_resumes_delegated_session_not_own_practice(self):
        self._login()
        PracticeSession.objects.create(player_codename="SELF01", practice_type="pointing")
        delegated = PracticeSession.objects.create(
            player_codename="QR0001", practice_type="shooting")
        s = self.client.session
        s[PRACTICE_DELEGATION_KEY] = {
            "session_id": str(delegated.pk),
            "codename": "QR0001",
            "practice_type": "shooting",
        }
        s.save()

        # Navigating elsewhere must not revoke the server-side QR authorisation.
        self.client.get(reverse("practice:practice_home"))
        response = self._smart()
        self.assertRedirects(response, reverse("practice:shooting_practice"),
                             fetch_redirect_response=False)
        self.assertEqual(self.client.session[PRACTICE_DELEGATION_KEY]["codename"], "QR0001")

        # Explicitly leaving delegation returns Smart to the player's own session.
        self.client.post(reverse("practice:leave_delegated_practice"))
        response = self._smart()
        self.assertRedirects(response, reverse("practice:pointing_practice"),
                             fetch_redirect_response=False)

    def test_smart_routes_to_practice_directly_even_if_friendly_is_available(self):
        self._login()
        PracticeSession.objects.create(player_codename="SELF01", practice_type="shooting")
        from types import SimpleNamespace
        friendly = {"priority": 55, "url": "/friendly-games/123/",
                    "label": "Active Friendly", "match_type": "friendly"}
        with (patch("pfc_core.smart_router._session_player",
                    return_value=SimpleNamespace(pk=1, id=1)),
              patch("pfc_core.smart_router._resolve_tournament_matches", return_value=[]),
              patch("pfc_core.smart_router._resolve_friendly_games", return_value=[friendly]),
              patch("pfc_core.smart_router._resolve_nearby_friendly_games", return_value=None)):
            response = self.client.get(reverse("my_active_matches"))
        self.assertRedirects(response, reverse("practice:shooting_practice"),
                             fetch_redirect_response=False)

    def test_urgent_score_action_still_precedes_practice(self):
        self._login()
        PracticeSession.objects.create(player_codename="SELF01", practice_type="shooting")
        urgent = {"priority": 10, "url": "/score/validate/",
                  "label": "Validate Score", "match_type": "tournament"}
        response = self._smart(tournament_candidates=[urgent])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["best"]["priority"], 10)
        self.assertTrue(any(c["match_type"] == "practice"
                            for c in response.context["others"]))

    def test_match_state_json_poller_does_not_auto_redirect_to_practice(self):
        self._login()
        PracticeSession.objects.create(player_codename="SELF01", practice_type="shooting")
        from types import SimpleNamespace
        with (patch("pfc_core.smart_router._session_player",
                    return_value=SimpleNamespace(pk=1, id=1)),
              patch("pfc_core.smart_router._resolve_tournament_matches", return_value=[]),
              patch("pfc_core.smart_router._resolve_friendly_games", return_value=[]),
              patch("pfc_core.smart_router._resolve_nearby_friendly_games", return_value=None)):
            response = self.client.post(reverse("pfc_next_url"))
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["next_url"])
