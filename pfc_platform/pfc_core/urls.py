from django.contrib import admin
from django.urls import path, include
from . import views

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
]
