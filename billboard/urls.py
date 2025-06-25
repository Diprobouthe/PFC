from django.urls import path
from . import views

app_name = 'billboard'

urlpatterns = [
    path('', views.BillboardListView.as_view(), name='list'),
    path('create/', views.BillboardCreateView.as_view(), name='create'),
    path('entry/<int:pk>/edit/', views.BillboardUpdateView.as_view(), name='edit'),
    path('entry/<int:pk>/delete/', views.BillboardDeleteView.as_view(), name='delete'),
    path('entry/<int:entry_id>/respond/', views.respond_to_entry, name='respond'),
    path('entry/<int:entry_id>/respond-match/', views.respond_to_match, name='respond_match'),
    path('api/search/', views.team_search_api, name='team_search_api'),
]

