"""
invites/consumers.py
====================
InviteConsumer — WebSocket consumer for the targeted invitation system.

Channel group naming:
    player_{player_id}   — one persistent group per player

Events relayed to client:
    invite.received   — a new invite arrived for this player
    invite.accepted   — one of your sent invites was accepted
    invite.rejected   — one of your sent invites was rejected
    session.ready     — a TeamBuildSession reached quorum; team was created
    session.update    — a TeamBuildSession acceptance count changed

Design rules:
    - Consumer is read-only from the client side (no client → server messages).
    - All state changes go through HTTP views (accept/reject endpoints).
    - This consumer never touches match/tournament/team logic directly.

Auth guard (connect):
    The URL carries the player's integer PK (ws/invites/<player_id>/).
    On connect, the consumer resolves the session's player_codename to a
    Player PK and compares it to the URL parameter.  If they do not match,
    or if no valid session is present, the connection is closed with code
    4003 (Forbidden) before joining any channel group.
    This requires SessionMiddlewareStack to be applied in asgi.py so that
    self.scope["session"] is populated from the browser session cookie.
"""
import logging
import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async

logger = logging.getLogger(__name__)


class InviteConsumer(AsyncWebsocketConsumer):
    """
    Persistent per-player WebSocket for invite notifications.

    URL pattern (see invites/routing.py):
        ws/invites/<player_id>/

    The client connects once and stays connected.  The server pushes
    invite events as they occur.
    """

    # ── Auth helper ──────────────────────────────────────────────────────────

    @database_sync_to_async
    def _resolve_session_player_id(self, codename):
        """
        Look up the Player PK for the given codename string.
        Returns the integer PK, or None if not found.
        """
        try:
            from friendly_games.models import PlayerCodename
            pc = PlayerCodename.objects.select_related("player").get(
                codename=codename.upper()
            )
            return pc.player_id
        except Exception:
            return None

    # ── Lifecycle ────────────────────────────────────────────────────────────

    async def connect(self):
        url_player_id = int(self.scope["url_route"]["kwargs"]["player_id"])

        # ── Session auth guard ───────────────────────────────────────────────
        # Resolve the session's player_codename to a Player PK and compare
        # it to the player_id in the URL.  Reject mismatches and anonymous
        # connections to prevent one player from subscribing to another's
        # notification stream.
        session = self.scope.get("session", {})
        codename = session.get("player_codename")

        if not codename:
            # No active player session — reject silently.
            logger.warning(
                "InviteConsumer: rejected unauthenticated connection "
                "for player_id=%s (no session codename)",
                url_player_id,
            )
            await self.close(code=4003)
            return

        session_player_id = await self._resolve_session_player_id(codename)

        if session_player_id is None or session_player_id != url_player_id:
            # Session player does not match the requested channel — reject.
            logger.warning(
                "InviteConsumer: rejected connection for player_id=%s "
                "(session resolves to player_id=%s, codename=%s)",
                url_player_id,
                session_player_id,
                codename,
            )
            await self.close(code=4003)
            return

        # Auth passed — join the group and accept.
        self.player_id  = url_player_id
        self.group_name = f"player_{self.player_id}"

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        # group_name may not be set if connect() rejected before setting it.
        group = getattr(self, "group_name", None)
        if group:
            await self.channel_layer.group_discard(group, self.channel_name)

    # ── Client → Server (ignored; all changes go through HTTP) ───────────────
    async def receive(self, text_data=None, bytes_data=None):
        pass

    # ── Server → Client event handlers ───────────────────────────────────────

    async def invite_received(self, event):
        """Push a new incoming invite to the recipient."""
        await self.send(text_data=json.dumps({
            "type":         "invite.received",
            "invite_id":    event["invite_id"],
            "token":        event["token"],
            "invite_type":  event["invite_type"],
            "sender_name":  event["sender_name"],
            "message":      event.get("message", ""),
            "play_time":    event.get("play_time"),
            "play_court":   event.get("play_court"),
            "session_id":   event.get("session_id"),
            "target_size":  event.get("target_size"),
        }))

    async def invite_accepted(self, event):
        """Push acceptance notification to the original sender."""
        await self.send(text_data=json.dumps({
            "type":            "invite.accepted",
            "invite_id":       event["invite_id"],
            "token":           event["token"],
            "recipient_name":  event["recipient_name"],
            "session_id":      event.get("session_id"),
            "accepted_count":  event.get("accepted_count"),
            "target_size":     event.get("target_size"),
        }))

    async def invite_rejected(self, event):
        """Push rejection notification to the original sender."""
        await self.send(text_data=json.dumps({
            "type":            "invite.rejected",
            "invite_id":       event["invite_id"],
            "token":           event["token"],
            "recipient_name":  event["recipient_name"],
        }))

    async def session_ready(self, event):
        """Push 'team created' notification to all session participants."""
        await self.send(text_data=json.dumps({
            "type":       "session.ready",
            "session_id": event["session_id"],
            "team_id":    event["team_id"],
            "team_name":  event["team_name"],
            "team_pin":   event["team_pin"],
        }))

    async def session_update(self, event):
        """Push acceptance-count update to the session creator."""
        await self.send(text_data=json.dumps({
            "type":           "session.update",
            "session_id":     event["session_id"],
            "accepted_count": event["accepted_count"],
            "target_size":    event["target_size"],
        }))
