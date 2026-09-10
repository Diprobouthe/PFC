from pathlib import Path

from django.template.loader import get_template
from django.test import SimpleTestCase

from practice.templatetags.practice_display import percentage_of


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class PracticeTemplatePresentationTests(SimpleTestCase):
    def test_practice_home_compiles_and_keeps_existing_mode_routes(self):
        get_template("practice/practice_home.html")
        source = (PROJECT_ROOT / "practice" / "templates" / "practice" / "practice_home.html").read_text()
        self.assertIn("{% url 'practice:shooting_practice' %}", source)
        self.assertIn("{% url 'practice:pointing_practice' %}", source)
        self.assertIn("Start Shooting", source)
        self.assertIn("Start Pointing", source)

    def test_pointing_template_compiles_and_preserves_existing_control_contract(self):
        get_template("practice/pointing_practice.html")
        source = (PROJECT_ROOT / "practice" / "templates" / "practice" / "pointing_practice.html").read_text()
        for control_id in (
            "startSessionBtn",
            "perfectBtn",
            "goodBtn",
            "fairBtn",
            "farBtn",
            "undoBtn",
            "endSessionBtn",
            "totalShots",
            "successPercentage",
            "perfectCount",
            "goodCount",
            "fairCount",
            "farCount",
            "currentStreak",
            "shotHistory",
        ):
            self.assertIn(f'id="{control_id}"', source)
        for endpoint in ("practice:start_session", "practice:record_shot", "practice:undo_shot", "practice:end_session"):
            self.assertIn(endpoint, source)
        self.assertIn("pointing-outcome-grid", source)
        self.assertIn("Success Rate", source)
        self.assertIn("stats.success_percentage ?? stats.hit_percentage ?? 0", source)
        self.assertIn("button.classList.add('is-recording')", source)
        self.assertIn("btn.classList.toggle('is-pending'", source)
        self.assertIn(".shot-btn.is-recording", source)

    def test_session_summary_compiles_and_keeps_shooting_and_pointing_data_contract(self):
        get_template("practice/session_summary.html")
        source = (PROJECT_ROOT / "practice" / "templates" / "practice" / "session_summary.html").read_text()
        for value in (
            "summary.total_shots",
            "summary.hit_percentage",
            "summary.carreau_percentage",
            "summary.longest_streak",
            "summary.performance_note",
            "session.carreaux",
            "session.petit_carreaux",
            "session.hits",
            "session.misses",
            "session.perfects",
            "session.goods",
            "session.fairs",
            "session.fars",
            "shot.sequence_number",
        ):
            self.assertIn(value, source)
        for section in ("Performance Insights", "Shot Sequence", "summary-breakdown-grid", "summary-key-metrics", "summary-page"):
            self.assertIn(section, source)
        self.assertIn("{% url 'practice:shooting_practice' %}", source)
        self.assertIn("{% url 'practice:practice_home' %}", source)
        for percentage in (
            "session.perfects|percentage_of:summary.total_shots",
            "session.goods|percentage_of:summary.total_shots",
            "session.fairs|percentage_of:summary.total_shots",
            "session.fars|percentage_of:summary.total_shots",
        ):
            self.assertIn(percentage, source)
        self.assertIn("pointing-sequence-badge", source)
        self.assertIn("pointing-sequence-perfect", source)
        self.assertIn("pointing-sequence-good", source)
        self.assertIn("pointing-sequence-fair", source)
        self.assertIn("pointing-sequence-far", source)

    def test_read_only_percentage_formatter_returns_real_category_percentages(self):
        self.assertEqual(percentage_of(1, 13), "7.7")
        self.assertEqual(percentage_of(7, 13), "53.8")
        self.assertEqual(percentage_of(3, 13), "23.1")
        self.assertEqual(percentage_of(2, 13), "15.4")
        self.assertEqual(percentage_of(0, 0), "0.0")
