"""
URL Configuration for Practice App
"""

from django.urls import path
from . import views

app_name = 'practice'

urlpatterns = [
    # Main practice pages
    path('', views.practice_home, name='practice_home'),
    path('shooting/', views.shooting_practice, name='shooting_practice'),
    path('pointing/', views.pointing_practice, name='pointing_practice'),
    
    # API endpoints for session management
    path('api/start-session/', views.start_session, name='start_session'),
    path('api/record-shot/', views.record_shot, name='record_shot'),
    path('api/undo-shot/', views.undo_last_shot, name='undo_shot'),
    path('api/end-session/', views.end_session, name='end_session'),
    
    # Session summary
    path('session/<uuid:session_id>/', views.session_summary, name='session_summary'),
    
    # Session history
    path('history/', views.session_history, name='session_history'),
]


