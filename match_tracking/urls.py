from django.urls import path
from . import views

app_name = 'match_tracking'

urlpatterns = [
    # Tournament match tracking page:  /track/match/<match_id>/
    path('<str:match_type>/<int:pk>/', views.tracking_page, name='tracking_page'),
    # Player shot stats API:           /track/match/<match_id>/player/<player_id>/stats/
    path('<str:match_type>/<int:pk>/player/<int:player_id>/stats/', views.player_stats_api, name='player_stats_api'),
    # Participant verification API:    /track/match/<match_id>/verify/
    path('<str:match_type>/<int:pk>/verify/', views.verify_participant, name='verify_participant'),
    # Shot recording API:               /track/match/<match_id>/shot/
    path('<str:match_type>/<int:pk>/shot/', views.record_shot, name='record_shot'),
    # Game status poll:                   /track/match/<match_id>/status/
    path('<str:match_type>/<int:pk>/status/', views.game_status_api, name='game_status_api'),
]
