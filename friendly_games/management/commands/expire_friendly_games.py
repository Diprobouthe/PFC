"""
Management command: expire_friendly_games
==========================================

Marks all non-completed friendly games older than 24 hours as CANCELLED.
No records are ever deleted — stale games become CANCELLED so Smart PFC
ignores them automatically (it already excludes CANCELLED from routing).

Usage:
    python manage.py expire_friendly_games          # cancel stale games
    python manage.py expire_friendly_games --dry-run # preview only

Designed to run via cron (e.g. every hour) or called at application
startup / key request points.
"""

from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta

from friendly_games.models import FriendlyGame


# Statuses that are "terminal" — these games are already done
TERMINAL_STATUSES = {'COMPLETED', 'CANCELLED', 'EXPIRED'}

# Games older than this are considered stale and should be expired
EXPIRATION_HOURS = 24


class Command(BaseCommand):
    help = 'Mark friendly games older than 24 hours as CANCELLED (no deletion)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be cancelled without making changes',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        cutoff = timezone.now() - timedelta(hours=EXPIRATION_HOURS)

        # Find non-terminal games older than 24h
        stale_games = FriendlyGame.objects.filter(
            created_at__lt=cutoff,
        ).exclude(
            status__in=TERMINAL_STATUSES,
        )

        count = stale_games.count()

        if count == 0:
            self.stdout.write(self.style.SUCCESS('No stale friendly games found.'))
            return

        if dry_run:
            self.stdout.write(self.style.WARNING(
                f'[DRY RUN] Would cancel {count} friendly game(s):'
            ))
            for g in stale_games[:20]:
                age_h = (timezone.now() - g.created_at).total_seconds() / 3600
                self.stdout.write(
                    f'  id={g.id} name="{g.name}" status={g.status} '
                    f'age={age_h:.1f}h match_number={g.match_number}'
                )
            if count > 20:
                self.stdout.write(f'  ... and {count - 20} more')
            return

        # Mark as CANCELLED — no deletion
        cancelled_count = stale_games.update(status='CANCELLED')
        self.stdout.write(self.style.SUCCESS(
            f'Marked {cancelled_count} stale friendly game(s) as CANCELLED.'
        ))
