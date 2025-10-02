from django.core.management.base import BaseCommand
from simple_creator.models import TournamentScenario


class Command(BaseCommand):
    help = 'Set up virtual courts configuration for existing tournament scenarios'

    def handle(self, *args, **options):
        scenarios = TournamentScenario.objects.all()
        
        # Default court configurations based on scenario type
        default_configs = {
            'swiss': {'max_courts': 4, 'recommended_courts': 3},
            'round_robin': {'max_courts': 6, 'recommended_courts': 4},
        }
        
        updated_count = 0
        
        for scenario in scenarios:
            # Skip if already configured
            if scenario.max_courts > 0:
                continue
                
            # Get default config based on tournament type
            config = default_configs.get(scenario.tournament_type, {'max_courts': 4, 'recommended_courts': 3})
            
            # Adjust based on player count
            if scenario.max_triples_players > 15:
                config['max_courts'] = min(config['max_courts'] + 2, 8)
                config['recommended_courts'] = min(config['recommended_courts'] + 1, 6)
            elif scenario.max_doubles_players > 10:
                config['max_courts'] = min(config['max_courts'] + 1, 6)
                config['recommended_courts'] = min(config['recommended_courts'] + 1, 4)
            
            # Update scenario
            scenario.max_courts = config['max_courts']
            scenario.recommended_courts = config['recommended_courts']
            scenario.save()
            
            updated_count += 1
            self.stdout.write(
                self.style.SUCCESS(
                    f'Updated {scenario.display_name}: max={config["max_courts"]}, recommended={config["recommended_courts"]}'
                )
            )
        
        self.stdout.write(
            self.style.SUCCESS(f'Successfully updated {updated_count} scenarios with virtual courts configuration')
        )

