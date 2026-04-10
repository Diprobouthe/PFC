from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.views.static import serve
from . import views
from . import auth_views
from . import simple_creator
from . import my_matches_view
from . import smart_router

urlpatterns = [
    path('', views.home, name='home'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('my-matches/', smart_router.resolve_decision_url, name='my_active_matches'),
    path('my-matches/next-url/', smart_router.resolve_next_url, name='pfc_next_url'),
    path('my-matches/list/', smart_router.my_matches_list, name='my_matches_list'),
    path('my-matches/old/', my_matches_view.my_active_matches, name='my_active_matches_old'),
    path('admin/', admin.site.urls),
    path('tournaments/', include('tournaments.urls')),
    path('matches/', include('matches.urls')),
    path('teams/', include('teams.urls')),
    path('leaderboards/', include('leaderboards.urls')),
    path('courts/', include('courts.urls')),
    path('signin/', include('signin.urls')),
    path('friendly-games/', include('friendly_games.urls')),  # New parallel friendly games system
    path('billboard/', include('billboard.urls')),  # Billboard module for player activity declarations
    path('invites/', include('invites.urls')),  # Targeted invitation system

    # Shot Accuracy Tracker API
    path('api/shoot/', include('shooting.urls')),

    # Shooting Practice Module (v0.1)
    path('practice/', include('practice.urls')),

    # Simple Tournament Creator
    path('simple/', simple_creator.simple_creator_home, name='simple_creator_home'),
    path('simple/create/', simple_creator.create_simple_tournament, name='create_simple_tournament'),
    path('simple/success/', simple_creator.simple_creator_success, name='simple_creator_success'),
    path('simple/manage/<int:tournament_id>/', simple_creator.manage_tournament, name='manage_tournament'),
    path('simple/start/<int:tournament_id>/', simple_creator.start_tournament, name='start_tournament'),
    path('simple/courts/', simple_creator.get_available_courts, name='get_available_courts'),
    path('simple/validate-voucher/', simple_creator.validate_voucher, name='validate_voucher'),
    path('simple/cleanup/<int:tournament_id>/', simple_creator.cleanup_empty_mele_teams, name='cleanup_empty_mele_teams'),

    # Authentication URLs
    path('player-auth/', include('player_auth.urls')),  # New: Google + Email OTP auth
    path('auth/login/', auth_views.codename_login, name='codename_login'),
    path('auth/logout/', auth_views.codename_logout, name='codename_logout'),
    path('auth/status/', auth_views.codename_status, name='codename_status'),
    path('auth/modal/', auth_views.quick_login_modal, name='quick_login_modal'),

    # Team PIN Authentication URLs
    path('auth/team/login/', auth_views.team_pin_login, name='team_pin_login'),
    path('auth/team/logout/', auth_views.team_pin_logout, name='team_pin_logout'),
    path('auth/team/status/', auth_views.team_pin_status, name='team_pin_status'),
    path('auth/team/modal/', auth_views.team_login_modal, name='team_login_modal'),
    path('auth/team/check/', views.check_team_session, name='check_team_session'),
]

# ---------------------------------------------------------------------------
# Permanent explicit media-serving route.
# Uses django.views.static.serve directly so media files (player images,
# team logos, court photos, etc.) are always accessible regardless of the
# DEBUG setting or deployment environment (including Render production).
#
# IMPORTANT: Do NOT replace this with the static(...) helper — that helper
# is development-only and will not serve files when DEBUG=False.
# This re_path must remain in all future URL configurations.
# ---------------------------------------------------------------------------
urlpatterns += [
    re_path(r"^media/(?P<path>.*)$", serve, {
        "document_root": settings.MEDIA_ROOT,
    }),
]
