from django.apps import AppConfig


class SimpleCreatorConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'simple_creator'
    verbose_name = 'Simple Tournament Creator'
    
    def ready(self):
        """Initialize app when Django starts"""
        # Import signals to register them
        from . import signals
