"""Explicit command for the same request-driven Friendly expiry policy.

The Smart Router also calls this policy; no cron is required.
"""
from django.core.management.base import BaseCommand
from friendly_games.expiration import expire_stale_friendly_games


class Command(BaseCommand):
    help = 'Cancel stale Friendly games without deleting history'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        if options['dry_run']:
            from datetime import timedelta
            from django.db.models import Q
            from django.utils import timezone
            from friendly_games.models import FriendlyGame
            now = timezone.now()
            count = FriendlyGame.objects.filter(
                Q(status='WAITING_FOR_PLAYERS',
                  created_at__lt=now - timedelta(minutes=10))
                | Q(status='ACTIVE',
                    started_at__lt=now - timedelta(minutes=150))
                | Q(status='ACTIVE', started_at__isnull=True,
                    created_at__lt=now - timedelta(minutes=150))
            ).count()
            self.stdout.write(f'[DRY RUN] Would cancel {count} stale Friendly game(s).')
            return
        count = expire_stale_friendly_games()
        self.stdout.write(self.style.SUCCESS(f'Cancelled {count} stale Friendly game(s).'))
