import json

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from billboard.models import BillboardEntry
from courts.models import CourtComplex
from courts.proximity import (
    VERIFICATION_ACCURACY_ASSISTED,
    VERIFICATION_AMBIGUOUS,
    VERIFICATION_NORMAL_RADIUS,
    VERIFICATION_USER_CONFIRMED_AMBIGUOUS,
    assess_court_proximity,
)
from friendly_games.models import PlayerCodename
from teams.models import Player, Team


class AccuracyAwareProximityTests(TestCase):
    def setUp(self):
        self.primary = CourtComplex.objects.create(
            name="Primary Physical Courts",
            description="",
            latitude="0.000000",
            longitude="0.000000",
        )

    def test_normal_radius_pass_remains_strict_and_needs_no_accuracy(self):
        assessment = assess_court_proximity(
            latitude=0.0005,
            longitude=0,
            selected_complex=self.primary,
            reported_accuracy=None,
        )

        self.assertTrue(assessment.allowed)
        self.assertEqual(assessment.outcome, VERIFICATION_NORMAL_RADIUS)
        self.assertEqual(assessment.effective_radius_metres, 200.0)

    def test_valid_accuracy_assists_only_the_current_reading(self):
        # Approximately 278m north of the selected Complex: outside 200m,
        # inside 200m + 100m.
        assessment = assess_court_proximity(
            latitude=0.0025,
            longitude=0,
            selected_complex=self.primary,
            reported_accuracy="100",
        )

        self.assertTrue(assessment.allowed)
        self.assertEqual(assessment.outcome, VERIFICATION_ACCURACY_ASSISTED)
        self.assertAlmostEqual(assessment.effective_radius_metres, 300.0)

    def test_invalid_accuracy_falls_back_to_existing_strict_radius(self):
        assessment = assess_court_proximity(
            latitude=0.0025,
            longitude=0,
            selected_complex=self.primary,
            reported_accuracy="not-a-number",
        )

        self.assertFalse(assessment.allowed)
        self.assertIsNone(assessment.reported_accuracy_metres)
        self.assertEqual(assessment.effective_radius_metres, 200.0)

    def test_multiple_overlapping_physical_venues_require_confirmation(self):
        nearby = CourtComplex.objects.create(
            name="Nearby Physical Courts",
            description="",
            latitude="0.001000",
            longitude="0.000000",
        )

        first_assessment = assess_court_proximity(
            latitude=0.0025,
            longitude=0,
            selected_complex=self.primary,
            reported_accuracy="100",
        )
        confirmed_assessment = assess_court_proximity(
            latitude=0.0025,
            longitude=0,
            selected_complex=self.primary,
            reported_accuracy="100",
            venue_confirmed=True,
        )

        self.assertEqual(first_assessment.outcome, VERIFICATION_AMBIGUOUS)
        self.assertEqual(
            {venue.pk for venue in first_assessment.overlapping_complexes},
            {self.primary.pk, nearby.pk},
        )
        self.assertEqual(
            confirmed_assessment.outcome,
            VERIFICATION_USER_CONFIRMED_AMBIGUOUS,
        )


