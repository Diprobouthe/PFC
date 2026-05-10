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

# Unstarted games (WAITING_FOR_PLAYERS) expire after 10 minutes
PRE_START_EXPIRATION_MINUTES = 10

# Games in other non-terminal states (ACTIVE, PENDING_VALIDATION, etc.) expire after 24 hours
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
        now = timezone.now()

        # 1. Unstarted games: expire after 10 minutes
        pre_start_cutoff = now - timedelta(minutes=PRE_START_EXPIRATION_MINUTES)
        pre_start_stale = FriendlyGame.objects.filter(
            status='WAITING_FOR_PLAYERS',
            created_at__lt=pre_start_cutoff,
        )

        # 2. Other non-terminal games (ACTIVE, PENDING_VALIDATION, etc.): expire after 24h
        long_cutoff = now - timedelta(hours=EXPIRATION_HOURS)
        long_stale = FriendlyGame.objects.filter(
            created_at__lt=long_cutoff,
        ).exclude(
            status__in=TERMINAL_STATUSES | {'WAITING_FOR_PLAYERS'},
        )

        total = pre_start_stale.count() + long_stale.count()

        if total == 0:
            self.stdout.write(self.style.SUCCESS('No stale friendly games found.'))
            return

        if dry_run:
            self.stdout.write(self.style.WARNING(
                f'[DRY RUN] Would cancel {total} friendly game(s):'
            ))
            for g in list(pre_start_stale[:10]) + list(long_stale[:10]):
                age_m = (now - g.created_at).total_seconds() / 60
                self.stdout.write(
                    f'  id={g.id} name="{g.name}" status={g.status} '
                    f'age={age_m:.1f}min match_number={g.match_number}'
                )
            return

        # Mark as CANCELLED — no deletion
        c1 = pre_start_stale.update(status='CANCELLED')
        c2 = long_stale.update(status='CANCELLED')
        self.stdout.write(self.style.SUCCESS(
            f'Marked {c1 + c2} stale friendly game(s) as CANCELLED '
            f'({c1} unstarted >10min, {c2} other >24h).'
        ))
