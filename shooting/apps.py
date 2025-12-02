from django.apps import AppConfig


class ShootingConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'shooting'
    verbose_name = 'Shot Accuracy Tracker'
    
    def ready(self):
        """Import signals when app is ready"""
        try:
            import shooting.signals  # noqa F401
        except ImportError:
            pass
