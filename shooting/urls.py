"""
URL configuration for Shot Accuracy Tracker API
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

# Create router for ViewSets
router = DefaultRouter()
router.register(r'sessions', views.ShotSessionViewSet, basename='shotsession')

app_name = 'shooting'

urlpatterns = [
    # API base path: /api/shoot/
    
    # ViewSet routes (sessions CRUD + actions)
    path('', include(router.urls)),
    
    # Additional function-based view endpoints
    path('active-session/', views.active_session, name='active-session'),
    path('user-stats/', views.UserStatsView.as_view(), name='user-stats'),
    path('achievements/', views.AchievementListView.as_view(), name='achievements'),
    path('matches/<uuid:match_id>/sessions/', views.match_sessions, name='match-sessions'),
    path('end-all-sessions/', views.end_all_active_sessions, name='end-all-sessions'),
]
