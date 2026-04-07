"""
pfc_events/routing.py
=====================
WebSocket URL patterns for the PFC event layer.

Two URL patterns share the same consumer:
  ws/match/<id>/   — tournament match events
  ws/game/<id>/    — friendly game events

The match_type kwarg ("match" or "game") is used by the consumer to
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
]
