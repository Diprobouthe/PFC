"""Read-only fan-out helpers for the Tournament Overview WebSocket.

These helpers mirror existing live-score and tracking events into one shared,
public Tournament Overview group. They never modify Match, LiveScoreboard,
tracking, or tournament state.
"""

import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

logger = logging.getLogger(__name__)


def _send(tournament_id, event_type, **payload):
    if not tournament_id:
        return
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return
    try:
        async_to_sync(channel_layer.group_send)(
            f"tournament_overview_{tournament_id}",
            {"type": event_type, **payload},
        )
    except Exception as exc:
        logger.warning(
            "Tournament Overview broadcast failed for tournament %s: %s",
            tournament_id,
            exc,
        )


def _tournament_id_for_scoreboard(scoreboard):
    """Return the existing linked Tournament ID without changing scoreboard state."""
    if not scoreboard or not scoreboard.tournament_match_id:
        return None
    match = scoreboard.tournament_match
    return match.tournament_id if match else None


def broadcast_score_updated(scoreboard, score_update=None):
    """Mirror an existing score.updated payload to the Tournament Overview."""
    tournament_id = _tournament_id_for_scoreboard(scoreboard)
    if not tournament_id:
        return
    from matches.views_scoreboard import _score_update_payload

    _send(
        tournament_id,
        "overview_score_updated",
        scoreboard_id=scoreboard.id,
        team1_score=scoreboard.team1_score,
        team2_score=scoreboard.team2_score,
        last_updated_by=scoreboard.last_updated_by or "",
        is_active=scoreboard.is_active,
        score_update=_score_update_payload(score_update),
    )


def broadcast_tracking_action(scoreboard, action):
    """Mirror one existing permitted public tracking action to the Overview."""
    tournament_id = _tournament_id_for_scoreboard(scoreboard)
    if tournament_id:
        _send(
            tournament_id,
            "overview_tracking_action",
            scoreboard_id=scoreboard.id,
            action=action or {},
        )


def broadcast_tracking_feed(scoreboard, actions):
    """Mirror an existing permitted tracking feed replacement to the Overview."""
    tournament_id = _tournament_id_for_scoreboard(scoreboard)
    if tournament_id:
        _send(
            tournament_id,
            "overview_tracking_feed_replaced",
            scoreboard_id=scoreboard.id,
            actions=actions or [],
        )


def broadcast_structure_refresh(tournament_id):
    """Ask Overview viewers to fetch cards once after a Match-set transition."""
    _send(tournament_id, "overview_refresh")
