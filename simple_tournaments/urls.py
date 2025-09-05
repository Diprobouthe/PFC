from django.urls import path
from . import views

app_name = 'simple_tournaments'

urlpatterns = [
    path('create/', views.tournament_create, name='create'),
    path('success/<int:pk>/', views.tournament_success, name='tournament_success'),
    path('check-voucher/', views.check_voucher, name='check_voucher'),
]

