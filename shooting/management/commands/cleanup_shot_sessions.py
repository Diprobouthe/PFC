"""
Management command to clean up stale shot tracker sessions.

Usage:
    python manage.py cleanup_shot_sessions
    python manage.py cleanup_shot_sessions --dry-run
    python manage.py cleanup_shot_sessions --older-than-hours 48
"""

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.conf import settings
from datetime import timedelta
from shooting.models import ShotSession


class Command(BaseCommand):
    help = 'Clean up stale shot tracker sessions'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be cleaned up without actually doing it',
        )
        
        parser.add_argument(
            '--older-than-hours',
            type=int,
            default=None,
            help='Clean up sessions older than this many hours (default from settings)',
        )
        
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force cleanup even if sessions have events',
        )
    
    def handle(self, *args, **options):
        dry_run = options['dry_run']
        force = options['force']
        
        # Get timeout from options or settings
        timeout_hours = options['older_than_hours']
        if timeout_hours is None:
            timeout_seconds = getattr(settings, 'SHOT_TRACKER_SESSION_TIMEOUT', 3600)
            timeout_hours = timeout_seconds / 3600
        
        cutoff_time = timezone.now() - timedelta(hours=timeout_hours)
        
        self.stdout.write(f"Looking for sessions older than {timeout_hours} hours...")
        self.stdout.write(f"Cutoff time: {cutoff_time}")
        
        # Find stale active sessions
        stale_sessions = ShotSession.objects.filter(
            is_active=True,
            started_at__lt=cutoff_time
        )
        
        if not stale_sessions.exists():
            self.stdout.write(
                self.style.SUCCESS("No stale sessions found.")
            )
            return
        
        self.stdout.write(f"Found {stale_sessions.count()} stale sessions:")
        
        cleaned_count = 0
        skipped_count = 0
        
        for session in stale_sessions:
            # Check if session has events
            has_events = session.events.exists()
            
            session_info = (
                f"  Session {session.id} (User: {session.user.username}, "
                f"Started: {session.started_at}, Events: {session.events.count()})"
            )
            
            if has_events and not force:
                self.stdout.write(
                    self.style.WARNING(f"SKIP: {session_info} - has events (use --force)")
                )
                skipped_count += 1
                continue
            
            if dry_run:
                self.stdout.write(
                    self.style.NOTICE(f"WOULD CLEAN: {session_info}")
                )
            else:
                try:
                    session.end_session()
                    self.stdout.write(
                        self.style.SUCCESS(f"CLEANED: {session_info}")
                    )
                    cleaned_count += 1
                except Exception as e:
                    self.stdout.write(
                        self.style.ERROR(f"ERROR cleaning {session.id}: {e}")
                    )
        
        # Summary
        if dry_run:
            self.stdout.write(
                self.style.NOTICE(
                    f"\nDry run complete. Would clean {stale_sessions.count() - skipped_count} sessions."
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"\nCleanup complete. Cleaned {cleaned_count} sessions, skipped {skipped_count}."
                )
            )
        
        # Also clean up very old inactive sessions (optional)
        if not dry_run:
            old_cutoff = timezone.now() - timedelta(days=30)  # 30 days
            old_sessions = ShotSession.objects.filter(
                is_active=False,
                started_at__lt=old_cutoff
            )
            
            if old_sessions.exists():
                self.stdout.write(f"\nFound {old_sessions.count()} old inactive sessions (>30 days)")
                
                if input("Delete old inactive sessions? (y/N): ").lower() == 'y':
                    deleted_count = old_sessions.count()
                    old_sessions.delete()
                    self.stdout.write(
                        self.style.SUCCESS(f"Deleted {deleted_count} old inactive sessions.")
                    )
