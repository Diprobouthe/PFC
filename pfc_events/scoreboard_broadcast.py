"""Read-only Match Tracking broadcasts for the existing public scoreboard channel."""

import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

logger = logging.getLogger(__name__)


def _send(scoreboard_id, event_type, **payload):
    """Send a non-authoritative spectator event over the established scoreboard group."""
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return
    try:
        async_to_sync(channel_layer.group_send)(
            f"scoreboard_{scoreboard_id}",
            {"type": event_type, "scoreboard_id": scoreboard_id, **payload},
        )
    except Exception as exc:
        logger.warning("scoreboard tracking broadcast failed for %s: %s", scoreboard_id, exc)


def broadcast_tracking_action(scoreboard_id, action):
    """Append one already-permitted Match Tracking action to the spectator feed."""
    _send(scoreboard_id, "tracking_action", action=action)


def broadcast_tracking_feed(scoreboard_id, actions):
    """Replace the public current-end feed after consent, undo, or score-boundary changes."""
    _send(scoreboard_id, "tracking_feed_replaced", actions=actions)
