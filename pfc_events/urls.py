from django.urls import path

from . import push_views

app_name = "pfc_events"

urlpatterns = [
    path("push/config/", push_views.push_config, name="push_config"),
    path("push/subscribe/", push_views.subscribe, name="push_subscribe"),
    path("push/unsubscribe/", push_views.unsubscribe, name="push_unsubscribe"),
]
