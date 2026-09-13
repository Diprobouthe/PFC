import unittest
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from signin.models import TeamTournamentSignin
from teams.models import Team, TeamProfile
from tournaments.models import Tournament


class TournamentSigninAuthorizationTests(TestCase):
    def setUp(self):
        now = timezone.now()
        self.tournament = Tournament.objects.create(
            name="Authorization Tournament",
            format="knockout",
            play_format="doublets",
            start_date=now + timedelta(days=1),
            end_date=now + timedelta(days=2),
        )
        self.team_a = Team.objects.create(name="Authorised Team", pin="111111")
        self.team_b = Team.objects.create(name="Other Team", pin="222222")
        self.signin_a = TeamTournamentSignin.objects.create(
            team=self.team_a,
            tournament=self.tournament,
            is_active=True,
        )

    def _dashboard_url(self, team):
        return reverse(
            "team_tournament_dashboard",
            kwargs={"team_id": team.pk, "tournament_id": self.tournament.pk},
        )

    def _signout_url(self, team):
        return reverse(
            "tournament_signout",
            kwargs={"team_id": team.pk, "tournament_id": self.tournament.pk},
        )

    def _authorise_team_session(self, team):
        session = self.client.session
        session["team_id"] = team.pk
        session["team_name"] = team.name
        session.save()

    def test_dashboard_rejects_request_without_target_team_session(self):
        response = self.client.get(self._dashboard_url(self.team_a))
        self.assertEqual(response.status_code, 403)

    def test_dashboard_allows_the_existing_target_team_session_only(self):
        self._authorise_team_session(self.team_a)
        response = self.client.get(self._dashboard_url(self.team_a))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.team_a.name)

        response = self.client.get(self._dashboard_url(self.team_b))
        self.assertEqual(response.status_code, 403)

    def test_existing_team_pin_session_can_access_its_dashboard(self):
        session = self.client.session
        session["team_pin"] = self.team_a.pin
        session["team_session_active"] = True
        session.save()
        response = self.client.get(self._dashboard_url(self.team_a))
        self.assertEqual(response.status_code, 200)

    def test_normal_team_pin_signin_establishes_dashboard_authorization(self):
        TeamProfile.objects.filter(team=self.team_a).update(profile_type="full")
        response = self.client.post(
            reverse("tournament_signin"),
            {
                "team": self.team_a.pk,
                "tournament": self.tournament.pk,
                "pin": self.team_a.pin,
            },
        )
        self.assertRedirects(response, self._dashboard_url(self.team_a))
        self.assertEqual(self.client.session["team_id"], self.team_a.pk)

    def test_signout_requires_post_and_target_team_authorization(self):
        self._authorise_team_session(self.team_b)
        response = self.client.post(self._signout_url(self.team_a))
        self.assertEqual(response.status_code, 403)
        self.signin_a.refresh_from_db()
        self.assertTrue(self.signin_a.is_active)

        self._authorise_team_session(self.team_a)
        response = self.client.get(self._signout_url(self.team_a))
        self.assertEqual(response.status_code, 405)

        response = self.client.post(self._signout_url(self.team_a))
        self.assertEqual(response.status_code, 302)
        self.signin_a.refresh_from_db()
        self.assertFalse(self.signin_a.is_active)

    def test_signout_rejects_missing_csrf_token_and_accepts_dashboard_form_token(self):
        csrf_client = Client(enforce_csrf_checks=True)
        session = csrf_client.session
        session["team_id"] = self.team_a.pk
        session["team_name"] = self.team_a.name
        session.save()

        response = csrf_client.post(self._signout_url(self.team_a))
        self.assertEqual(response.status_code, 403)
        self.signin_a.refresh_from_db()
        self.assertTrue(self.signin_a.is_active)

        response = csrf_client.get(self._dashboard_url(self.team_a))
        self.assertEqual(response.status_code, 200)
        token = response.cookies["csrftoken"].value
        response = csrf_client.post(
            self._signout_url(self.team_a),
            HTTP_X_CSRFTOKEN=token,
        )
        self.assertEqual(response.status_code, 302)
        self.signin_a.refresh_from_db()
        self.assertFalse(self.signin_a.is_active)

    def test_staff_retains_explicit_operational_override(self):
        User = get_user_model()
        staff = User.objects.create_user(
            username="signin-staff",
            password="test-password",
            is_staff=True,
        )
        self.client.force_login(staff)
        response = self.client.get(self._dashboard_url(self.team_a))
        self.assertEqual(response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
