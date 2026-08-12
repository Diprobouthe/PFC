"""
invites/urls.py
===============
HTTP URL patterns for the PFC invitation system.
Mounted at /invites/ in pfc_core/urls.py.
"""
from django.urls import path
from . import views

app_name = "invites"

urlpatterns = [
    # Hub page
    path("", views.invite_hub, name="hub"),

    # Actions
    path("send/", views.send_invite, name="send"),
    path("<uuid:token>/accept/", views.accept_invite, name="accept"),
    path("<uuid:token>/reject/", views.reject_invite, name="reject"),

    # JSON endpoints
    path("inbox/", views.inbox, name="inbox"),
    path("session/<uuid:token>/", views.session_status, name="session_status"),
    path("players/search/", views.player_search, name="player_search"),
    path("qr-add-player/", views.qr_add_player, name="qr_add_player"),
    path("qr-start-session/", views.qr_start_session, name="qr_start_session"),
]
