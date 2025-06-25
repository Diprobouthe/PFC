from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from . import views
from . import auth_views

urlpatterns = [
    path('', views.home, name='home'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('admin/', admin.site.urls),
    path('tournaments/', include('tournaments.urls')),
    path('matches/', include('matches.urls')),
    path('teams/', include('teams.urls')),
    path('leaderboards/', include('leaderboards.urls')),
    path('courts/', include('courts.urls')),
    path('signin/', include('signin.urls')),
    path('friendly-games/', include('friendly_games.urls')),  # New parallel friendly games system
    path('billboard/', include('billboard.urls')),  # Billboard module for player activity declarations
    
    # Authentication URLs
    path('auth/login/', auth_views.codename_login, name='codename_login'),
    path('auth/logout/', auth_views.codename_logout, name='codename_logout'),
    path('auth/status/', auth_views.codename_status, name='codename_status'),
    path('auth/modal/', auth_views.quick_login_modal, name='quick_login_modal'),
    
    # Team PIN Authentication URLs
    path('auth/team/login/', auth_views.team_pin_login, name='team_pin_login'),
    path('auth/team/logout/', auth_views.team_pin_logout, name='team_pin_logout'),
    path('auth/team/status/', auth_views.team_pin_status, name='team_pin_status'),
    path('auth/team/modal/', auth_views.team_login_modal, name='team_login_modal'),
]

# Serve media files during development and production
if settings.DEBUG or True:  # Force media serving for sandbox/production
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
