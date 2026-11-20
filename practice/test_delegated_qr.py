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


class PracticeOwnerSwitchTests(TestCase):
    """A QR scan authorises one player/session; switching does not erase the grant."""

    def setUp(self):
        self.own = PracticeSession.objects.create(
            player_codename="SELF01", practice_type="shooting")
        self.linda = PracticeSession.objects.create(
            player_codename="LINDA1", practice_type="shooting")
        self.other = PracticeSession.objects.create(
            player_codename="OTHER1", practice_type="pointing")
        session = self.client.session
        session["player_codename"] = "SELF01"
        session["session_active"] = True
        session.save()

    def _scan(self, codename, practice_type):
        session = self.client.session
        session["qr_resolved_codename"] = codename
        session.save()
        with patch("friendly_games.models.PlayerCodename.objects.filter") as players:
            players.return_value.exists.return_value = True
            return self.client.post(
                reverse("practice:authorize_practice_qr"),
                data=json.dumps({"practice_type": practice_type}),
                content_type="application/json")

    def _choose(self, owner, practice_type="shooting"):
        return self.client.post(
            reverse("practice:select_practice_owner"),
            data=json.dumps({"owner": owner, "practice_type": practice_type}),
            content_type="application/json")

    def _shot(self, session_id, outcome="hit"):
        return self.client.post(
            reverse("practice:record_shot"),
            data=json.dumps({"outcome": outcome, "session_id": str(session_id)}),
            content_type="application/json")

    def test_last_scanned_default_and_return_without_rescan(self):
        self.assertEqual(self._scan("LINDA1", "shooting").status_code, 200)
        self.assertEqual(
            self.client.session["practice_selected_owner"], "LINDA1:shooting")
        # Navigating around the PFC does not change the selected recipient.
        self.client.get(reverse("practice:practice_home"))
        response = self.client.get(reverse("practice:shooting_practice"))
        self.assertEqual(response.context["practice_selected_key"], "LINDA1:shooting")
        self.assertEqual(str(response.context["active_session"].pk), str(self.linda.pk))

        self.assertEqual(self._choose("self").status_code, 200)
        self.assertEqual(self._shot(self.own.pk).status_code, 200)
        self.assertEqual(self._choose("LINDA1:shooting").status_code, 200)
        self.assertEqual(self._shot(self.linda.pk).status_code, 200)
        self.own.refresh_from_db()
        self.linda.refresh_from_db()
        self.assertEqual(self.own.total_shots, 1)
        self.assertEqual(self.linda.total_shots, 1)

    def test_multiple_authorized_players_and_previous_session_switch(self):
        self._scan("LINDA1", "shooting")
        self._scan("OTHER1", "pointing")
        self.assertEqual(
            self.client.session["practice_selected_owner"], "OTHER1:pointing")
        options = self.client.get(reverse("practice:pointing_practice")).context[
            "practice_owner_choices"]
        self.assertEqual([o["key"] for o in options],
                         ["self", "LINDA1:shooting", "OTHER1:pointing"])
        self.assertEqual(self._shot(self.other.pk, "good").status_code, 200)
        response = self._choose("LINDA1:shooting")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["next_url"],
                         reverse("practice:shooting_practice"))
        self.assertEqual(self._shot(self.linda.pk).status_code, 200)
        self.assertIn("OTHER1:pointing", self.client.session["practice_qr_grants"])

    def test_switching_tabs_cannot_silently_reassign_shots(self):
        self._scan("LINDA1", "shooting")
        self._choose("self")
        # Old tab still displays Linda's session ID, not the current recipient.
        response = self._shot(self.linda.pk)
        self.assertEqual(response.status_code, 409)
        self.linda.refresh_from_db()
        self.own.refresh_from_db()
        self.assertEqual(self.linda.total_shots, 0)
        self.assertEqual(self.own.total_shots, 0)

    def test_unknown_qr_owner_selection_denied(self):
        self._scan("LINDA1", "shooting")
        response = self._choose("UNAUTHORIZED:shooting")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.client.session["practice_selected_owner"],
                         "LINDA1:shooting")

    def test_completing_one_qr_session_preserves_other_authorizations(self):
        self._scan("LINDA1", "shooting")
        self._scan("OTHER1", "pointing")
        response = self.client.post(
            reverse("practice:end_session"),
            data=json.dumps({"session_id": str(self.other.pk)}),
            content_type="application/json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertNotIn("OTHER1:pointing", self.client.session["practice_qr_grants"])
        self.assertIn("LINDA1:shooting", self.client.session["practice_qr_grants"])
        self.assertEqual(self._choose("LINDA1:shooting").status_code, 200)
        self.assertEqual(self._shot(self.linda.pk).status_code, 200)

    def test_ended_session_rejects_stale_shot_no_fallback_to_self(self):
        self._scan("LINDA1", "shooting")
        self.linda.end_session()
        response = self._shot(self.linda.pk)
        self.assertEqual(response.status_code, 409)
        self.own.refresh_from_db()
        self.assertEqual(self.own.total_shots, 0)

    def test_logout_revokes_all_qr_grants(self):
        self._scan("LINDA1", "shooting")
        self._scan("OTHER1", "pointing")
        self.client.get(reverse("codename_logout"))
        self.assertNotIn("practice_qr_grants", self.client.session)
        self.assertNotIn("delegated_practice_session", self.client.session)
        self.assertNotIn("practice_selected_owner", self.client.session)

    def test_changing_operator_login_revokes_grants_but_same_login_retains(self):
        from types import SimpleNamespace
        from pfc_core.session_utils import CodenameSessionManager

        self._scan("LINDA1", "shooting")
        request = SimpleNamespace(session=dict(self.client.session))
        self.assertTrue(CodenameSessionManager.login_player(request, "SELF01"))
        self.assertIn("practice_qr_grants", request.session)
        self.assertTrue(CodenameSessionManager.login_player(request, "NEW002"))
        self.assertNotIn("practice_qr_grants", request.session)
        self.assertNotIn("delegated_practice_session", request.session)
        self.assertNotIn("practice_selected_owner", request.session)
