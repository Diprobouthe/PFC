"""
pfc_events/consumers.py
=======================
MatchEventConsumer — minimal WebSocket consumer for live match state transitions.

Design rules:
  - One channel group per match:  "match_{id}"
  - One channel group per friendly game:  "game_{id}"
  - Consumer only relays events; it never changes match state.
  - No routing logic lives here; the client calls /my-matches/next-url/
    after receiving an event to resolve its correct destination.

Future-proof:
  The same consumer can carry other event types later (invites, notifications,
  team formation) by adding new message types without touching existing code.
"""
import json
from channels.generic.websocket import AsyncWebsocketConsumer


class MatchEventConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer that clients connect to while on a match page.

    URL patterns (see routing.py):
        ws/match/<match_id>/        — tournament match
        ws/game/<game_id>/          — friendly game

    On connect:
        The consumer joins the appropriate channel group so it receives
        any events broadcast to that match/game.

    On receive (server → client only):
        The consumer does not process messages sent from the client.
        All state changes happen through normal Django HTTP views.

    Event shape sent to client:
        {
            "type": "match.state_changed",
            "match_type": "tournament" | "friendly",
            "match_id": <int>,
            "new_status": "<status string>"
        }

    Client reaction:
        On receiving any event, the client calls GET /my-matches/next-url/
        and navigates to the returned URL if it differs from the current page.
        This keeps all routing logic in the server-side PFC decision engine.
    """

    async def connect(self):
        self.match_type = self.scope["url_route"]["kwargs"].get("match_type", "match")
        self.object_id  = self.scope["url_route"]["kwargs"]["object_id"]
        self.group_name = f"{self.match_type}_{self.object_id}"

        # Join the channel group for this match/game
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    # ── Incoming messages from client (ignored — read-only consumer) ──────
    async def receive(self, text_data=None, bytes_data=None):
        pass  # Clients do not send data; all state changes go through HTTP

    # ── Event handlers (called by channel layer when server broadcasts) ───
    async def match_state_changed(self, event):
        """
        Relay a match.state_changed event to the connected WebSocket client.
        Called automatically by the channel layer when group_send() is used
        with type="match.state_changed".
        """
        await self.send(text_data=json.dumps({
            "type":       "match.state_changed",
            "match_type": event.get("match_type", "tournament"),
            "match_id":   event.get("match_id"),
            "new_status": event.get("new_status", ""),
        }))
