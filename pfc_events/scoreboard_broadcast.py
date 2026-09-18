"""Read-only Match Tracking broadcasts for the existing public scoreboard channel."""

import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

logger = logging.getLogger(__name__)


def _send(scoreboard, event_type, **payload):
    """Send a permitted spectator event to the scoreboard and its Overview."""
    if not scoreboard:
        return
    channel_layer = get_channel_layer()
    if channel_layer is not None:
        try:
            async_to_sync(channel_layer.group_send)(
                f"scoreboard_{scoreboard.id}",
                {"type": event_type, "scoreboard_id": scoreboard.id, **payload},
            )
        except Exception as exc:
            logger.warning(
                "scoreboard tracking broadcast failed for %s: %s",
                scoreboard.id,
                exc,
            )

    # The Overview is another public spectator projection. It receives exactly
    # the already-permitted payload and cannot alter tracking or match state.
    from pfc_events import tournament_overview
    if event_type == "tracking_action":
        tournament_overview.broadcast_tracking_action(scoreboard, payload.get("action"))
    elif event_type == "tracking_feed_replaced":
        tournament_overview.broadcast_tracking_feed(scoreboard, payload.get("actions"))


def broadcast_tracking_action(scoreboard, action):
    """Append one already-permitted Match Tracking action to spectator feeds."""
    _send(scoreboard, "tracking_action", action=action)


def broadcast_tracking_feed(scoreboard, actions):
    """Replace public feeds after consent, undo, or a score boundary."""
    _send(scoreboard, "tracking_feed_replaced", actions=actions)
