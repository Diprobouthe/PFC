"""Regression checks for longitudinal Practice History progress summary."""
from datetime import timedelta
from types import SimpleNamespace

from django.test import SimpleTestCase, TestCase
from django.template.loader import get_template
from django.urls import reverse
from unittest.mock import patch
from django.utils import timezone

from practice.history_progress import summarize_practice_progress
from practice.models import PracticeSession, Shot


def sample(kind, shots, successes, *, active=False, drill="", ended=True, distance="7m"):
    return SimpleNamespace(
        practice_type=kind,
        drill_type=drill,
        is_active=active,
        ended_at=timezone.now() if ended else None,
        total_shots=shots,
        successful_shots=successes,
        distance=distance,
    )


class PracticeProgressMathTests(SimpleTestCase):
    def test_weighted_mean_and_deviation_without_fake_improvement(self):
        # 1/1=100%, 0/9=0% => weighted mean 10%, not naive 50%.
        result = summarize_practice_progress([
            sample("shooting", 1, 1),
            sample("shooting", 9, 0),
        ])["shooting"]
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["mean"], 10.0)
        self.assertEqual(result["deviation"], 30.0)
        self.assertEqual(result["total_shots"], 10)
        self.assertIsNone(result["trend"])
        self.assertEqual(result["path"], "10.0,90.0 290.0,10.0")

    def test_special_drills_and_active_sessions_are_not_mixed_in(self):
        result = summarize_practice_progress([
            sample("shooting", 20, 20, drill="tir_de_precision"),
            sample("shooting", 10, 10, active=True),
            sample("shooting", 12, 12, ended=False),
            sample("shooting", 0, 0),
            sample("shooting", 4, 1),
            sample("pointing", 4, 3),
        ])
        self.assertEqual(result["shooting"]["count"], 1)
        self.assertEqual(result["shooting"]["mean"], 25.0)
        self.assertEqual(result["pointing"]["mean"], 75.0)

    def test_last_twelve_and_last_four_trend(self):
        # First four 25%, next four 75%, 4 recent 50% are selected in
        # reversed-newest order; trend is last four minus previous four.
        chronological = [sample("pointing", 4, 1) for _ in range(4)]
        chronological += [sample("pointing", 4, 3) for _ in range(4)]
        chronological += [sample("pointing", 4, 2) for _ in range(4)]
        result = summarize_practice_progress(list(reversed(chronological)))["pointing"]
        self.assertEqual(result["count"], 12)
        self.assertEqual(result["mean"], 50.0)
        self.assertEqual(result["trend"], -25.0)
        self.assertEqual(result["first"], 25.0)
        self.assertEqual(result["last"], 50.0)

    def test_ing_and_fixed_distance_are_distinct_observation_sources(self):
        from practice.history_progress import summarize_accuracy_views
        records = [
            sample("shooting", 0, 0, distance="ing"),      # not an accuracy observation
            sample("shooting", 4, 4, distance="ing"),      # InG: 100%
            sample("shooting", 4, 0, distance="8m"),       # training: real 0%
            sample("shooting", 10, 10, distance="ing", active=True),
            sample("pointing", 6, 3, distance="7m"),
            sample("pointing", 6, 6, distance="ing"),
        ]
        groups = summarize_accuracy_views(records)
        self.assertEqual(groups["all"]["shooting"]["count"], 2)
        self.assertEqual(groups["all"]["shooting"]["mean"], 50.0)
        self.assertEqual(groups["training"]["shooting"]["mean"], 0.0)
        self.assertEqual(groups["ing"]["shooting"]["mean"], 100.0)
        self.assertEqual(groups["training"]["shooting"]["count"], 1)
        self.assertEqual(groups["ing"]["shooting"]["count"], 1)
        self.assertEqual(groups["training"]["pointing"]["mean"], 50.0)
        self.assertEqual(groups["ing"]["pointing"]["mean"], 100.0)
        self.assertEqual(groups["all"]["shooting"]["total_shots"], 8)

    def test_empty_history_not_misrepresented_as_zero_performance(self):
        result = summarize_practice_progress([])
        self.assertEqual(result["shooting"]["count"], 0)
        self.assertNotIn("mean", result["shooting"])
        self.assertEqual(result["pointing"]["count"], 0)


class PracticeProgressRenderedTests(TestCase):
    def test_history_contains_both_charts_with_real_scored_data(self):
        now = timezone.now()
        pointing = PracticeSession.objects.create(
            player_codename="PROGRESS_OWNER", practice_type="pointing",
            is_active=False, ended_at=now,
        )
        for outcome in ("perfect", "good", "fair", "far"):
            Shot.objects.create(session=pointing, outcome=outcome)
        shooting = PracticeSession.objects.create(
            player_codename="PROGRESS_OWNER", practice_type="shooting",
            is_active=False, ended_at=now,
        )
        for outcome in ("hit", "hit", "miss", "carreau"):
            Shot.objects.create(session=shooting, outcome=outcome)
        session_context = {
            "player_logged_in": True,
            "session_codename": "PROGRESS_OWNER",
            "player_name": "Regression",
        }
        with patch("practice.views.SessionManager.get_session_context", return_value=session_context):
            response = self.client.get(reverse("practice:session_history"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="ph-trends"', count=3)
        self.assertContains(response, 'class="ph-trend-graph"', count=4)
        self.assertContains(response, 'data-accuracy-button="ing"')
        self.assertContains(response, 'data-accuracy-button="training"')
        self.assertEqual(response.context["progress"]["shooting"]["mean"], 75.0)
        self.assertEqual(response.context["progress"]["pointing"]["mean"], 50.0)
        self.assertContains(response, 'class="ph-trend-dot"', count=4)

    def test_history_zero_attempt_card_is_unmeasured_not_zero_percent(self):
        from unittest.mock import patch
        zero = PracticeSession.objects.create(
            player_codename="ZERO_TEST", practice_type="shooting",
            distance="ing", is_active=False, ended_at=timezone.now(),
        )
        context = {"player_logged_in": True, "session_codename": "ZERO_TEST",
                   "player_name": "Zero test"}
        with patch("practice.views.SessionManager.get_session_context", return_value=context):
            response = self.client.get(reverse("practice:session_history"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No shots yet")
        self.assertContains(response, "InG")
        self.assertEqual(response.context["progress"]["shooting"]["count"], 0)

    def test_template_compiles_and_retains_session_card_links(self):
        get_template("practice/session_history.html")
