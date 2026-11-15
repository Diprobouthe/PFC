"""Lightweight, court-scoped Friendly presence.

A game confirms a player's physical presence, but does not own its lifetime.
The first game creates a two-hour presence. Later games reuse it, refreshing
the same row only when less than one hour remains. Completing, cancelling or
expiring a game never removes the player's physical presence.
"""
import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from billboard.models import BillboardEntry
from billboard.presence_query import current_court_presence
from courts.models import CourtComplex
from friendly_games.models import PlayerCodename

logger = logging.getLogger(__name__)
PRESENCE_MINUTES = 120
REFRESH_WHEN_REMAINING_MINUTES = 60


def register_friendly_game_players_at_court(game):
    """Reuse or refresh one current presence per player and court.

    Serializing on the CourtComplex row prevents concurrent activations from
    creating duplicate entries for the same player at the same venue.
    Existing manual presence is reused; its original source is preserved.
    """
    if not game.court_complex_id:
        return
    try:
        player_ids = list(game.players.values_list('player_id', flat=True))
        codenames = list(PlayerCodename.objects.filter(
            player_id__in=player_ids
        ).values_list('codename', flat=True))
        if not codenames:
            return
        with transaction.atomic():
            CourtComplex.objects.select_for_update().get(pk=game.court_complex_id)
            now = timezone.now()
            expiry = now + timedelta(minutes=PRESENCE_MINUTES)
            refresh_cutoff = now + timedelta(minutes=REFRESH_WHEN_REMAINING_MINUTES)
            # Shared query enforces the same source-aware freshness rules as
            # venue authorization; never resurrect a stale presence.
            current = {}
            for entry in current_court_presence(game.court_complex).filter(
                codename__in=codenames
            ):
                current.setdefault(entry.codename, entry)
            for codename in set(codenames):
                entry = current.get(codename)
                if entry:
                    # Legacy/manual entries use created_at for their 2-hour
                    # cutoff; other sources may have an explicit expires_at.
                    effective_expiry = entry.expires_at
                    if entry.presence_source in (
                        BillboardEntry.PRESENCE_SOURCE_MANUAL, None
                    ):
                        manual_expiry = entry.created_at + timedelta(minutes=120)
                        effective_expiry = min(
                            effective_expiry, manual_expiry
                        ) if effective_expiry else manual_expiry
                    elif not effective_expiry:
                        effective_expiry = entry.created_at + timedelta(hours=6)
                    if effective_expiry > refresh_cutoff:
                        continue
                    # Refresh existing record, not a new INSERT. Keep its
                    # source and provenance; manual freshness is also renewed.
                    BillboardEntry.objects.filter(pk=entry.pk).update(
                        created_at=now, expires_at=expiry
                    )
                else:
                    BillboardEntry.objects.create(
                        codename=codename,
                        action_type='AT_COURTS',
                        court_complex=game.court_complex,
                        is_active=True,
                        presence_source=BillboardEntry.PRESENCE_SOURCE_FRIENDLY,
                        game_ref=None,
                        expires_at=expiry,
                        message='Court presence confirmed by Friendly Game',
                    )
    except Exception:
        logger.exception('Unable to register Friendly presence for game %s', game.pk)


def deactivate_friendly_game_presence(game, *, create_grace=True):
    """Compatibility hook: game lifecycle does not revoke court presence.

    Existing records expire through the read-side timestamp. Neither
    cancellation nor completion writes to Billboard.
    """
    return
