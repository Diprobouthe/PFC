from pathlib import Path
from io import BytesIO
import json

from pypdf import PdfReader
from unittest.mock import patch

from django.template.loader import get_template
from django.test import RequestFactory, SimpleTestCase, TestCase

from practice.models import PracticeSession, Shot
from practice.utils import calculate_session_summary

from practice.templatetags.practice_display import percentage_of


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class PointingFairSemanticsTests(TestCase):
    def test_fair_and_far_are_unsuccessful_across_recorded_history_and_streaks(self):
        session = PracticeSession.objects.create(player_codename='POINTING_FAIR_TEST', practice_type='pointing')
        for outcome in ('perfect', 'good', 'fair', 'far', 'good'):
            Shot.objects.create(session=session, outcome=outcome)
        session.refresh_from_db()
        self.assertEqual(session.total_shots, 5)
        self.assertEqual(session.successful_shots, 3)
        self.assertEqual(session.hit_percentage, 60.0)
        summary = calculate_session_summary(session)
        self.assertEqual(summary['hit_percentage'], 60.0)
        self.assertEqual(summary['longest_streak'], 2)  # Fair breaks the positive streak.
        self.assertEqual(summary['first_miss_position'], 3)

    def test_historical_petit_perfect_is_still_successful(self):
        session = PracticeSession.objects.create(player_codename='LEGACY_POINTING', practice_type='pointing')
        for outcome in ('petit_perfect', 'fair', 'far'):
            Shot.objects.create(session=session, outcome=outcome)
        session.refresh_from_db()
        self.assertAlmostEqual(session.hit_percentage, 100 / 3)
        self.assertEqual(calculate_session_summary(session)['hit_percentage'], 33.3)

    def test_pointing_undo_returns_all_category_counts_and_fair_as_failure(self):
        from practice.views import undo_last_shot
        session = PracticeSession.objects.create(player_codename='UNDO_POINTING', practice_type='pointing')
        for outcome in ('perfect', 'good', 'fair', 'far'):
            Shot.objects.create(session=session, outcome=outcome)
        request = RequestFactory().post('/practice/api/undo-shot/')
        with patch('practice.views.CodenameSessionManager.is_logged_in', return_value=True), \
             patch('practice.views.CodenameSessionManager.get_logged_in_codename', return_value='UNDO_POINTING'):
            response = undo_last_shot(request)
        self.assertEqual(response.status_code, 200)
        stats = json.loads(response.content)['session_stats']
        self.assertEqual(stats['total_shots'], 3)
        self.assertEqual(stats['perfects'], 1)
        self.assertEqual(stats['goods'], 1)
        self.assertEqual(stats['fairs'], 1)
        self.assertEqual(stats['fars'], 0)
        self.assertEqual(stats['success_percentage'], 66.7)
        self.assertEqual(stats['current_streak'], 0)

    def test_shooting_accuracy_unchanged(self):
        session = PracticeSession.objects.create(player_codename='SHOOTING_FAIR_TEST', practice_type='shooting')
        for outcome in ('hit', 'petit_carreau', 'carreau', 'miss'):
            Shot.objects.create(session=session, outcome=outcome)
        session.refresh_from_db()
        self.assertEqual(session.hit_percentage, 75.0)
        self.assertEqual(calculate_session_summary(session)['longest_streak'], 3)


class PracticePdfShareTests(TestCase):
    def setUp(self):
        from django.urls import reverse
        self.session = PracticeSession.objects.create(
            player_codename='SHAREPDF', practice_type='pointing',
            distance='7m', sequence_tracking=True, is_active=False,
        )
        for outcome in ('perfect', 'good', 'fair', 'far'):
            Shot.objects.create(session=self.session, outcome=outcome)
        self.url = reverse('practice:session_summary_pdf', args=[self.session.id])

    def get_as_owner(self):
        with patch('practice.views.CodenameSessionManager.is_logged_in', return_value=True), \
             patch('practice.views.CodenameSessionManager.get_logged_in_codename', return_value='SHAREPDF'):
            return self.client.get(self.url)

    def test_download_is_a_real_pdf_with_all_shots_in_recorded_order(self):
        response = self.get_as_owner()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertIn('attachment;', response['Content-Disposition'])
        self.assertEqual(response['Cache-Control'], 'private, no-store')
        self.assertTrue(response.content.startswith(b'%PDF'))
        extracted = ' '.join(
            ' '.join((page.extract_text() or '').split())
            for page in PdfReader(BytesIO(response.content)).pages
        )
        self.assertIn('PFC - Practice Summary', extracted)
        self.assertIn('50.0%', extracted)  # Fair and Far are unsuccessful.
        self.assertIn('Recorded shot sequence', extracted)
        for label in ('#1 Perfect', '#2 Good', '#3 Fair', '#4 Far'):
            self.assertIn(label, extracted)
        self.assertLess(extracted.index('#1 Perfect'), extracted.index('#2 Good'))
        self.assertLess(extracted.index('#2 Good'), extracted.index('#3 Fair'))
        self.assertLess(extracted.index('#3 Fair'), extracted.index('#4 Far'))
        self.assertNotIn('SHAREPDF', extracted)  # Never disclose the login codename in a shared PDF.

    def test_cannot_export_someone_elses_training(self):
        with patch('practice.views.CodenameSessionManager.is_logged_in', return_value=True), \
             patch('practice.views.CodenameSessionManager.get_logged_in_codename', return_value='SOMEONE'):
            response = self.client.get(self.url)
        self.assertEqual(response.status_code, 403)

    def test_unauthenticated_export_is_rejected(self):
        with patch('practice.views.CodenameSessionManager.is_logged_in', return_value=False):
            response = self.client.get(self.url)
        self.assertEqual(response.status_code, 403)

    def test_print_and_mobile_pdf_sharing_controls_exist(self):
        from django.template.loader import get_template
        get_template('practice/session_summary.html')
        source = (PROJECT_ROOT / 'practice/templates/practice/session_summary.html').read_text()
        self.assertIn('practice:session_summary_pdf', source)
        self.assertIn('id="sharePracticePdf"', source)
        self.assertIn('id="downloadPracticePdf"', source)
        self.assertIn('navigator.share({ files: [pdfFile]', source)
        self.assertIn('navigator.canShare({ files: [pdfFile] })', source)
        self.assertIn('downloadLink.click()', source)
        self.assertIn('window.print()', source)  # Existing print action is untouched.

    def test_sequence_off_is_disclosed_in_pdf(self):
        self.session.sequence_tracking = False
        self.session.save(update_fields=['sequence_tracking'])
        extracted = ' '.join(
            ' '.join((page.extract_text() or '').split())
            for page in PdfReader(BytesIO(self.get_as_owner().content)).pages
        )
        self.assertIn('Sequence tracking was OFF', extracted)


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
        self.assertIn('Fair (unsuccessful)', source)

    def test_read_only_percentage_formatter_returns_real_category_percentages(self):
        self.assertEqual(percentage_of(1, 13), "7.7")
        self.assertEqual(percentage_of(7, 13), "53.8")
        self.assertEqual(percentage_of(3, 13), "23.1")
        self.assertEqual(percentage_of(2, 13), "15.4")
        self.assertEqual(percentage_of(0, 0), "0.0")
