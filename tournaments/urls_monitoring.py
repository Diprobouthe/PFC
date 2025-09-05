"""
URL patterns for tournament automation monitoring
"""

from django.urls import path
from . import views_monitoring

urlpatterns = [
    # Main monitoring dashboard
    path('monitoring/', views_monitoring.automation_dashboard, name='automation_dashboard'),
    
    # Tournament-specific monitoring
    path('monitoring/<int:tournament_id>/', views_monitoring.tournament_detail_monitoring, name='tournament_monitoring'),
    
    # API endpoints
    path('monitoring/api/logs/', views_monitoring.automation_logs_api, name='automation_logs_api'),
    path('monitoring/api/logs/<int:tournament_id>/', views_monitoring.automation_logs_api, name='tournament_logs_api'),
    path('monitoring/api/status/', views_monitoring.tournament_status_api, name='tournament_status_api'),
    path('monitoring/api/status/<int:tournament_id>/', views_monitoring.tournament_status_api, name='tournament_status_detail_api'),
    
    # Control endpoints
    path('monitoring/control/<int:tournament_id>/', views_monitoring.AutomationControlView.as_view(), name='automation_control'),
    
    # Health and export
    path('monitoring/health/', views_monitoring.automation_health_check, name='automation_health'),
    path('monitoring/export/', views_monitoring.export_automation_logs, name='export_logs'),
    path('monitoring/export/<int:tournament_id>/', views_monitoring.export_automation_logs, name='export_tournament_logs'),
]

