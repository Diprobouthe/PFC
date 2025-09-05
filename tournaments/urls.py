from django.urls import path, include
from . import views

urlpatterns = [
    path('', views.tournament_list, name='tournament_list'),
    path('<int:tournament_id>/', views.tournament_detail, name='tournament_detail'),
    path('<int:tournament_id>/overview/', views.tournament_overview, name='tournament_overview'),
    path('create/', views.tournament_create, name='tournament_create'),
    path('<int:tournament_id>/update/', views.tournament_update, name='tournament_update'),
    path('<int:tournament_id>/assign_teams/', views.tournament_assign_teams, name='tournament_assign_teams'),
    path('<int:tournament_id>/archive/', views.tournament_archive, name='tournament_archive'),
    path('<int:tournament_id>/generate_matches/', views.generate_matches, name='generate_matches'),
    path('<int:tournament_id>/register/', views.tournament_register, name='tournament_register'),
    path('<int:tournament_id>/register/choice/', views.tournament_register_choice, name='tournament_register_choice'),
    path('<int:tournament_id>/register/subteams/', views.tournament_register_subteams, name='tournament_register_subteams'),
    
    # Mêlée Mode URLs
    path('<int:tournament_id>/register/melee/', views.tournament_register_melee, name='tournament_register_melee'),
    path('<int:tournament_id>/melee/status/', views.tournament_melee_status, name='tournament_melee_status'),
    path('<int:tournament_id>/melee/generate/', views.tournament_generate_melee_teams, name='tournament_generate_melee_teams'),
    path('<int:tournament_id>/melee/restore/', views.tournament_restore_melee_players, name='tournament_restore_melee_players'),
    path('<int:tournament_id>/melee/check_completion/', views.tournament_check_completion, name='tournament_check_completion'),
    
    # Include monitoring URLs
    path('', include('tournaments.urls_monitoring')),
]
