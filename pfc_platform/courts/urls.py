from django.urls import path
from . import views

urlpatterns = [
    path('', views.court_list, name='court_list'),
    path('<int:court_id>/', views.court_detail, name='court_detail'),
    path('assign/<int:match_id>/', views.assign_court, name='assign_court'),
]
