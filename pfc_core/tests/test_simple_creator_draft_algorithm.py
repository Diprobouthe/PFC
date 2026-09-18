from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from pfc_core.simple_creator import normalize_melee_draft_algorithm
from tournaments.models import Tournament


class SimpleCreatorDraftAlgorithmTests(TestCase):
    """Protect the live Scenario-to-Mêlée-generator token boundary."""

    def setUp(self):
        now = timezone.now()
        self.tournament = Tournament.objects.create(
            name='scenario live-start fixture',
            description='Focused Simple Creator algorithm fixture',
            start_date=now + timedelta(days=1),
            end_date=now + timedelta(days=1, hours=8),
            format='multi_stage',
            is_melee=True,
            is_active=True,
            melee_teams_generated=False,
            max_participants=12,
        )

    def _start_with_scenario_draft_type(self, draft_type):
        scenarios = {
            'scenario': {
                'name': 'Scenario',
                'draft_type': draft_type,
            }
        }
        with patch('pfc_core.simple_creator.get_available_scenarios', return_value=scenarios), patch.object(
            Tournament, 'generate_melee_teams', return_value=2
        ) as generate_melee_teams, patch.object(Tournament, 'generate_matches', return_value=1):
            response = self.client.post(
                reverse('start_tournament', kwargs={'tournament_id': self.tournament.id}),
            )

        self.assertEqual(response.status_code, 302)
        return generate_melee_teams

    def test_live_scenario_snake_uses_snake_draft_generator_path(self):
        generate_melee_teams = self._start_with_scenario_draft_type('snake')

        generate_melee_teams.assert_called_once_with('snake_draft')

    def test_live_scenario_balance_uses_balanced_generator_path(self):
        generate_melee_teams = self._start_with_scenario_draft_type('balance')

        generate_melee_teams.assert_called_once_with('balanced')

    def test_live_scenario_random_remains_random(self):
        generate_melee_teams = self._start_with_scenario_draft_type('random')

        generate_melee_teams.assert_called_once_with('random')

    def test_existing_canonical_generator_tokens_remain_supported_aliases(self):
        for draft_type, expected_algorithm in (
            ('snake_draft', 'snake_draft'),
            ('balanced', 'balanced'),
        ):
            with self.subTest(draft_type=draft_type):
                generate_melee_teams = self._start_with_scenario_draft_type(draft_type)
                generate_melee_teams.assert_called_once_with(expected_algorithm)

    def test_unknown_draft_type_warns_and_uses_historic_random_fallback(self):
        with self.assertLogs('pfc_core.simple_creator', level='WARNING') as logs:
            algorithm = normalize_melee_draft_algorithm('unexpected-mode')

        self.assertEqual(algorithm, 'random')
        self.assertIn('Unknown Simple Creator Mêlée draft type', logs.output[0])
