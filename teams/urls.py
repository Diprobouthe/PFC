from django.urls import path
from . import views
from . import api_views

urlpatterns = [
    path('', views.team_list, name='team_list'),
    path('create/', views.team_create, name='team_create'),
    path('<int:team_id>/', views.team_detail, name='team_detail'),
    path('login/', views.team_login, name='team_login'),
    path('matches/', views.team_matches, name='team_matches'),
    path('submit-score/', views.team_submit_score, name='team_submit_score'),
    path('players/leaderboard/', views.player_leaderboard, name='player_leaderboard'),
    path('players/friendly-leaderboard/', views.friendly_games_leaderboard, name='friendly_games_leaderboard'),
    path('players/<int:player_id>/', views.player_profile, name='player_profile'),
    path('players/create/', views.public_player_create, name='public_player_create'),
    path('players/login/', views.player_login, name='player_login'),
    path('api/search/', views.team_search_api, name='team_search_api'),
    path('api/player-lookup/', api_views.player_lookup_api, name='player_lookup_api'),
    path('<int:team_id>/pin/', views.show_team_pin, name='show_team_pin'),
]

