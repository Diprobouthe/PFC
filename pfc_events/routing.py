"""
pfc_events/routing.py
=====================
WebSocket URL patterns for the PFC event layer.

  ws/match/<id>/        — tournament match state events (MatchEventConsumer)
  ws/game/<id>/         — friendly game state events   (MatchEventConsumer)
  ws/scoreboard/<id>/   — live scoreboard score push   (ScoreboardConsumer)

The match_type kwarg ("match" or "game") is used by MatchEventConsumer to
build the correct channel group name.
"""
from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    re_path(
        r"^ws/match/(?P<object_id>\d+)/$",
        consumers.MatchEventConsumer.as_asgi(),
        kwargs={"match_type": "match"},
    ),
    re_path(
        r"^ws/game/(?P<object_id>\d+)/$",
        consumers.MatchEventConsumer.as_asgi(),
        kwargs={"match_type": "game"},
    ),
    re_path(
        r"^ws/scoreboard/(?P<scoreboard_id>\d+)/$",
        consumers.ScoreboardConsumer.as_asgi(),
    ),
]
