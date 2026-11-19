"""Regression checks for corrected PFC player profile tab bindings."""
from pathlib import Path

from django.template.loader import get_template
from django.test import SimpleTestCase


class PlayerProfileTabBindingTests(SimpleTestCase):
    ROOT = Path(__file__).resolve().parent

    def test_profile_template_compiles_and_binds_existing_stats_keys(self):
        get_template('teams/player_profile.html')
        template = (self.ROOT / 'templates/teams/player_profile.html').read_text(encoding='utf-8')
        self.assertIn('accurate_stats.matches_lost|default:0', template)
        self.assertIn('friendly_stats.win_rate|default:0|floatformat:1', template)
        self.assertNotIn('friendly_stats.win_percentage', template)
        self.assertNotIn('accurate_stats.matches_played|default:0|add:"-"', template)

    def test_tabs_are_single_row_and_the_derived_loss_count_is_in_view(self):
        template = (self.ROOT / 'templates/teams/player_profile.html').read_text(encoding='utf-8')
        view = (self.ROOT / 'views.py').read_text(encoding='utf-8')
        self.assertIn('flex-wrap: nowrap !important', template)
        self.assertIn('overflow-x: auto !important', template)
        self.assertIn("accurate_stats['matches_lost'] = max(", view)
