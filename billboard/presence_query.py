"""Shared read-only definition of current physical AT_COURTS presence.

Used by court-complex presentation and Friendly creator venue authorization.
Presence creation, expiry and game lifecycle remain unchanged.
"""

from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from billboard.models import BillboardEntry
from courts.timezone_utils import get_court_local_now


def current_court_presence(court_complex):
    """Return valid active presence entries at a court complex, newest first.

    Manual/legacy: 2 hours; game-generated: 6-hour safety cap;
    post_game: explicit expires_at (normally 30 minutes).
    """
    now = timezone.now()
    manual_cutoff = get_court_local_now(court_complex) - timedelta(hours=2)
    game_cutoff = now - timedelta(hours=6)
    return (
        BillboardEntry.objects.filter(
            court_complex=court_complex,
            action_type='AT_COURTS',
            is_active=True,
        )
        .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
        .filter(
            Q(
                presence_source__in=(
                    BillboardEntry.PRESENCE_SOURCE_FRIENDLY,
                    BillboardEntry.PRESENCE_SOURCE_MATCH,
                ),
                created_at__gte=game_cutoff,
            )
            | Q(
                presence_source=BillboardEntry.PRESENCE_SOURCE_MATCH,
                game_ref__startswith="tournament:",
                expires_at__isnull=False,
            )
            | Q(presence_source=BillboardEntry.PRESENCE_SOURCE_POST_GAME,
                expires_at__isnull=False)
            | Q(presence_source=BillboardEntry.PRESENCE_SOURCE_MANUAL,
                created_at__gte=manual_cutoff)
            | Q(presence_source__isnull=True,
                created_at__gte=manual_cutoff)
        )
        .order_by('-created_at')
    )
