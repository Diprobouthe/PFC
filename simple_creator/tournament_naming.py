"""Stable, concurrent-safe titles for Scenario-created Tournaments."""

from django.db import transaction


def allocate_scenario_tournament_title(*, scenario, event_date, display_name):
    """Allocate ``<Scenario> — <date> #<n>`` under the Scenario row lock.

    The Scenario lock is the serialization boundary for every date belonging to
    that Scenario. It makes both the counter creation and increment safe on
    PostgreSQL without inferring a sequence from mutable Tournament names.
    """
    from simple_creator.models import ScenarioTournamentSequence, TournamentScenario

    with transaction.atomic():
        locked_scenario = TournamentScenario.objects.select_for_update().get(pk=scenario.pk)
        sequence, _ = (
            ScenarioTournamentSequence.objects.select_for_update()
            .get_or_create(
                scenario=locked_scenario,
                event_date=event_date,
                defaults={'last_sequence': 0},
            )
        )
        sequence.last_sequence += 1
        sequence.save(update_fields=['last_sequence', 'updated_at'])

        suffix = f' — {event_date.isoformat()} #{sequence.last_sequence}'
        maximum_display_length = 100 - len(suffix)
        title_display_name = str(display_name).strip()[:maximum_display_length]
        if not title_display_name:
            raise ValueError('Scenario display name is required to allocate a tournament title.')
        return f'{title_display_name}{suffix}'
