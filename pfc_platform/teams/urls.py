from django.urls import path
from . import views

urlpatterns = [
    path('', views.team_list, name='team_list'),
    path('<int:team_id>/', views.team_detail, name='team_detail'),
    path('create/', views.team_create, name='team_create'),
    path('<int:team_id>/update/', views.team_update, name='team_update'),
    path('<int:team_id>/player/add/', views.player_create, name='player_create'),
    path('player/<int:player_id>/update/', views.player_update, name='player_update'),
    path('player/<int:player_id>/delete/', views.player_delete, name='player_delete'),
    path('<int:team_id>/availability/add/', views.team_availability_create, name='team_availability_create'),
    path('<int:team_id>/pin/', views.show_team_pin, name='show_team_pin'),
    path('login/', views.team_login, name='team_login'),
]
