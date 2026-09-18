from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from teams.models import Team


class TeamPinAuthorizationTests(TestCase):
    def setUp(self):
        self.team_a = Team.objects.create(name="PIN Team A", pin="333333")
        self.team_b = Team.objects.create(name="PIN Team B", pin="444444")

    def _url(self, team):
        return reverse("show_team_pin", kwargs={"team_id": team.pk})

    def _set_team_session(self, team):
        session = self.client.session
        session["team_id"] = team.pk
        session["team_name"] = team.name
        session.save()

    def test_ordinary_authenticated_user_cannot_view_another_team_pin(self):
        User = get_user_model()
        user = User.objects.create_user(username="ordinary-user", password="test-password")
        self.client.force_login(user)
        response = self.client.get(self._url(self.team_a))
        self.assertEqual(response.status_code, 403)

    def test_target_team_session_can_view_its_own_pin_but_not_another_team_pin(self):
        self._set_team_session(self.team_a)
        response = self.client.get(self._url(self.team_a))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.team_a.pin)

        response = self.client.get(self._url(self.team_b))
        self.assertEqual(response.status_code, 403)

    def test_scoped_post_creation_grant_only_allows_the_created_team_once(self):
        session = self.client.session
        session["player_id"] = 42
        session["team_created"] = {
            "team_id": self.team_a.pk,
            "team_name": self.team_a.name,
            "player_id": 42,
        }
        session.save()

        response = self.client.get(self._url(self.team_a))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.team_a.pin)
        self.assertNotIn("team_created", self.client.session)

        session = self.client.session
        session["player_id"] = 42
        session["team_created"] = {
            "team_id": self.team_a.pk,
            "team_name": self.team_a.name,
            "player_id": 42,
        }
        session.save()
        response = self.client.get(self._url(self.team_b))
        self.assertEqual(response.status_code, 403)

    def test_staff_can_view_team_pin_without_team_session(self):
        User = get_user_model()
        staff = User.objects.create_user(
            username="pin-staff",
            password="test-password",
            is_staff=True,
        )
        self.client.force_login(staff)
        response = self.client.get(self._url(self.team_a))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.team_a.pin)
