from django.urls import path
from . import views

urlpatterns = [
    path('', views.tournament_list, name='tournament_list'),
    path('<int:tournament_id>/', views.tournament_detail, name='tournament_detail'),
    path('create/', views.tournament_create, name='tournament_create'),
    path('<int:tournament_id>/update/', views.tournament_update, name='tournament_update'),
    path('<int:tournament_id>/assign-teams/', views.tournament_assign_teams, name='tournament_assign_teams'),
    path('<int:tournament_id>/archive/', views.tournament_archive, name='tournament_archive'),
    path('<int:tournament_id>/generate-matches/', views.generate_matches, name='generate_matches'),
    
    # Public registration URLs
    path('<int:tournament_id>/register/', views.tournament_register, name='tournament_register'),
    path('<int:tournament_id>/register/choice/', views.tournament_register_choice, name='tournament_register_choice'),
    path('<int:tournament_id>/register/subteams/', views.tournament_register_subteams, name='tournament_register_subteams'),
]
