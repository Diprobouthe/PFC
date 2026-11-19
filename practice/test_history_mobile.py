"""Focused regression coverage for the mobile-first PFC Practice History page."""
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from practice.models import PracticeSession, Shot


class PracticeHistoryMarkupTests(SimpleTestCase):
    def test_css_is_inside_a_block_the_real_base_renders(self):
        from django.template.loader import get_template
        get_template('practice/session_history.html')
        path = Path(__file__).resolve().parent / 'templates/practice/session_history.html'
        source = path.read_text(encoding='utf-8')
        self.assertIn('{% block content %}\n<style>', source)
        self.assertNotIn('{% block extra_css %}', source)
        for required in ('practice-history', 'ph-head', 'ph-item', 'ph-metrics',
                         'percentage_of:summary.total_shots', 'practice:session_summary',
                         'practice:practice_home'):
            self.assertIn(required, source)
        self.assertNotIn('session.perfect_percentage', source)
        self.assertNotIn('session.good_percentage', source)


class PracticeHistoryRenderedTests(TestCase):
    CODENAME = 'PFC_HISTORY_REGRESSION'

    def _get_history(self):
        context = {
            'player_logged_in': True,
            'session_codename': self.CODENAME,
            'player_name': 'History regression player',
        }
        with patch('practice.views.SessionManager.get_session_context', return_value=context):
            return self.client.get(reverse('practice:session_history'))

    def test_pointing_history_shows_real_percentages_and_readable_distance(self):
        session = PracticeSession.objects.create(
            player_codename=self.CODENAME, practice_type='pointing',
            distance='ing', is_active=False,
        )
        for outcome in ('perfect', 'good', 'fair', 'far'):
            Shot.objects.create(session=session, outcome=outcome)
        response = self._get_history()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'ph-metrics')
        self.assertContains(response, '50%')  # Two successes out of four
        self.assertContains(response, '25.0%', count=2)  # Perfect and Good separately
        self.assertContains(response, 'InG')
        self.assertContains(response, str(session.id))
        self.assertContains(response, '<style>', html=False)

    def test_shooting_history_shows_actual_accuracy_and_carreau(self):
        session = PracticeSession.objects.create(
            player_codename=self.CODENAME, practice_type='shooting',
            distance='7m', is_active=False,
        )
        for outcome in ('hit', 'carreau', 'miss'):
            Shot.objects.create(session=session, outcome=outcome)
        response = self._get_history()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '67%')  # 2/3 rounded for compact card
        self.assertContains(response, '33%')  # 1/3 carreau
        self.assertContains(response, '7 meters')

    def test_empty_history_keeps_navigation(self):
        response = self._get_history()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse('practice:practice_home'))
        self.assertContains(response, reverse('practice:shooting_practice'))
        self.assertContains(response, reverse('practice:pointing_practice'))

    def test_guest_cannot_see_history(self):
        with patch('practice.views.SessionManager.get_session_context',
                   return_value={'player_logged_in': False}):
            response = self.client.get(reverse('practice:session_history'))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('practice:practice_home'))
