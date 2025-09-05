from django.urls import path
from . import views

urlpatterns = [
    path('', views.tournament_signin_list, name='tournament_signin_list'),
    path('signin/', views.tournament_signin, name='tournament_signin'),
    path('dashboard/<int:team_id>/<int:tournament_id>/', views.team_tournament_dashboard, name='team_tournament_dashboard'),
    path('signout/<int:team_id>/<int:tournament_id>/', views.tournament_signout, name='tournament_signout'),
]
