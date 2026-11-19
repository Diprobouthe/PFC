"""Opt-in sharing and cross-profile identity/privacy regressions."""
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from friendly_games.models import PlayerCodename
from practice.models import PracticeSession, Shot
from practice.public_profiles import public_practice_progress_for_player
from shooting.templatetags.shot_tracker_tags import shot_stats_summary
from teams.models import Player, PlayerProfile, Team


class PracticeSharingProfileTests(TestCase):
    def setUp(self):
        team = Team.objects.create(name="Practice opt-in test team", pin="984321")
        self.target = Player.objects.create(name="TARGET_PLAYER_PUBLIC", team=team)
        self.visitor = Player.objects.create(name="VISITOR_PLAYER_PRIVATE", team=team)
        self.target_profile, _ = PlayerProfile.objects.get_or_create(player=self.target)
        self.visitor_profile, _ = PlayerProfile.objects.get_or_create(player=self.visitor)
        PlayerCodename.objects.create(player=self.target, codename="TARGET")
        PlayerCodename.objects.create(player=self.visitor, codename="VIEWER")

        now = timezone.now()
        self.target_shoot = PracticeSession.objects.create(
            player_codename="TARGET", practice_type="shooting",
            is_active=False, ended_at=now,
        )
        for outcome in ("hit", "hit", "carreau", "miss"):
            Shot.objects.create(session=self.target_shoot, outcome=outcome)

        self.target_point = PracticeSession.objects.create(
            player_codename="TARGET", practice_type="pointing",
            is_active=False, ended_at=now,
        )
        for outcome in ("perfect", "good", "far", "fair"):
            Shot.objects.create(session=self.target_point, outcome=outcome)

        self.visitor_shoot = PracticeSession.objects.create(
            player_codename="VIEWER", practice_type="shooting",
            is_active=False, ended_at=now,
        )
        for outcome in ("hit", "carreau", "hit", "hit"):
            Shot.objects.create(session=self.visitor_shoot, outcome=outcome)

        # Neither special drills nor active sessions should alter public aggregates.
        specialty = PracticeSession.objects.create(
            player_codename="TARGET", practice_type="shooting",
            is_active=False, ended_at=now, drill_type="sequence",
        )
        for _ in range(8):
            Shot.objects.create(session=specialty, outcome="hit")
        active = PracticeSession.objects.create(
            player_codename="TARGET", practice_type="shooting", is_active=True,
        )
        for _ in range(6):
            Shot.objects.create(session=active, outcome="hit")

    def _login(self, codename):
        sess = self.client.session
        sess["player_codename"] = codename
        sess["session_active"] = True
        sess.save()

    def _profile(self):
        return self.client.get(reverse("player_profile", args=[self.target.pk]))

    def test_default_private_to_visitors_and_identity_fallback_absent(self):
        self.assertFalse(self.target_profile.share_practice_statistics)
        self._login("VIEWER")
        page = self._profile()
        self.assertEqual(page.status_code, 200)
        self.assertFalse(page.context["is_own_profile"])
        self.assertFalse(page.context["show_practice_tab"])
        self.assertIsNone(page.context["public_practice_progress"])
        self.assertNotContains(page, 'data-pp-tab="pp-shooting"')
        self.assertNotContains(page, "TARGET_PLAYER_PUBLIC · Shooting")
        self.assertNotContains(page, "VISITOR_PLAYER_PRIVATE · Shooting")
        self.assertNotContains(page, str(self.visitor_shoot.pk))
        # The inclusion tag itself is also fail-closed, even when called directly.
        self.assertEqual(
            shot_stats_summary({"player": self.target, "is_own_profile": False,
                                "request": page.wsgi_request}),
            {"has_stats": False},
        )

    def test_player_explicitly_opts_in_and_public_view_has_target_aggregates_only(self):
        self._login("TARGET")
        edit_url = reverse("edit_player_profile")
        page = self.client.get(edit_url)
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'name="share_practice_statistics"')
        self.assertNotContains(page, 'name="share_practice_statistics" class="form-check-input"\n               style="width:20px;height:20px;margin:0;"\n               checked')

        save = self.client.post(edit_url, {
            "action": "update_practice_sharing",
            "share_practice_statistics": "on",
        })
        self.assertEqual(save.status_code, 302)
        self.target_profile.refresh_from_db()
        self.assertTrue(self.target_profile.share_practice_statistics)
        self.assertFalse(self.visitor_profile.share_practice_statistics)

        self._login("VIEWER")
        page = self._profile()
        self.assertEqual(page.status_code, 200)
        self.assertFalse(page.context["is_own_profile"])
        self.assertTrue(page.context["show_practice_tab"])
        self.assertContains(page, 'data-pp-tab="pp-shooting"')
        self.assertContains(page, 'class="pp-public-practice-chart"', count=2)
        values = page.context["public_practice_progress"]
        self.assertEqual(values["shooting"]["mean"], 75.0)
        self.assertEqual(values["shooting"]["total_shots"], 4)
        self.assertEqual(values["pointing"]["mean"], 50.0)
        self.assertEqual(values["pointing"]["total_shots"], 4)
        self.assertNotContains(page, str(self.target_shoot.pk))
        self.assertNotContains(page, str(self.target_point.pk))
        self.assertNotContains(page, str(self.visitor_shoot.pk))
        self.assertNotContains(page, "Recent Sessions")
        self.assertNotContains(page, "Start Practice Session")
        self.assertNotContains(page, reverse("practice:session_summary", args=[self.target_shoot.pk]))

    def test_owner_can_access_own_private_tracker(self):
        self._login("TARGET")
        page = self._profile()
        self.assertEqual(page.status_code, 200)
        self.assertTrue(page.context["is_own_profile"])
        self.assertTrue(page.context["show_practice_tab"])
        self.assertContains(page, 'data-pp-tab="pp-shooting"')
        self.assertContains(page, "Open Practice")
        self.assertNotContains(page, 'class="pp-public-practice-chart"')

    def test_global_hide_statistics_overrides_opt_in_for_others(self):
        self.target_profile.share_practice_statistics = True
        self.target_profile.hide_public_statistics = True
        self.target_profile.save(update_fields=[
            "share_practice_statistics", "hide_public_statistics"
        ])
        self._login("VIEWER")
        page = self._profile()
        self.assertFalse(page.context["show_practice_tab"])
        self.assertIsNone(page.context["public_practice_progress"])
        self.assertNotContains(page, 'data-pp-tab="pp-shooting"')
        self._login("TARGET")
        owner = self._profile()
        self.assertTrue(owner.context["show_practice_tab"])

    def test_owner_can_revoke_sharing_immediately(self):
        self._login("TARGET")
        url = reverse("edit_player_profile")
        self.client.post(url, {
            "action": "update_practice_sharing",
            "share_practice_statistics": "on",
        })
        self.client.post(url, {"action": "update_practice_sharing"})
        self.target_profile.refresh_from_db()
        self.assertFalse(self.target_profile.share_practice_statistics)
        self._login("VIEWER")
        self.assertFalse(self._profile().context["show_practice_tab"])

    def test_unrelated_user_cannot_change_target_setting(self):
        self._login("VIEWER")
        self.client.post(reverse("edit_player_profile"), {
            "action": "update_practice_sharing", "share_practice_statistics": "on",
        })
        self.target_profile.refresh_from_db()
        self.visitor_profile.refresh_from_db()
        self.assertFalse(self.target_profile.share_practice_statistics)
        self.assertTrue(self.visitor_profile.share_practice_statistics)

    def test_codename_missing_fails_closed_without_viewer_fallback(self):
        self.target_profile.share_practice_statistics = True
        self.target_profile.save(update_fields=["share_practice_statistics"])
        PlayerCodename.objects.filter(player=self.target).delete()
        self._login("VIEWER")
        page = self._profile()
        self.assertTrue(page.context["show_practice_tab"])
        summary = page.context["public_practice_progress"]
        self.assertEqual(summary["shooting"]["count"], 0)
        self.assertEqual(summary["pointing"]["count"], 0)
        self.assertNotContains(page, str(self.visitor_shoot.pk))
        self.assertNotContains(page, "100,0%")
        self.assertNotContains(page, "100.0%")

    def test_public_helper_refuses_read_without_explicit_opt_in(self):
        self.assertIsNone(public_practice_progress_for_player(self.target))
        self.target_profile.share_practice_statistics = True
        self.target_profile.hide_public_statistics = True
        self.target_profile.save(update_fields=["share_practice_statistics", "hide_public_statistics"])
        self.assertIsNone(public_practice_progress_for_player(self.target))
