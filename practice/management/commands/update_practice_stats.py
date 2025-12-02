"""
Management command to update practice statistics for all players.

This command recalculates aggregated statistics for all players who have
completed practice sessions. It's useful for maintenance and ensuring
data consistency.
"""

from django.core.management.base import BaseCommand
from django.db.models import Count
from practice.models import PracticeSession, PracticeStatistics


class Command(BaseCommand):
    help = 'Update practice statistics for all players'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--player',
            type=str,
            help='Update statistics for specific player codename only'
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force update even if statistics are up to date'
        )
    
    def handle(self, *args, **options):
        player_codename = options.get('player')
        force_update = options.get('force', False)
        
        if player_codename:
            # Update specific player
            self.update_player_stats(player_codename, force_update)
        else:
            # Update all players
            self.update_all_players_stats(force_update)
    
    def update_all_players_stats(self, force_update=False):
        """Update statistics for all players with completed sessions"""
        
        # Get all players with completed sessions
        players_with_sessions = PracticeSession.objects.filter(
            is_active=False
        ).values_list('player_codename', flat=True).distinct()
        
        total_players = len(players_with_sessions)
        
        if total_players == 0:
            self.stdout.write(
                self.style.WARNING('No players with completed sessions found.')
            )
            return
        
        self.stdout.write(f'Updating statistics for {total_players} players...')
        
        updated_count = 0
        for player_codename in players_with_sessions:
            if self.update_player_stats(player_codename, force_update, quiet=True):
                updated_count += 1
        
        self.stdout.write(
            self.style.SUCCESS(
                f'Successfully updated statistics for {updated_count}/{total_players} players.'
            )
        )
    
    def update_player_stats(self, player_codename, force_update=False, quiet=False):
        """Update statistics for a specific player"""
        
        # Check if player has completed sessions
        completed_sessions = PracticeSession.objects.filter(
            player_codename=player_codename,
            is_active=False
        )
        
        if not completed_sessions.exists():
            if not quiet:
                self.stdout.write(
                    self.style.WARNING(
                        f'No completed sessions found for player {player_codename}'
                    )
                )
            return False
        
        # Check if update is needed
        try:
            existing_stats = PracticeStatistics.objects.get(
                player_codename=player_codename
            )
            
            if not force_update:
                # Check if stats are up to date
                latest_session = completed_sessions.order_by('-ended_at').first()
                if existing_stats.last_updated >= latest_session.ended_at:
                    if not quiet:
                        self.stdout.write(
                            f'Statistics for {player_codename} are already up to date.'
                        )
                    return False
        
        except PracticeStatistics.DoesNotExist:
            existing_stats = None
        
        # Update statistics
        try:
            updated_stats = PracticeStatistics.update_for_player(player_codename)
            
            if updated_stats:
                if not quiet:
                    self.stdout.write(
                        self.style.SUCCESS(
                            f'Updated statistics for {player_codename}: '
                            f'{updated_stats.total_sessions} sessions, '
                            f'{updated_stats.total_shots} shots, '
                            f'{updated_stats.overall_hit_percentage:.1f}% hit rate'
                        )
                    )
                return True
            else:
                if not quiet:
                    self.stdout.write(
                        self.style.ERROR(
                            f'Failed to update statistics for {player_codename}'
                        )
                    )
                return False
        
        except Exception as e:
            if not quiet:
                self.stdout.write(
                    self.style.ERROR(
                        f'Error updating statistics for {player_codename}: {str(e)}'
                    )
                )
            return False
