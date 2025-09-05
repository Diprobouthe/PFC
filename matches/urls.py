from django.urls import path
from . import views
from . import views_scoreboard

urlpatterns = [
    path('', views.match_list, name='match_list'),
    path('<int:tournament_id>/', views.match_list, name='tournament_matches'),
    path('detail/<int:match_id>/', views.match_detail, name='match_detail'),
    path('activate/<int:match_id>/<int:team_id>/', views.match_activate, name='match_activate'),
    path('submit-result/<int:match_id>/<int:team_id>/', views.match_submit_result, name='match_submit_result'),
    path('validate-result/<int:match_id>/<int:team_id>/', views.match_validate_result, name='match_validate_result'),
    path('next-opponent/<int:tournament_id>/<int:team_id>/', views.request_next_opponent, name='next_opponent_request'),
    # path('respond-request/<int:request_id>/<int:team_id>/', views.respond_to_opponent_request, name='respond_to_opponent_request'), # Commented out - view does not exist
    
    # Live Scoreboard URLs
    path('live-scores/', views_scoreboard.live_scores_list, name='live_scores_list'),
    path('scoreboard/<int:scoreboard_id>/', views_scoreboard.scoreboard_detail, name='scoreboard_detail'),
    path('scoreboard/<int:scoreboard_id>/update/', views_scoreboard.update_scoreboard, name='update_scoreboard'),
    path('scoreboard/<int:scoreboard_id>/reset/', views_scoreboard.reset_scoreboard, name='reset_scoreboard'),
    path('scoreboard/<int:scoreboard_id>/embed/', views_scoreboard.scoreboard_embed, name='scoreboard_embed'),
    path('scoreboard/<int:scoreboard_id>/rate/', views_scoreboard.rate_scorekeeper, name='rate_scorekeeper'),
]
