from datetime import date, timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from courts.models import Court, CourtComplex
from simple_creator.models import ScenarioTournamentSequence, TournamentScenario
from simple_creator.tournament_naming import allocate_scenario_tournament_title
from tournaments.models import Tournament


class ScenarioTournamentNamingTests(TestCase):
    def setUp(self):
        complex_ = CourtComplex.objects.create(
            name='Scenario naming test complex',
            description='Synthetic fixture only.',
        )
        self.scenario = TournamentScenario.objects.create(
            name='scenario-naming-fixture',
            display_name='Scenario Naming Fixture',
            description='Synthetic fixture only.',
            default_court_complex=complex_,
            tournament_type='swiss',
            draft_type='snake',
        )

    def test_allocations_increment_per_scenario_and_title_date(self):
        event_date = date(2026, 9, 19)

        first = allocate_scenario_tournament_title(
            scenario=self.scenario,
            event_date=event_date,
            display_name=self.scenario.display_name,
        )
        second = allocate_scenario_tournament_title(
            scenario=self.scenario,
            event_date=event_date,
            display_name=self.scenario.display_name,
        )

        self.assertEqual(first, 'Scenario Naming Fixture — 2026-09-19 #1')
        self.assertEqual(second, 'Scenario Naming Fixture — 2026-09-19 #2')
        self.assertEqual(
            ScenarioTournamentSequence.objects.get(
                scenario=self.scenario,
                event_date=event_date,
            ).last_sequence,
            2,
        )

    def test_allocations_reset_for_a_new_printed_date(self):
        first_date = date(2026, 9, 19)
        second_date = date(2026, 9, 20)

        allocate_scenario_tournament_title(
            scenario=self.scenario,
            event_date=first_date,
            display_name=self.scenario.display_name,
        )
        next_day = allocate_scenario_tournament_title(
            scenario=self.scenario,
            event_date=second_date,
            display_name=self.scenario.display_name,
        )

        self.assertEqual(next_day, 'Scenario Naming Fixture — 2026-09-20 #1')

    def test_sequence_is_independent_for_each_scenario(self):
        other_complex = CourtComplex.objects.create(
            name='Second scenario naming test complex',
            description='Synthetic fixture only.',
        )
        other = TournamentScenario.objects.create(
            name='second-scenario-naming-fixture',
            display_name='Second Scenario Fixture',
            description='Synthetic fixture only.',
            default_court_complex=other_complex,
            tournament_type='swiss',
            draft_type='snake',
        )
        event_date = date(2026, 9, 19)

        allocate_scenario_tournament_title(
            scenario=self.scenario,
            event_date=event_date,
            display_name=self.scenario.display_name,
        )
        other_title = allocate_scenario_tournament_title(
            scenario=other,
            event_date=event_date,
            display_name=other.display_name,
        )

        self.assertEqual(other_title, 'Second Scenario Fixture — 2026-09-19 #1')

    def test_live_creator_uses_the_persisted_scenario_date_sequence(self):
        court = Court.objects.create(number=94001, is_available=True)
        self.scenario.default_court_complex.courts.add(court)
        self.scenario.is_free = True
        self.scenario.max_courts = 1
        self.scenario.save(update_fields=['is_free', 'max_courts'])

        for expected_sequence in (1, 2):
            response = self.client.post(
                reverse('create_simple_tournament'),
                {
                    'scenario': self.scenario.name,
                    'format': 'doubles',
                    'num_courts': '1',
                },
            )
            self.assertEqual(response.status_code, 302)

            printed_date = timezone.now().date() + timedelta(days=1)
            self.assertTrue(
                Tournament.objects.filter(
                    name=(
                        f'Scenario Naming Fixture — '
                        f'{printed_date.isoformat()} #{expected_sequence}'
                    )
                ).exists()
            )
