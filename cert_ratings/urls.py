from django.urls import path
from . import views

app_name = "cert_ratings"

urlpatterns = [
    path(
        "players/<int:player_id>/cert-ratings/",
        views.player_cert_ratings,
        name="player_cert_ratings",
    ),
]
