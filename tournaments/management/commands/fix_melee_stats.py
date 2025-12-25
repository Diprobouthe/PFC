"""
Management command to initialize/fix mêlée player stats for all tournaments.
Usage: python manage.py fix_melee_stats
"""
from django.core.management.base import BaseCommand
from tournaments.models import Tournament
from tournaments.partnership_models import MeleePlayerStats
from tournaments.melee_stats_updater import initialize_melee_player_stats, recalculate_all_melee_stats


class Command(BaseCommand):
    help = 'Initialize and fix mêlée player stats for all mêlée tournaments'

    def add_arguments(self, parser):
        parser.add_argument(
            '--tournament-id',
            type=int,
            help='Fix specific tournament by ID',
        )
        parser.add_argument(
            '--recalculate',
            action='store_true',
            help='Recalculate stats from completed matches',
        )

    def handle(self, *args, **options):
        tournament_id = options.get('tournament_id')
        recalculate = options.get('recalculate', False)
        
        # Get tournaments to process
        if tournament_id:
            tournaments = Tournament.objects.filter(id=tournament_id, is_melee=True)
            if not tournaments.exists():
                self.stdout.write(self.style.ERROR(
                    f'Tournament {tournament_id} not found or is not a mêlée tournament'
                ))
                return
        else:
            tournaments = Tournament.objects.filter(is_melee=True)
        
        total_tournaments = tournaments.count()
        self.stdout.write(f'Found {total_tournaments} mêlée tournament(s) to process\n')
        
        fixed_count = 0
        already_ok_count = 0
        
        for tournament in tournaments:
            self.stdout.write(f'Processing: {tournament.name} (ID: {tournament.id})')
            
            # Check if stats exist
            stats_count = MeleePlayerStats.objects.filter(tournament=tournament).count()
            players_count = tournament.melee_players.count()
            
            if stats_count == 0:
                # No stats at all - initialize
                self.stdout.write(f'  No stats found. Initializing for {players_count} players...')
                result = initialize_melee_player_stats(tournament)
                self.stdout.write(self.style.SUCCESS(f'  ✓ Initialized {result} player stats'))
                fixed_count += 1
            elif stats_count < players_count:
                # Some stats missing - reinitialize
                self.stdout.write(f'  Incomplete stats ({stats_count}/{players_count}). Re-initializing...')
                result = initialize_melee_player_stats(tournament)
                self.stdout.write(self.style.SUCCESS(f'  ✓ Re-initialized {result} player stats'))
                fixed_count += 1
            else:
                self.stdout.write(f'  ✓ Stats already exist ({stats_count} players)')
                already_ok_count += 1
            
            # Recalculate if requested
            if recalculate:
                self.stdout.write(f'  Recalculating stats from completed matches...')
                recalculate_all_melee_stats(tournament)
                self.stdout.write(self.style.SUCCESS(f'  ✓ Stats recalculated'))
            
            self.stdout.write('')  # Blank line
        
        # Summary
        self.stdout.write(self.style.SUCCESS('\n=== Summary ==='))
        self.stdout.write(f'Total tournaments processed: {total_tournaments}')
        self.stdout.write(self.style.SUCCESS(f'Fixed/initialized: {fixed_count}'))
        self.stdout.write(f'Already OK: {already_ok_count}')
        
        if recalculate:
            self.stdout.write(self.style.SUCCESS('Stats recalculated from completed matches'))
        
        self.stdout.write(self.style.SUCCESS('\n✓ All done!'))
