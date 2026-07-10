"""
friendly_games/signals.py
==========================
Django signals for the friendly_games app.

post_save on FriendlyGame
--------------------------
When a FriendlyGame transitions to a terminal status (CANCELLED, EXPIRED,
COMPLETED) via *any* path — view, management command, Django admin, shell —
this signal deactivates the associated billboard presence entries.

The view-level calls to deactivate_friendly_game_presence() are idempotent,
so calling it a second time from the signal is safe and results in a no-op
if the view already handled it.

This signal is the safety net for paths that bypass the view layer (e.g.
direct admin saves, shell updates, bulk queryset.update() calls that were
already handled by collecting objects first).
"""
import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import FriendlyGame

logger = logging.getLogger(__name__)

TERMINAL_STATUSES = {'CANCELLED', 'EXPIRED', 'COMPLETED'}


@receiver(post_save, sender=FriendlyGame)
def deactivate_presence_on_terminal_status(sender, instance, created, **kwargs):
    """
    Deactivate billboard presence entries when a FriendlyGame reaches a
    terminal status.  Called after every save; skips non-terminal statuses
    and newly-created games.
    """
    if created:
        # Newly created games have no presence entries yet.
        return

    if instance.status not in TERMINAL_STATUSES:
        return

    try:
        from .presence_utils import deactivate_friendly_game_presence
        deactivate_friendly_game_presence(instance)
    except Exception as exc:
        logger.error(
            f"Signal: error deactivating presence for FriendlyGame {instance.id} "
            f"(status={instance.status}): {exc}"
        )
