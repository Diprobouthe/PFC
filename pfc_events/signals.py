"""
pfc_events/signals.py
=====================
Server-side emitter helpers.

Views call these functions after changing match state.
They broadcast a "match.state_changed" event to all WebSocket clients
currently connected to that match/game group.

Usage (in any view, after saving a state change):
    from pfc_events.signals import notify_match_state_changed, notify_game_state_changed

    # After changing a tournament match status:
    notify_match_state_changed(match.id, match.status)

    # After changing a friendly game status:
    notify_game_state_changed(game.id, game.status)

These functions are fire-and-forget: they use async_to_sync so they can
be called from synchronous Django views without any changes to the view
architecture.
"""
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer


def _broadcast(group_name: str, match_type: str, object_id: int, new_status: str):
    """Low-level broadcast helper. Safe to call from sync code."""
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return  # Channels not configured — silent no-op (e.g. unit tests)
    async_to_sync(channel_layer.group_send)(
        group_name,
        {
            "type":       "match.state_changed",   # maps to consumer.match_state_changed()
            "match_type": match_type,
            "match_id":   object_id,
            "new_status": new_status,
        },
    )


def notify_match_state_changed(match_id: int, new_status: str):
    """
    Broadcast a state-change event to all clients watching tournament match <match_id>.
    Call this from any view that changes Match.status.
    """
    _broadcast(f"match_{match_id}", "tournament", match_id, new_status)


def notify_game_state_changed(game_id: int, new_status: str):
    """
    Broadcast a state-change event to all clients watching friendly game <game_id>.
    Call this from any view that changes FriendlyGame.status.
    """
    _broadcast(f"game_{game_id}", "friendly", game_id, new_status)
