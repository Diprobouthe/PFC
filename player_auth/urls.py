from django.urls import path
from . import views

app_name = 'player_auth'

urlpatterns = [
    # Main login page
    path('login/', views.login_page, name='login'),
    path('logout/', views.logout, name='logout'),

    # Google OAuth
    path('google/', views.google_login, name='google_login'),
    path('google/callback/', views.google_callback, name='google_callback'),

    # Email OTP
    path('email/', views.email_login, name='email_login'),
    path('email/verify/', views.email_verify, name='email_verify'),

    # Legacy player linking
    path('link/', views.link_player, name='link'),
    path('link/skip/', views.link_skip, name='link_skip'),
]
