import json
from datetime import timedelta

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from friendly_games.models import PlayerCodename
from matches.models import LiveScoreboard, Match, MatchPlayer
from teams.models import Player, Team
from tournaments.models import Tournament

from .services import BROWSER_DELEGATIONS_SESSION_KEY
from .models import MatchTrackingSession


class MatchTrackingBrowserDelegationTests(TestCase):
    def setUp(self):
        now = timezone.now()
        self.tournament = Tournament.objects.create(
            name="Tracking Delegation Test",
            play_format="doublets",
            start_date=now,
            end_date=now + timedelta(hours=2),
        )
        self.team1 = Team.objects.create(name="Tracking North", pin="771001")
        self.team2 = Team.objects.create(name="Tracking South", pin="771002")
        self.player1 = Player.objects.create(name="Tracking Player One", team=self.team1)
        self.player2 = Player.objects.create(name="Tracking Player Two", team=self.team2)
        self.codename1 = PlayerCodename.objects.create(player=self.player1, codename="TRACK01")
        self.codename2 = PlayerCodename.objects.create(player=self.player2, codename="TRACK02")
        self.match = Match.objects.create(
            tournament=self.tournament,
            team1=self.team1,
            team2=self.team2,
            status="active",
        )
        MatchPlayer.objects.create(match=self.match, player=self.player1, team=self.team1)
        MatchPlayer.objects.create(match=self.match, player=self.player2, team=self.team2)
        self.scoreboard, _ = LiveScoreboard.objects.get_or_create(tournament_match=self.match)

    def _authorize_with_qr(self, client, player, codename):
        session = client.session
        session["qr_resolved_codename"] = codename
        session.save()
        response = client.post(
            reverse("match_tracking:verify_participant", args=["match", self.match.id]),
            data=json.dumps({"player_id": player.id}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        return response

    def test_qr_delegation_survives_reload_and_allows_shots_and_score(self):
        self._authorize_with_qr(self.client, self.player1, self.codename1.codename)

        page = self.client.get(
            reverse("match_tracking:tracking_page", args=["match", self.match.id])
        )
        self.assertEqual(page.status_code, 200)
        restored = json.loads(page.context["browser_authorizations_json"])
        self.assertEqual([item["player_id"] for item in restored], [self.player1.id])

        shot = self.client.post(
            reverse("match_tracking:record_shot", args=["match", self.match.id]),
            data=json.dumps({"player_id": self.player1.id, "outcome": "hit"}),
            content_type="application/json",
        )
        self.assertEqual(shot.status_code, 200)
        self.assertTrue(shot.json()["ok"])

        score = self.client.post(
            reverse("update_scoreboard", args=[self.scoreboard.id]),
            data=json.dumps({"team1_score": 1, "team2_score": 0, "tracking_delegated": True}),
            content_type="application/json",
        )
        self.assertEqual(score.status_code, 200)
        self.assertTrue(score.json()["success"])
        self.assertEqual(score.json()["last_updated_by"], self.codename1.codename)

    def test_second_browser_does_not_inherit_database_authorization(self):
        self._authorize_with_qr(self.client, self.player1, self.codename1.codename)

        other = Client()
        page = other.get(
            reverse("match_tracking:tracking_page", args=["match", self.match.id])
        )
        self.assertEqual(page.status_code, 200)
        self.assertEqual(json.loads(page.context["browser_authorizations_json"]), [])

        shot = other.post(
            reverse("match_tracking:record_shot", args=["match", self.match.id]),
            data=json.dumps({"player_id": self.player1.id, "outcome": "hit"}),
            content_type="application/json",
        )
        self.assertEqual(shot.status_code, 403)

        score = other.post(
            reverse("update_scoreboard", args=[self.scoreboard.id]),
            data=json.dumps({"team1_score": 1, "team2_score": 0, "tracking_delegated": True}),
            content_type="application/json",
        )
        self.assertEqual(score.status_code, 403)

    def test_first_authorized_player_remains_delegated_score_actor(self):
        self._authorize_with_qr(self.client, self.player1, self.codename1.codename)
        self._authorize_with_qr(self.client, self.player2, self.codename2.codename)

        page = self.client.get(
            reverse("match_tracking:tracking_page", args=["match", self.match.id])
        )
        restored = json.loads(page.context["browser_authorizations_json"])
        self.assertEqual(
            [item["player_id"] for item in restored],
            [self.player1.id, self.player2.id],
        )

        score = self.client.post(
            reverse("update_scoreboard", args=[self.scoreboard.id]),
            data=json.dumps({
                "team1_score": 1,
                "team2_score": 0,
                "codename": self.codename2.codename,
                "tracking_delegated": True,
            }),
            content_type="application/json",
        )
        self.assertEqual(score.status_code, 200)
        self.assertEqual(score.json()["last_updated_by"], self.codename1.codename)

    def test_normal_score_page_keeps_existing_session_identity_even_with_tracking_delegation(self):
        self._authorize_with_qr(self.client, self.player1, self.codename1.codename)

        session = self.client.session
        session["player_codename"] = self.codename2.codename
        session.save()

        score = self.client.post(
            reverse("update_scoreboard", args=[self.scoreboard.id]),
            data=json.dumps({
                "team1_score": 0,
                "team2_score": 1,
                "codename": "UNTRUSTED",
            }),
            content_type="application/json",
        )
        self.assertEqual(score.status_code, 200)
        self.assertTrue(score.json()["success"])
        self.assertEqual(score.json()["last_updated_by"], self.codename2.codename)

    def test_old_manual_end_route_cannot_stop_any_players_tracking(self):
        self._authorize_with_qr(self.client, self.player1, self.codename1.codename)
        other = Client()
        self._authorize_with_qr(other, self.player2, self.codename2.codename)

        session = MatchTrackingSession.objects.get(
            match_type="match", match_pk=self.match.pk, status="active"
        )
        response = self.client.post(
            reverse("match_tracking:end_tracking_session", args=["match", self.match.id]),
            data="{}", content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)
        session.refresh_from_db()
        self.assertEqual(session.status, "active")
        self.assertTrue(session.authorizations.filter(player=self.player1, is_active=True).exists())
        self.assertTrue(session.authorizations.filter(player=self.player2, is_active=True).exists())

        shot = other.post(
            reverse("match_tracking:record_shot", args=["match", self.match.id]),
            data=json.dumps({"player_id": self.player2.id, "outcome": "hit"}),
            content_type="application/json",
        )
        self.assertEqual(shot.status_code, 200)

    def test_result_pending_validation_pauses_but_does_not_end_tracking(self):
        self._authorize_with_qr(self.client, self.player1, self.codename1.codename)
        session = MatchTrackingSession.objects.get(
            match_type="match", match_pk=self.match.pk, status="active"
        )
        Match.objects.filter(pk=self.match.pk).update(status="waiting_validation")
        status_url = reverse("match_tracking:game_status_api", args=["match", self.match.id])
        response = self.client.get(status_url)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["tracking_active"])
        session.refresh_from_db()
        self.assertEqual(session.status, "active")
        self.assertTrue(session.authorizations.filter(player=self.player1, is_active=True).exists())

        paused_shot = self.client.post(
            reverse("match_tracking:record_shot", args=["match", self.match.id]),
            data=json.dumps({"player_id": self.player1.id, "outcome": "hit"}),
            content_type="application/json",
        )
        self.assertEqual(paused_shot.status_code, 403)
        session.refresh_from_db()
        self.assertEqual(session.status, "active")

        Match.objects.filter(pk=self.match.pk).update(status="active")
        resumed = self.client.post(
            reverse("match_tracking:record_shot", args=["match", self.match.id]),
            data=json.dumps({"player_id": self.player1.id, "outcome": "hit"}),
            content_type="application/json",
        )
        self.assertEqual(resumed.status_code, 200)
        self.assertEqual(MatchTrackingSession.objects.filter(
            match_type="match", match_pk=self.match.pk
        ).count(), 1)

        Match.objects.filter(pk=self.match.pk).update(status="completed")
        ended = self.client.get(status_url)
        self.assertEqual(ended.status_code, 200)
        session.refresh_from_db()
        self.assertEqual(session.status, "ended")
        self.assertFalse(session.authorizations.filter(is_active=True).exists())

    def test_completed_match_is_read_only_and_no_manual_end_button(self):
        self._authorize_with_qr(self.client, self.player1, self.codename1.codename)
        response = self.client.get(
            reverse("match_tracking:tracking_page", args=["match", self.match.id])
        )
        self.assertNotContains(response, 'id="btn-end-session"')
