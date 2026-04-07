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
"""
import json
from channels.generic.websocket import AsyncWebsocketConsumer


class InviteConsumer(AsyncWebsocketConsumer):
    """
    Persistent per-player WebSocket for invite notifications.

    URL pattern (see invites/routing.py):
        ws/invites/<player_id>/

    The client connects once and stays connected.  The server pushes
    invite events as they occur.
    """

    async def connect(self):
        self.player_id  = self.scope["url_route"]["kwargs"]["player_id"]
        self.group_name = f"player_{self.player_id}"

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

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
