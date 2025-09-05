from django.urls import path
from . import views

app_name = 'simple_creator'

urlpatterns = [
    # Main pages
    path('', views.simple_tournament_home, name='home'),
    path('create/', views.create_tournament, name='create'),
    path('tournaments/', views.tournament_list, name='list'),
    path('tournaments/<int:pk>/', views.tournament_detail, name='detail'),
    path('tournaments/<int:pk>/success/', views.tournament_success, name='tournament_success'),
    
    # AJAX endpoints
    path('api/scenario/<int:scenario_id>/', views.scenario_details, name='scenario_details'),
    path('api/validate-voucher/', views.validate_voucher, name='validate_voucher'),
]

