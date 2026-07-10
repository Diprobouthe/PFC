from django.apps import AppConfig


class FriendlyGamesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'friendly_games'

    def ready(self):
        import friendly_games.signals  # noqa: F401 — registers post_save signal
