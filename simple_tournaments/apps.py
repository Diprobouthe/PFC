from django.apps import AppConfig


class SimpleTournamentsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'simple_tournaments'
    verbose_name = 'Simple Tournament Creation'
    
    def ready(self):
        # Create default scenarios when app is ready
        try:
            from .models import create_default_scenarios
            create_default_scenarios()
        except Exception:
            # Ignore errors during migrations
            pass

