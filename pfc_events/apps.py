from django.apps import AppConfig


class PfcEventsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "pfc_events"
    verbose_name = "PFC Events (WebSocket)"
