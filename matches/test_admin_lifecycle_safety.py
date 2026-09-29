from datetime import timedelta
from unittest.mock import patch

from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from courts.admin import CourtAdmin
from courts.models import Court
from matches.admin import MatchAdmin
from matches.lifecycle import reconcile_court_occupancy, release_court_and_requeue_match
from matches.models import Match, MatchPlayer
from teams.models import Player, Team
from tournaments.forms import StageForm
from tournaments.models import Round, Stage, Tournament


class LifecycleSafeAdminTests(TestCase):
    def setUp(self):
        now = timezone.now()
        self.tournament = Tournament.objects.create(
            name="Admin Lifecycle Safety",
            format="swiss",
            start_date=now,
            end_date=now + timedelta(hours=3),
        )
        self.team1 = Team.objects.create(name="Admin Lifecycle A", pin="950101")
        self.team2 = Team.objects.create(name="Admin Lifecycle B", pin="950102")
        self.court = Court.objects.create(number=95001, is_available=False)
        self.tournament.courts.add(self.court)
        self.match = Match.objects.create(
            tournament=self.tournament,
            team1=self.team1,
            team2=self.team2,
            status="active",
            court=self.court,
            start_time=now,
        )
        for team, suffix in ((self.team1, "a"), (self.team2, "b")):
            player = Player.objects.create(name=f"Admin-{suffix}", team=team)
            MatchPlayer.objects.create(match=self.match, player=player, team=team)

        self.staff = get_user_model().objects.create_superuser(
            username="admin-lifecycle-test",
            email="admin-lifecycle-test@example.test",
            password="test-password",
        )

    def test_release_action_requeues_through_lifecycle_service(self):
        outcome = release_court_and_requeue_match(self.match.id)

        self.assertEqual(outcome.state, "requeued")
        self.match.refresh_from_db()
        self.court.refresh_from_db()
        self.assertEqual(self.match.status, "pending_verification")
        self.assertTrue(self.match.waiting_for_court)
        self.assertIsNone(self.match.court_id)
        self.assertEqual(self.match.proposed_court_id, self.court.id)
        self.assertTrue(self.court.is_available)

    def test_court_reconciliation_preserves_live_match_as_authority(self):
        self.court.is_available = True
        self.court.save(update_fields=["is_available"])

        outcome = reconcile_court_occupancy(self.court.id)

        self.assertEqual(outcome.state, "owned_by_live_match")
        self.court.refresh_from_db()
        self.assertFalse(self.court.is_available)
        self.match.refresh_from_db()
        self.assertEqual(self.match.status, "active")
        self.assertEqual(self.match.court_id, self.court.id)

    def test_court_reconciliation_recovers_orphaned_occupied_flag(self):
        orphan = Court.objects.create(number=95002, is_available=False)

        outcome = reconcile_court_occupancy(orphan.id)

        self.assertEqual(outcome.state, "reconciled_available")
        orphan.refresh_from_db()
        self.assertTrue(orphan.is_available)

    def test_admin_activation_action_uses_lifecycle_service(self):
        self.match.status = "pending_verification"
        self.match.court = None
        self.match.start_time = None
        self.match.waiting_for_court = False
        self.match.save(update_fields=["status", "court", "start_time", "waiting_for_court", "updated_at"])
        self.court.is_available = True
        self.court.save(update_fields=["is_available"])
        self.client.force_login(self.staff)

        response = self.client.post(
            reverse("admin:matches_match_changelist"),
            {
                "action": "activate_or_assign_court",
                "_selected_action": [str(self.match.id)],
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.match.refresh_from_db()
        self.court.refresh_from_db()
        self.assertEqual(self.match.status, "active")
        self.assertEqual(self.match.court_id, self.court.id)
        self.assertFalse(self.court.is_available)

    def test_admin_release_action_uses_lifecycle_service(self):
        self.client.force_login(self.staff)

        response = self.client.post(
            reverse("admin:matches_match_changelist"),
            {
                "action": "release_court_and_requeue",
                "_selected_action": [str(self.match.id)],
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.match.refresh_from_db()
        self.court.refresh_from_db()
        self.assertEqual(self.match.status, "pending_verification")
        self.assertIsNone(self.match.court_id)
        self.assertTrue(self.match.waiting_for_court)
        self.assertTrue(self.court.is_available)

    def test_admin_cancel_action_uses_lifecycle_service(self):
        self.client.force_login(self.staff)

        response = self.client.post(
            reverse("admin:matches_match_changelist"),
            {
                "action": "cancel_match_and_release_court",
                "_selected_action": [str(self.match.id)],
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.match.refresh_from_db()
        self.court.refresh_from_db()
        self.assertEqual(self.match.status, "cancelled")
        self.assertTrue(self.court.is_available)

    @patch("matches.admin.process_tournament_transition", return_value=True)
    def test_admin_retry_action_calls_transition_service(self, retry_transition):
        from matches.models import MatchLifecycleTransition

        MatchLifecycleTransition.objects.create(
            match=self.match,
            tournament=self.tournament,
            status=MatchLifecycleTransition.FAILED,
            last_error="fixture failure",
        )
        self.client.force_login(self.staff)

        response = self.client.post(
            reverse("admin:matches_match_changelist"),
            {
                "action": "retry_lifecycle_transition",
                "_selected_action": [str(self.match.id)],
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        retry_transition.assert_called_once_with(self.match.id)

    def test_admin_court_reconciliation_action_uses_lifecycle_service(self):
        orphan = Court.objects.create(number=95003, is_available=False)
        self.client.force_login(self.staff)

        response = self.client.post(
            reverse("admin:courts_court_changelist"),
            {
                "action": "reconcile_lifecycle_occupancy",
                "_selected_action": [str(orphan.id)],
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        orphan.refresh_from_db()
        self.assertTrue(orphan.is_available)

    def test_admin_does_not_expose_raw_lifecycle_or_destructive_controls(self):
        match_admin = MatchAdmin(Match, AdminSite())
        court_admin = CourtAdmin(Court, AdminSite())
        request = RequestFactory().get("/admin/")
        request.user = self.staff
        actions = match_admin.get_actions(request)

        self.assertNotIn("generate_matches", actions)
        self.assertNotIn("advance_knockout_tournaments", actions)
        self.assertFalse(match_admin.has_add_permission(request))
        self.assertFalse(match_admin.has_delete_permission(request, self.match))
        self.assertIn("is_available", court_admin.get_readonly_fields(request, self.court))
        self.assertFalse(court_admin.has_delete_permission(request, self.court))

    def test_stage_form_enforces_current_round_robin_semantics(self):
        invalid = StageForm(
            data={
                "tournament": self.tournament.id,
                "stage_number": 1,
                "name": "Invalid Round Robin",
                "format": "round_robin",
                "num_rounds_in_stage": 2,
                "num_qualifiers": 0,
                "num_matches_per_team": "",
            }
        )
        self.assertFalse(invalid.is_valid())
        self.assertIn("num_rounds_in_stage", invalid.errors)

        valid = StageForm(
            data={
                "tournament": self.tournament.id,
                "stage_number": 1,
                "name": "Round Robin",
                "format": "round_robin",
                "num_rounds_in_stage": 1,
                "num_qualifiers": 0,
                "num_matches_per_team": "",
            }
        )
        self.assertTrue(valid.is_valid(), valid.errors)

    def test_generated_stage_rejects_destructive_admin_edit(self):
        stage = Stage.objects.create(
            tournament=self.tournament,
            stage_number=1,
            format="swiss",
            num_rounds_in_stage=1,
            num_qualifiers=0,
        )
        Round.objects.create(tournament=self.tournament, stage=stage, number=1, number_in_stage=1)
        self.client.force_login(self.staff)

        response = self.client.post(
            reverse("admin:tournaments_stage_change", args=[stage.id]),
            {
                "tournament": self.tournament.id,
                "stage_number": 1,
                "name": stage.name,
                "format": "knockout",
                "num_rounds_in_stage": 1,
                "num_qualifiers": 0,
                "_save": "Save",
            },
        )

        self.assertIn(response.status_code, {200, 302})
        stage.refresh_from_db()
        self.assertEqual(stage.format, "swiss")
