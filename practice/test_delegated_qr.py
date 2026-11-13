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
