"""
Management command to fix team match statistics bug.

This script:
1. Resets existing team-match W/L per player
2. Creates TeamMatchParticipant records from existing MatchPlayer data
3. Recomputes player statistics from participation data (played = TRUE only)
4. Handles edge cases (walkover, forfeit, BYE)

Usage:
    python manage.py fix_team_match_statistics [--dry-run] [--verbose]
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db import models
from django.utils import timezone
from matches.models import Match, MatchPlayer
from matches.models_participant import TeamMatchParticipant
from teams.models import PlayerProfile
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Fix team match statistics by implementing proper participation tracking'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be done without making changes',
        )
        parser.add_argument(
            '--verbose',
            action='store_true',
            help='Show detailed progress information',
        )
        parser.add_argument(
            '--reset-only',
            action='store_true',
            help='Only reset statistics without recomputing (for testing)',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        verbose = options['verbose']
        reset_only = options['reset_only']

        self.stdout.write(
            self.style.SUCCESS(
                f"🔧 Starting team match statistics fix {'(DRY RUN)' if dry_run else ''}"
            )
        )

        try:
            with transaction.atomic():
                # Step 1: Reset existing statistics
                self.reset_player_statistics(dry_run, verbose)
                
                if not reset_only:
                    # Step 2: Create participation records from MatchPlayer data
                    self.create_participation_records(dry_run, verbose)
                    
                    # Step 3: Handle edge cases
                    self.handle_edge_cases(dry_run, verbose)
                    
                    # Step 4: Recompute statistics from participation data
                    self.recompute_statistics(dry_run, verbose)
                
                if dry_run:
                    # Rollback transaction for dry run
                    raise transaction.TransactionManagementError("Dry run - rolling back")

        except transaction.TransactionManagementError:
            if dry_run:
                self.stdout.write(
                    self.style.WARNING("🔄 Dry run completed - no changes made")
                )
            else:
                raise
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f"❌ Error during statistics fix: {e}")
            )
            raise
        else:
            self.stdout.write(
                self.style.SUCCESS("✅ Team match statistics fix completed successfully!")
            )

    def reset_player_statistics(self, dry_run, verbose):
        """Reset all player match statistics to zero"""
        self.stdout.write("📊 Step 1: Resetting player statistics...")
        
        player_profiles = PlayerProfile.objects.all()
        reset_count = 0
        
        for profile in player_profiles:
            if profile.matches_played > 0 or profile.matches_won > 0:
                if verbose:
                    self.stdout.write(
                        f"  Resetting {profile.player.name}: "
                        f"{profile.matches_played} played, {profile.matches_won} won"
                    )
                
                if not dry_run:
                    profile.matches_played = 0
                    profile.matches_won = 0
                    profile.save()
                
                reset_count += 1
        
        self.stdout.write(
            self.style.SUCCESS(f"  ✅ Reset statistics for {reset_count} players")
        )

    def create_participation_records(self, dry_run, verbose):
        """Create TeamMatchParticipant records from existing MatchPlayer data"""
        self.stdout.write("👥 Step 2: Creating participation records...")
        
        # Get all completed matches with MatchPlayer data
        matches_with_players = Match.objects.filter(
            status='completed',
            match_players__isnull=False
        ).distinct()
        
        total_matches = matches_with_players.count()
        processed_matches = 0
        total_participants_created = 0
        
        for match in matches_with_players:
            if verbose:
                self.stdout.write(f"  Processing match: {match}")
            
            # Check if participation records already exist
            existing_participants = TeamMatchParticipant.objects.filter(match=match).count()
            if existing_participants > 0:
                if verbose:
                    self.stdout.write(f"    Skipping - {existing_participants} participants already exist")
                continue
            
            if not dry_run:
                participants_created = TeamMatchParticipant.create_from_match_players(match)
                total_participants_created += participants_created
                
                if verbose:
                    self.stdout.write(f"    Created {participants_created} participation records")
            else:
                # Count what would be created
                match_players_count = MatchPlayer.objects.filter(match=match).count()
                total_participants_created += match_players_count
                
                if verbose:
                    self.stdout.write(f"    Would create {match_players_count} participation records")
            
            processed_matches += 1
        
        self.stdout.write(
            self.style.SUCCESS(
                f"  ✅ Processed {processed_matches}/{total_matches} matches, "
                f"created {total_participants_created} participation records"
            )
        )

    def handle_edge_cases(self, dry_run, verbose):
        """Handle edge cases like walkover, forfeit, BYE"""
        self.stdout.write("⚠️  Step 3: Handling edge cases...")
        
        # For now, we'll identify potential edge cases but not automatically handle them
        # since we need more context about how these are currently stored
        
        # Look for matches with unusual score patterns that might indicate walkovers
        unusual_matches = Match.objects.filter(
            status='completed'
        ).filter(
            models.Q(team1_score=0, team2_score=0) |  # Potential BYE
            models.Q(team1_score__gte=13, team2_score=0) |  # Potential walkover
            models.Q(team1_score=0, team2_score__gte=13)    # Potential walkover
        )
        
        edge_case_count = unusual_matches.count()
        
        if edge_case_count > 0:
            self.stdout.write(
                self.style.WARNING(
                    f"  ⚠️  Found {edge_case_count} matches with unusual scores that might be edge cases"
                )
            )
            
            if verbose:
                for match in unusual_matches[:5]:  # Show first 5 examples
                    self.stdout.write(
                        f"    {match} - Score: {match.team1_score}-{match.team2_score}"
                    )
                if edge_case_count > 5:
                    self.stdout.write(f"    ... and {edge_case_count - 5} more")
            
            self.stdout.write(
                "  ℹ️  Edge cases require manual review - participation records created as normal"
            )
        else:
            self.stdout.write("  ✅ No obvious edge cases found")

    def recompute_statistics(self, dry_run, verbose):
        """Recompute player statistics from TeamMatchParticipant data"""
        self.stdout.write("🔢 Step 4: Recomputing statistics from participation data...")
        
        player_profiles = PlayerProfile.objects.all()
        updated_count = 0
        
        for profile in player_profiles:
            # Get accurate statistics from participation data
            stats = profile.get_accurate_match_statistics()
            
            old_played = profile.matches_played
            old_won = profile.matches_won
            new_played = stats['matches_played']
            new_won = stats['matches_won']
            
            if old_played != new_played or old_won != new_won:
                if verbose:
                    self.stdout.write(
                        f"  Updating {profile.player.name}: "
                        f"{old_played}→{new_played} played, {old_won}→{new_won} won "
                        f"(Win rate: {stats['win_rate']}%)"
                    )
                
                if not dry_run:
                    profile.matches_played = new_played
                    profile.matches_won = new_won
                    profile.save()
                
                updated_count += 1
        
        self.stdout.write(
            self.style.SUCCESS(f"  ✅ Updated statistics for {updated_count} players")
        )

    def get_summary_statistics(self):
        """Get summary statistics for reporting"""
        total_matches = Match.objects.filter(status='completed').count()
        total_participants = TeamMatchParticipant.objects.count()
        total_players_with_stats = PlayerProfile.objects.filter(matches_played__gt=0).count()
        
        return {
            'total_matches': total_matches,
            'total_participants': total_participants,
            'total_players_with_stats': total_players_with_stats,
        }

