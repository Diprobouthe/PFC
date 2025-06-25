from django.urls import path
from . import views

urlpatterns = [
    path('', views.leaderboard_index, name='leaderboard_index'),
    path('tournament/<int:tournament_id>/', views.tournament_leaderboard, name='tournament_leaderboard'),
    path('team/<int:team_id>/', views.team_statistics, name='team_statistics'),
    path('match/<int:match_id>/', views.match_statistics, name='match_statistics'),
]
