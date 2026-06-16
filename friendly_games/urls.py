from django.urls import path
from . import views

app_name = 'friendly_games'

urlpatterns = [
    path('create/', views.create_game, name='create_game'),
    path('submit-score/', views.submit_score_list, name='submit_score_list'),  # NEW: List of games to submit scores
    path('<int:game_id>/', views.game_detail, name='game_detail'),
    path('join/', views.join_game, name='join_game'),
    path('api/game-preview/', views.game_preview_api, name='game_preview_api'),
    path('api/qr-resolve/', views.qr_resolve_player, name='qr_resolve_player'),
    path('<int:game_id>/start/', views.start_match, name='start_match'),
    path('<int:game_id>/submit-score/', views.submit_score, name='submit_score'),
    path('<int:game_id>/validate-result/', views.validate_result, name='validate_result'),
    path('<int:game_id>/check-codename/', views.check_codename, name='check_codename'),
    path('<int:game_id>/leave/', views.leave_game, name='leave_game'),
    path('<int:game_id>/rematch/', views.rematch, name='rematch'),
    path('<int:game_id>/status/', views.game_status_api, name='game_status_api'),
]

