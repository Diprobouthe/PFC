"""
pfc_events/consumers.py
=======================
Two consumers:

1. MatchEventConsumer — server-authoritative match state events.
   Groups: "match_{id}" / "game_{id}" (shared) + "player_{codename}" (personal)
   Events: match.state_changed → client navigates via next_url (no HTTP fetch)

2. ScoreboardConsumer — real-time score push for live scoreboards.
   Group: "scoreboard_{id}"
   Events: score.updated → client updates DOM in-place (no reload)

Architecture contract:
  - Consumers are read-only: they never change state.
  - All state changes go through Django HTTP views.
  - Clients MUST NOT poll, reload, or fetch after receiving a WS event.
"""
import json
from channels.generic.websocket import AsyncWebsocketConsumer


class MatchEventConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for live match/game state events.

    URL patterns (see routing.py):
        ws/match/<object_id>/    - tournament match
        ws/game/<object_id>/     - friendly game
    """

    async def connect(self):
        kwargs = self.scope["url_route"]["kwargs"]
        self.match_type = kwargs.get("match_type", "match")
        self.object_id  = kwargs["object_id"]
        self.group_name = f"{self.match_type}_{self.object_id}"

        # Join the shared match/game group (spectators + all players)
        await self.channel_layer.group_add(self.group_name, self.channel_name)

        # Join the personal player group so this client receives
        # a personalised next_url without any follow-up HTTP request.
        self.personal_group = None
        session = self.scope.get("session", {})
        codename = session.get("player_codename")
        if codename:
            self.personal_group = f"player_{codename}"
            await self.channel_layer.group_add(self.personal_group, self.channel_name)

        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)
        if self.personal_group:
            await self.channel_layer.group_discard(self.personal_group, self.channel_name)

    # ── Incoming messages from client (ignored — read-only consumer) ──────
    async def receive(self, text_data=None, bytes_data=None):
        pass  # All state changes go through HTTP views, never through WS

    # ── Event handlers ────────────────────────────────────────────────────

    async def match_state_changed(self, event):
        """
        Relay a match.state_changed event to the connected WebSocket client.

        Includes next_url when available (personal group payloads).
        Spectator payloads carry next_url=null — clients handle both cases.

        Called automatically by the channel layer when group_send() is used
        with type="match.state_changed".
        """
        await self.send(text_data=json.dumps({
            "type":       "match.state_changed",
            "match_type": event.get("match_type", "match"),
            "match_id":   event.get("match_id"),
            "new_status": event.get("new_status", ""),
            "next_url":   event.get("next_url"),   # None for spectators
        }))

    async def score_updated(self, event):
        """
        Relay a score.updated event to the connected WebSocket client.

        Called automatically by the channel layer when group_send() is used
        with type="score_updated" on the "match_{id}" or "game_{id}" group.
        This allows scoreboard_detail.html (player view) to also receive
        score pushes if it is connected to the match group.
        """
        await self.send(text_data=json.dumps({
            "type":             "score.updated",
            "scoreboard_id":    event.get("scoreboard_id"),
            "team1_score":      event.get("team1_score"),
            "team2_score":      event.get("team2_score"),
            "last_updated_by":  event.get("last_updated_by", ""),
            "is_active":        event.get("is_active", True),
        }))


class ScoreboardConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for live scoreboard score updates.

    URL pattern (see routing.py):
        ws/scoreboard/<scoreboard_id>/

    Group: "scoreboard_{scoreboard_id}"

    This consumer is used by:
      - scoreboard_detail.html  (player live-score view)
      - scoreboard_embed.html   (public spectator view)

    Both views subscribe to the same group and update their DOM in-place
    when a score.updated event arrives — no page reload required.
    """

    async def connect(self):
        self.scoreboard_id = self.scope["url_route"]["kwargs"]["scoreboard_id"]
        self.group_name = f"scoreboard_{self.scoreboard_id}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data=None, bytes_data=None):
        pass  # Read-only consumer

    async def score_updated(self, event):
        """
        Relay a score.updated event to the connected WebSocket client.

        Called automatically by the channel layer when group_send() is used
        with type="score_updated" on the "scoreboard_{id}" group.
        """
        await self.send(text_data=json.dumps({
            "type":             "score.updated",
            "scoreboard_id":    event.get("scoreboard_id"),
            "team1_score":      event.get("team1_score"),
            "team2_score":      event.get("team2_score"),
            "last_updated_by":  event.get("last_updated_by", ""),
            "is_active":        event.get("is_active", True),
        }))
