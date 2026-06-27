from django.core.management.base import BaseCommand
from django.utils import timezone
from simple_creator.models import SimpleTournament
from tournaments.models import Tournament
from teams.models import Team


class Command(BaseCommand):
    help = 'Automatically cleanup completed simple tournaments'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be cleaned up without actually doing it'
        )
        
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force cleanup even if tournament is not marked as complete'
        )
    
    def handle(self, *args, **options):
        dry_run = options['dry_run']
        force = options['force']
        
        self.stdout.write('🧹 Starting automatic tournament cleanup...')
        
        # Find completed tournaments that need cleanup
        if force:
            tournaments = SimpleTournament.objects.filter(
                players_restored=False
            )
            self.stdout.write(f'🔍 Found {tournaments.count()} tournaments (force mode)')
        else:
            tournaments = SimpleTournament.objects.filter(
                is_completed=False
            )
            # Check which ones are actually complete
            completed_tournaments = []
            for tournament in tournaments:
                if tournament.tournament.is_tournament_complete():
                    completed_tournaments.append(tournament)
                    if not dry_run:
                        tournament.is_completed = True
                        tournament.save()
            
            tournaments = completed_tournaments
            self.stdout.write(f'🔍 Found {len(tournaments)} completed tournaments needing cleanup')
        
        if not tournaments:
            self.stdout.write(self.style.SUCCESS('✅ No tournaments need cleanup'))
            return
        
        cleanup_count = 0
        for simple_tournament in tournaments:
            self.stdout.write(f'\n🎯 Processing: {simple_tournament.tournament.name}')
            
            try:
                if dry_run:
                    self._dry_run_cleanup(simple_tournament)
                else:
                    self._perform_cleanup(simple_tournament)
                    cleanup_count += 1
                    
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f'❌ Error cleaning up {simple_tournament.tournament.name}: {e}')
                )
        
        if dry_run:
            self.stdout.write(
                self.style.WARNING(f'\n🔍 DRY RUN: Would have cleaned up {len(tournaments)} tournaments')
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(f'\n🎉 Successfully cleaned up {cleanup_count} tournaments!')
            )
    
    def _dry_run_cleanup(self, simple_tournament):
        """Show what would be cleaned up without actually doing it"""
        tournament = simple_tournament.tournament
        
        # Check badges
        if not simple_tournament.badges_assigned:
            self.stdout.write('  📋 Would assign badges (if system supports it)')
        
        # Check player restoration
        if not simple_tournament.players_restored:
            mele_players = tournament.meleeplayer_set.all()
            if mele_players.exists():
                self.stdout.write(f'  👥 Would restore {mele_players.count()} players to original teams')
                for mp in mele_players[:3]:  # Show first 3 as example
                    if mp.original_team:
                        self.stdout.write(f'    - {mp.player.name} → {mp.original_team.name}')
                if mele_players.count() > 3:
                    self.stdout.write(f'    ... and {mele_players.count() - 3} more')
            else:
                self.stdout.write('  👥 No mêlée players to restore')
        
        # Check team deletion
        if not simple_tournament.mele_teams_deleted:
            mele_teams = tournament.teams.filter(name__startswith='Mêlée Team')
            empty_teams = [team for team in mele_teams if team.players.count() == 0]
            if empty_teams:
                self.stdout.write(f'  🗑️  Would delete {len(empty_teams)} empty mêlée teams')
                for team in empty_teams[:3]:  # Show first 3 as example
                    self.stdout.write(f'    - {team.name}')
                if len(empty_teams) > 3:
                    self.stdout.write(f'    ... and {len(empty_teams) - 3} more')
            else:
                self.stdout.write('  🗑️  No empty mêlée teams to delete')
    
    def _perform_cleanup(self, simple_tournament):
        """Actually perform the cleanup"""
        tournament = simple_tournament.tournament
        
        # Assign badges (placeholder for future implementation)
        if not simple_tournament.badges_assigned:
            # TODO: Implement badge assignment when system supports it
            simple_tournament.badges_assigned = True
            self.stdout.write('  📋 Badges assigned (placeholder)')
        
        # Restore players to original teams
        if not simple_tournament.players_restored:
            restored_count = tournament.restore_melee_players_to_original_teams()
            simple_tournament.players_restored = True
            self.stdout.write(f'  👥 Restored {restored_count} players to original teams')
        
        # Delete empty temporary tournament teams (Mêlée / Tête-à-tête)
        if not simple_tournament.mele_teams_deleted:
            mele_teams = tournament.teams.filter(is_tournament_temp=True)
            deleted_count = 0
            skipped_count = 0
            for team in mele_teams:
                remaining = team.players.count()
                if remaining == 0:
                    team_name = team.name
                    team.delete()
                    deleted_count += 1
                    self.stdout.write(f'    🗑️  Deleted empty team: {team_name}')
                else:
                    # Safety guard: players not fully restored — do NOT delete.
                    self.stdout.write(
                        self.style.ERROR(
                            f'    SAFETY ABORT: Cannot delete temp team "{team.name}" '
                            f'(id={team.id}) — {remaining} player(s) still belong to it.'
                        )
                    )
                    skipped_count += 1
            
            simple_tournament.mele_teams_deleted = True
            self.stdout.write(f'  🗑️  Deleted {deleted_count} empty temp teams ({skipped_count} skipped — still had players)')
        
        # Save the updated status
        simple_tournament.save()
        self.stdout.write('  ✅ Cleanup completed successfully')

