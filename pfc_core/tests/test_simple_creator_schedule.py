"""Regression coverage for Simple Creator's venue-local scheduling defaults."""
from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from courts.models import Court, CourtComplex
from simple_creator.models import TournamentScenario
from tournaments.models import Tournament


class SimpleCreatorScheduleTests(TestCase):
    def setUp(self):
        self.venue = CourtComplex.objects.create(
            name="Schedule test venue", description="Isolated test venue",
            timezone_name="Europe/Athens",
        )
        court = Court.objects.create(number=95071, is_available=True)
        self.venue.courts.add(court)
        self.scenario = TournamentScenario.objects.create(
            name="schedule-fixture", display_name="Schedule Fixture",
            description="Test scenario", default_court_complex=self.venue,
            tournament_type="swiss", draft_type="snake", is_free=True,
            max_courts=1,
        )
        self.url = reverse("create_simple_tournament")
        self.base = {"scenario": self.scenario.name, "format": "doubles", "num_courts": "1"}

    def create(self, **fields):
        return self.client.post(self.url, {**self.base, **fields})

    def latest(self):
        return Tournament.objects.filter(name__startswith="Schedule Fixture").latest("id")

    @patch("pfc_core.simple_creator.timezone.now")
    def test_now_starts_in_30_minutes_and_ends_three_hours_later(self, mocked_now):
        now = datetime(2026, 11, 15, 10, 20, tzinfo=ZoneInfo("UTC"))
        mocked_now.return_value = now
        response = self.create(schedule_mode="now")
        self.assertEqual(response.status_code, 302)
        tournament = self.latest()
        self.assertEqual(tournament.start_date, now + timedelta(minutes=30))
        self.assertEqual(tournament.end_date, now + timedelta(hours=3, minutes=30))
        self.assertIn("2026-11-15", tournament.name)

    @patch("pfc_core.simple_creator.timezone.now")
    def test_scheduled_uses_venue_timezone_not_server_timezone(self, mocked_now):
        mocked_now.return_value = datetime(2026, 11, 15, 10, 0, tzinfo=ZoneInfo("UTC"))
        response = self.create(schedule_mode="scheduled", scheduled_start="2026-11-16T17:45")
        self.assertEqual(response.status_code, 302)
        tournament = self.latest()
        self.assertEqual(timezone.localtime(tournament.start_date, ZoneInfo("Europe/Athens")).strftime("%Y-%m-%d %H:%M"), "2026-11-16 17:45")
        self.assertEqual(tournament.end_date - tournament.start_date, timedelta(hours=3))
        self.assertIn("2026-11-16", tournament.name)

    @patch("pfc_core.simple_creator.timezone.now")
    def test_scheduled_allows_start_under_ten_minutes_away(self, mocked_now):
        mocked_now.return_value = datetime(2026, 11, 15, 10, 0, tzinfo=ZoneInfo("UTC"))
        response = self.create(schedule_mode="scheduled", scheduled_start="2026-11-15T12:05")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.latest().start_date, datetime(2026, 11, 15, 10, 5, tzinfo=ZoneInfo("UTC")))

    @patch("pfc_core.simple_creator.timezone.now")
    def test_past_start_rejected_without_creating_tournament(self, mocked_now):
        mocked_now.return_value = datetime(2026, 11, 15, 10, 0, tzinfo=ZoneInfo("UTC"))
        response = self.create(schedule_mode="scheduled", scheduled_start="2026-11-15T11:59")
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Tournament.objects.filter(name__startswith="Schedule Fixture").exists())

    @patch("pfc_core.simple_creator.timezone.now")
    def test_nonexistent_dst_local_time_rejected(self, mocked_now):
        mocked_now.return_value = datetime(2026, 3, 20, 10, 0, tzinfo=ZoneInfo("UTC"))
        response = self.create(schedule_mode="scheduled", scheduled_start="2026-03-29T03:30")
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Tournament.objects.filter(name__startswith="Schedule Fixture").exists())

    def test_invalid_schedule_mode_rejected(self):
        response = self.create(schedule_mode="invalid")
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Tournament.objects.filter(name__startswith="Schedule Fixture").exists())