class AccuracyAwarePresenceEndpointTests(TestCase):
    def setUp(self):
        self.primary = CourtComplex.objects.create(
            name="Presence Physical Courts",
            description="",
            latitude="0.000000",
            longitude="0.000000",
        )
        session = self.client.session
        session["player_codename"] = "GEO001"
        session["session_active"] = True
        session.save()

    def _post_here(self, **payload):
        payload.setdefault("court_id", self.primary.pk)
        return self.client.post(
            reverse("billboard:api_im_here"),
            data=json.dumps(payload),
            content_type="application/json",
        )

    def test_manual_presence_persists_accuracy_assisted_provenance(self):
        response = self._post_here(latitude=0.0025, longitude=0, accuracy=100)

        self.assertEqual(response.status_code, 200)
        self.assertIn("low location accuracy", response.json()["accuracy_notice"])
        entry = BillboardEntry.objects.get(action_type="AT_COURTS")
        self.assertEqual(
            entry.location_verification,
            BillboardEntry.LOCATION_VERIFICATION_ACCURACY_ASSISTED,
        )

    def test_manual_presence_requires_choice_for_ambiguous_accuracy_assistance(self):
        nearby = CourtComplex.objects.create(
            name="Ambiguous Physical Courts",
            description="",
            latitude="0.001000",
            longitude="0.000000",
        )

        response = self._post_here(latitude=0.0025, longitude=0, accuracy=100)
        self.assertEqual(response.status_code, 409)
        self.assertTrue(response.json()["requires_venue_confirmation"])
        self.assertEqual(BillboardEntry.objects.filter(action_type="AT_COURTS").count(), 0)
        self.assertEqual(
            {venue["id"] for venue in response.json()["verification"]["venues"]},
            {self.primary.pk, nearby.pk},
        )

        confirmed = self._post_here(
            latitude=0.0025,
            longitude=0,
            accuracy=100,
            confirm_ambiguous_venue=True,
        )
        self.assertEqual(confirmed.status_code, 200)
        entry = BillboardEntry.objects.get(action_type="AT_COURTS")
        self.assertEqual(
            entry.location_verification,
            BillboardEntry.LOCATION_VERIFICATION_USER_CONFIRMED_AMBIGUOUS,
        )

    def test_gps_detects_different_court_despite_stale_selector(self):
        other = CourtComplex.objects.create(
            name="Actual Physical Courts", latitude="0.020000", longitude="0.000000"
        )
        response = self._post_here(
            court_id=self.primary.pk, latitude=0.02, longitude=0, accuracy=10,
            is_anonymous=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["court_id"], other.pk)
        entry = BillboardEntry.objects.get(action_type="AT_COURTS")
        self.assertEqual(entry.court_complex_id, other.pk)
        self.assertTrue(entry.is_anonymous)
        self.assertEqual(entry.location_verification, VERIFICATION_NORMAL_RADIUS)

    def test_virtual_selector_does_not_disable_physical_checkin(self):
        virtual = CourtComplex.objects.create(name="Virtual Courts", description="")
        defaults = self.client.get(reverse("billboard:api_defaults"), {"court_id": virtual.pk})
        self.assertTrue(defaults.json()["manual_here_available"])
        response = self._post_here(
            court_id=virtual.pk, latitude=0, longitude=0, accuracy=5
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["court_id"], self.primary.pk)

    def test_no_court_id_needed(self):
        response = self.client.post(
            reverse("billboard:api_im_here"),
            data=json.dumps({"latitude": 0, "longitude": 0, "accuracy": 5}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["court_id"], self.primary.pk)

    def test_overlapping_normal_radii_require_explicit_choice(self):
        nearby = CourtComplex.objects.create(
            name="Nearby Courts", latitude="0.001000", longitude="0.000000"
        )
        response = self._post_here(latitude=0.0005, longitude=0, accuracy=5)
        self.assertEqual(response.status_code, 409)
        self.assertTrue(response.json()["requires_venue_confirmation"])
        self.assertEqual(
            {venue["id"] for venue in response.json()["verification"]["venues"]},
            {self.primary.pk, nearby.pk},
        )
        self.assertFalse(BillboardEntry.objects.filter(action_type="AT_COURTS").exists())
        confirmed = self._post_here(
            court_id=nearby.pk, latitude=0.0005, longitude=0, accuracy=5,
            confirm_ambiguous_venue=True,
        )
        self.assertEqual(confirmed.status_code, 200)
        self.assertEqual(BillboardEntry.objects.get(action_type="AT_COURTS").court_complex_id, nearby.pk)

    def test_outside_all_venues_does_not_register(self):
        response = self._post_here(latitude=0.05, longitude=0, accuracy=10)
        self.assertEqual(response.status_code, 403)
        self.assertFalse(BillboardEntry.objects.filter(action_type="AT_COURTS").exists())

    def test_confirmation_cannot_select_non_candidate(self):
        remote = CourtComplex.objects.create(
            name="Remote Courts", latitude="0.020000", longitude="0.000000"
        )
        response = self._post_here(
            court_id=remote.pk, latitude=0, longitude=0, accuracy=5,
            confirm_ambiguous_venue=True,
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(BillboardEntry.objects.filter(action_type="AT_COURTS").exists())


class AccuracyAwareFriendlyEndpointTests(TestCase):
    def setUp(self):
        self.team = Team.objects.create(name="Accuracy Friendly Team")
        self.player = Player.objects.create(name="Accuracy Creator", team=self.team)
        self.codename = PlayerCodename.objects.create(player=self.player, codename="GEO002")
        self.primary = CourtComplex.objects.create(
            name="Friendly Physical Courts",
            description="",
            latitude="0.000000",
            longitude="0.000000",
        )
        CourtComplex.objects.create(name="Virtual Friendly Courts", description="")
        BillboardEntry.objects.create(
            codename=self.codename.codename,
            action_type="AT_COURTS",
            court_complex=self.primary,
            presence_source=BillboardEntry.PRESENCE_SOURCE_MANUAL,
            location_verification=BillboardEntry.LOCATION_VERIFICATION_NORMAL_RADIUS,
            is_active=True,
            created_at=timezone.now(),
        )
        session = self.client.session
        session["player_codename"] = self.codename.codename
        session["session_active"] = True
        session.save()

    def test_friendly_nearby_player_lookup_uses_shared_accuracy_assistance(self):
        response = self.client.post(
            reverse("friendly_games:available_court_players_api"),
            {
                "court_complex_id": self.primary.pk,
                "latitude": "0.0025",
                "longitude": "0",
                "accuracy": "100",
                "position_timestamp": "1700000000000",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["verification"]["verification_outcome"],
            VERIFICATION_ACCURACY_ASSISTED,
        )
        self.assertIn("low location accuracy", response.json()["accuracy_notice"])
