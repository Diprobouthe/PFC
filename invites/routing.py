"""
invites/routing.py
==================
WebSocket URL pattern for the InviteConsumer.

Pattern:
    ws/invites/<player_id>/

The player_id is the PK of the Player model.
The client connects once on page load and stays connected.
"""
from django.urls import re_path
from .consumers import InviteConsumer

websocket_urlpatterns = [
    re_path(
        r"^ws/invites/(?P<player_id>\d+)/$",
        InviteConsumer.as_asgi(),
    ),
]
