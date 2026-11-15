"""On-demand Friendly expiration using the existing request-driven lifecycle.

No background worker or deletion. Called before routing/activation and on
Friendly detail requests so abandoned games cannot indefinitely block players.
"""
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from friendly_games.models import FriendlyGame
from friendly_games.presence_utils import deactivate_friendly_game_presence

MAX_STARTED_MINUTES = 150
PRE_START_MINUTES = 10


def expire_stale_friendly_games(*, now=None):
    now = now or timezone.now()
    started_cutoff = now - timedelta(minutes=MAX_STARTED_MINUTES)
    pre_start_cutoff = now - timedelta(minutes=PRE_START_MINUTES)

    stale = FriendlyGame.objects.filter(
        Q(status='WAITING_FOR_PLAYERS', created_at__lt=pre_start_cutoff)
        | Q(status='ACTIVE',
            started_at__lt=started_cutoff)
        | Q(status='ACTIVE',
            started_at__isnull=True, created_at__lt=started_cutoff)
    ).values_list('pk', flat=True)
    ids = list(stale)
    if not ids:
        return 0
    # Queryset.update avoids post_save and the unintended cancellation grace.
    changed = FriendlyGame.objects.filter(pk__in=ids).exclude(
        status__in=('COMPLETED', 'CANCELLED', 'EXPIRED')
    ).update(status='CANCELLED')
    for game_id in ids:
        deactivate_friendly_game_presence(
            FriendlyGame(id=game_id), create_grace=False
        )
    return changed
