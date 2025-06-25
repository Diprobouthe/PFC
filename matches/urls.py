from django.urls import path
from . import views

urlpatterns = [
    path('', views.match_list, name='match_list'),
    path('<int:tournament_id>/', views.match_list, name='tournament_matches'),
    path('detail/<int:match_id>/', views.match_detail, name='match_detail'),
    path('activate/<int:match_id>/<int:team_id>/', views.match_activate, name='match_activate'),
    path('submit-result/<int:match_id>/<int:team_id>/', views.match_submit_result, name='match_submit_result'),
    path('validate-result/<int:match_id>/<int:team_id>/', views.match_validate_result, name='match_validate_result'),
    path('next-opponent/<int:tournament_id>/<int:team_id>/', views.request_next_opponent, name='next_opponent_request'),
    # path('respond-request/<int:request_id>/<int:team_id>/', views.respond_to_opponent_request, name='respond_to_opponent_request'), # Commented out - view does not exist
]
