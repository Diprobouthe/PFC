import json

from django.test import Client, TestCase
from django.urls import reverse

from billboard.models import BillboardEntry
from courts.models import CourtComplex


class BillboardPresenceIdentityAuthorizationTests(TestCase):
    def setUp(self):
        self.court = CourtComplex.objects.create(
            name="Presence Security Court",
            description="Test venue",
        )
        self.endpoints = {
            "im_here": reverse("billboard:api_im_here"),
            "going": reverse("billboard:api_going"),
            "cancel_going": reverse("billboard:api_cancel_going"),
            "leave": reverse("billboard:api_leave"),
            "availability": reverse("billboard:api_friendly_availability"),
            "community_report": reverse("billboard:api_community_report"),
            "community_confirm": reverse("billboard:api_community_confirm"),
        }

    def _json_post(self, client, url, payload, **extra):
        return client.post(
            url,
            data=json.dumps(payload),
            content_type="application/json",
            **extra,
        )

    def _set_player_session(self, codename="OWN001"):
        session = self.client.session
        session["player_codename"] = codename
        session["session_active"] = True
        session.save()

    def test_body_codename_cannot_mutate_any_presence_or_community_endpoint(self):
        payloads = {
            "im_here": {"codename": "OTHER1", "court_id": self.court.pk, "latitude": 0, "longitude": 0},
            "going": {"codename": "OTHER1", "court_id": self.court.pk, "arrival_mode": "plus30"},
            "cancel_going": {"codename": "OTHER1", "entry_id": 1},
            "leave": {"codename": "OTHER1"},
            "availability": {"codename": "OTHER1", "available_for_friendly": True},
            "community_report": {"codename": "OTHER1", "court_id": self.court.pk, "count": 4},
            "community_confirm": {"codename": "OTHER1", "court_id": self.court.pk},
        }
        for name, payload in payloads.items():
            with self.subTest(endpoint=name):
                response = self._json_post(self.client, self.endpoints[name], payload)
                self.assertEqual(response.status_code, 401)

    def test_authenticated_session_identity_overrides_a_forged_body_codename(self):
        self._set_player_session("OWN001")
        response = self._json_post(
            self.client,
            self.endpoints["going"],
            {
                "codename": "OTHER1",
                "court_id": self.court.pk,
                "arrival_mode": "plus30",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        entry = BillboardEntry.objects.get(pk=response.json()["entry_id"])
        self.assertEqual(entry.codename, "OWN001")

    def test_billboard_page_sets_csrf_cookie_and_mutations_require_it(self):
        csrf_client = Client(enforce_csrf_checks=True)
        session = csrf_client.session
        session["player_codename"] = "OWN001"
        session["session_active"] = True
        session.save()

        payload = {"court_id": self.court.pk, "arrival_mode": "plus30"}
        response = self._json_post(csrf_client, self.endpoints["going"], payload)
        self.assertEqual(response.status_code, 403)

        response = csrf_client.get(reverse("billboard:list"))
        self.assertEqual(response.status_code, 200)
        token = response.cookies["csrftoken"].value
        response = self._json_post(
            csrf_client,
            self.endpoints["going"],
            payload,
            HTTP_X_CSRFTOKEN=token,
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
