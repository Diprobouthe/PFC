from django.urls import path
from . import views
from . import analytics_views
from . import presence_views
from . import court_analytics_api

app_name = 'billboard'

urlpatterns = [
    # Main billboard list
    path('', views.BillboardListView.as_view(), name='list'),
    path('create/', views.BillboardCreateView.as_view(), name='create'),
    path('entry/<int:pk>/edit/', views.BillboardUpdateView.as_view(), name='edit'),
    path('entry/<int:pk>/delete/', views.BillboardDeleteView.as_view(), name='delete'),
    path('entry/<int:entry_id>/respond/', views.respond_to_entry, name='respond'),
    path('entry/<int:entry_id>/respond-match/', views.respond_to_match, name='respond_match'),
    path('api/search/', views.team_search_api, name='team_search_api'),

    # ── One-tap presence API ──────────────────────────────────────────────────
    path('api/defaults/', presence_views.api_defaults, name='api_defaults'),
    path('api/im-here/', presence_views.api_im_here, name='api_im_here'),
    path('api/going/', presence_views.api_going, name='api_going'),
    path('api/leave/', presence_views.api_leave, name='api_leave'),

    # ── Court usage analytics API ─────────────────────────────────────────────
    path('api/analytics/summary/', court_analytics_api.api_analytics_summary, name='api_analytics_summary'),
    path('api/analytics/court/<int:court_id>/', court_analytics_api.api_analytics_court, name='api_analytics_court'),

    # Legacy analytics URLs (kept for backward compat)
    path('analytics/', analytics_views.analytics_dashboard, name='analytics_dashboard'),
    path('analytics/complex/<int:complex_id>/', analytics_views.complex_analytics, name='complex_analytics'),
    path('api/analytics/<int:complex_id>/', analytics_views.analytics_api, name='analytics_api'),
    path('api/heatmap/<int:complex_id>/', analytics_views.heatmap_api, name='heatmap_api'),
]
