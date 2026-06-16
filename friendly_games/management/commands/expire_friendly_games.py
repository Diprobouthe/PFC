"""
Management command: expire_friendly_games
==========================================

Marks stale friendly games as CANCELLED. Three tiers:

  Tier 1 — Unstarted (WAITING_FOR_PLAYERS):
      Expire after 10 minutes. Pre-start games that nobody joined/started.

  Tier 2 — Started but unvalidated (ACTIVE, PENDING_VALIDATION):
      Expire after 6 hours. Petanque is not an async game; if a started
      game has not been validated after 6 hours it is abandoned.

  Tier 3 — Any other non-terminal state:
      Expire after 24 hours as a catch-all safety net.

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
from friendly_games.presence_utils import deactivate_friendly_game_presence


# Statuses that are "terminal" — these games are already done
TERMINAL_STATUSES = {'COMPLETED', 'CANCELLED', 'EXPIRED'}

# Tier 1: Unstarted games expire after 10 minutes
PRE_START_EXPIRATION_MINUTES = 10

# Tier 2: Started-but-unvalidated games expire after 6 hours
STARTED_EXPIRATION_HOURS = 6
STARTED_STATUSES = {'ACTIVE', 'PENDING_VALIDATION'}

# Tier 3: Any other non-terminal state expires after 24 hours (catch-all)
EXPIRATION_HOURS = 24


class Command(BaseCommand):
    help = 'Mark stale friendly games as CANCELLED (no deletion)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be cancelled without making changes',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        now = timezone.now()

        # Tier 1: Unstarted games — expire after 10 minutes
        pre_start_cutoff = now - timedelta(minutes=PRE_START_EXPIRATION_MINUTES)
        pre_start_stale = FriendlyGame.objects.filter(
            status='WAITING_FOR_PLAYERS',
            created_at__lt=pre_start_cutoff,
        )

        # Tier 2: Started but unvalidated — expire after 6 hours
        started_cutoff = now - timedelta(hours=STARTED_EXPIRATION_HOURS)
        started_stale = FriendlyGame.objects.filter(
            status__in=STARTED_STATUSES,
            created_at__lt=started_cutoff,
        )

        # Tier 3: Any other non-terminal state — expire after 24 hours
        long_cutoff = now - timedelta(hours=EXPIRATION_HOURS)
        long_stale = FriendlyGame.objects.filter(
            created_at__lt=long_cutoff,
        ).exclude(
            status__in=TERMINAL_STATUSES | {'WAITING_FOR_PLAYERS'} | STARTED_STATUSES,
        )

        total = pre_start_stale.count() + started_stale.count() + long_stale.count()

        if total == 0:
            self.stdout.write(self.style.SUCCESS('No stale friendly games found.'))
            return

        if dry_run:
            self.stdout.write(self.style.WARNING(
                f'[DRY RUN] Would cancel {total} friendly game(s):'
            ))
            for g in list(pre_start_stale[:10]) + list(started_stale[:10]) + list(long_stale[:10]):
                age_m = (now - g.created_at).total_seconds() / 60
                self.stdout.write(
                    f'  id={g.id} name="{g.name}" status={g.status} '
                    f'age={age_m:.1f}min match_number={g.match_number}'
                )
            return

        # Mark as CANCELLED — no deletion.
        # Collect game IDs before the bulk update so we can deactivate presence.
        stale_games = list(pre_start_stale) + list(started_stale) + list(long_stale)
        c1 = pre_start_stale.update(status='CANCELLED')
        c2 = started_stale.update(status='CANCELLED')
        c3 = long_stale.update(status='CANCELLED')
        # Deactivate Billboard presence for every cancelled game
        for g in stale_games:
            deactivate_friendly_game_presence(g)
        self.stdout.write(self.style.SUCCESS(
            f'Marked {c1 + c2 + c3} stale friendly game(s) as CANCELLED '
            f'({c1} unstarted >10min, {c2} started >6h, {c3} other >24h).'
        ))
