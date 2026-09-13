from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from teams.models import Player, Team
from tournaments.models import MeleePlayer, Tournament
from tournaments.registration_services import register_melee_player_for_tournament


class SimpleTournamentRegistrationRemovalTests(TestCase):
    def setUp(self):
        now = timezone.now()
        self.tournament = Tournament.objects.create(
            name="Simple management removal test",
            description="Focused test fixture",
            start_date=now + timedelta(days=1),
            end_date=now + timedelta(days=1, hours=8),
            format="multi_stage",
            is_melee=True,
            is_active=True,
            melee_teams_generated=False,
            max_participants=12,
        )
        self.team = Team.objects.create(name="Removal test team", pin="990001")
        self.player = Player.objects.create(name="Remove me", team=self.team)
        self.second_player = Player.objects.create(name="Keep me", team=self.team)
        self.other_tournament = Tournament.objects.create(
            name="Other tournament",
            description="Isolation fixture",
            start_date=now + timedelta(days=2),
            end_date=now + timedelta(days=2, hours=8),
            format="multi_stage",
            is_melee=True,
            is_active=True,
            melee_teams_generated=False,
            max_participants=12,
        )
        self.registration = MeleePlayer.objects.create(
            tournament=self.tournament,
            player=self.player,
            original_team=self.team,
        )
        self.other_registration = MeleePlayer.objects.create(
            tournament=self.other_tournament,
            player=self.player,
            original_team=self.team,
        )

    def _authorize_creator_session(self, client, tournament=None):
        session = client.session
        session["simple_tournament_info"] = {
            "tournament_id": (tournament or self.tournament).id,
            "tournament_name": (tournament or self.tournament).name,
        }
        session.save()

    def _remove_url(self, registration=None):
        registration = registration or self.registration
        return reverse(
            "remove_simple_tournament_player",
            kwargs={
                "tournament_id": self.tournament.id,
                "melee_player_id": registration.id,
            },
        )

    def test_authorized_creator_removes_only_that_tournament_registration(self):
        self._authorize_creator_session(self.client)

        response = self.client.post(self._remove_url(), follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(MeleePlayer.objects.filter(pk=self.registration.pk).exists())
        self.assertTrue(MeleePlayer.objects.filter(pk=self.other_registration.pk).exists())
        self.assertTrue(Player.objects.filter(pk=self.player.pk).exists())
        self.assertTrue(Team.objects.filter(pk=self.team.pk).exists())
        self.assertContains(response, "Registered Players (0)")
        self.assertContains(response, "was removed from this tournament registration")

    def test_removed_player_can_register_again_through_central_registration_service(self):
        self._authorize_creator_session(self.client)
        self.client.post(self._remove_url())

        registration, created, _ = register_melee_player_for_tournament(
            tournament=self.tournament,
            player=self.player,
        )

        self.assertTrue(created)
        self.assertEqual(registration.tournament_id, self.tournament.id)
        self.assertEqual(registration.player_id, self.player.id)

    def test_unauthorized_request_cannot_remove_registration(self):
        response = self.client.post(self._remove_url(), follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(MeleePlayer.objects.filter(pk=self.registration.pk).exists())
        self.assertContains(response, "Tournament management access is required")

    def test_wrong_creator_session_cannot_remove_registration(self):
        self._authorize_creator_session(self.client, self.other_tournament)

        self.client.post(self._remove_url())

        self.assertTrue(MeleePlayer.objects.filter(pk=self.registration.pk).exists())

    def test_staff_override_can_remove_registration(self):
        staff = get_user_model().objects.create_user(
            username="simple-removal-staff",
            password="safe-test-password",
            is_staff=True,
        )
        self.client.force_login(staff)

        self.client.post(self._remove_url())

        self.assertFalse(MeleePlayer.objects.filter(pk=self.registration.pk).exists())

    def test_post_without_csrf_is_rejected(self):
        csrf_client = Client(enforce_csrf_checks=True)
        self._authorize_creator_session(csrf_client)

        response = csrf_client.post(self._remove_url())

        self.assertEqual(response.status_code, 403)
        self.assertTrue(MeleePlayer.objects.filter(pk=self.registration.pk).exists())

    def test_after_generation_removal_control_and_direct_removal_are_unavailable(self):
        self.tournament.melee_teams_generated = True
        self.tournament.save(update_fields=["melee_teams_generated"])
        self._authorize_creator_session(self.client)

        management = self.client.get(
            reverse("manage_tournament", kwargs={"tournament_id": self.tournament.id})
        )
        response = self.client.post(self._remove_url(), follow=True)

        self.assertNotContains(management, self._remove_url())
        self.assertTrue(MeleePlayer.objects.filter(pk=self.registration.pk).exists())
        self.assertContains(response, "can no longer be removed")

    def test_pre_start_management_keeps_existing_start_action_available_at_four_players(self):
        for number in range(3):
            player = Player.objects.create(name=f"Starter {number}", team=self.team)
            MeleePlayer.objects.create(
                tournament=self.tournament,
                player=player,
                original_team=self.team,
            )
        self._authorize_creator_session(self.client)

        response = self.client.get(
            reverse("manage_tournament", kwargs={"tournament_id": self.tournament.id})
        )

        self.assertContains(response, "Generate Teams &amp; Start")
        self.assertContains(
            response,
            reverse("start_tournament", kwargs={"tournament_id": self.tournament.id}),
        )
