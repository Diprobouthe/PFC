import os
import sys

from django.apps import AppConfig
from django.conf import settings


class TournamentsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'tournaments'

    def ready(self):
        import tournaments.signals # Import signals to connect them
        # Tests drive lifecycle finalization explicitly; a clock against
        # Django's temporary test database would add nondeterminism.
        if (
            settings.TOURNAMENT_LINEUP_CLOCK_ENABLED
            and "manage.py" not in sys.argv[0]
            and os.environ.get("RUN_MAIN") != "false"
        ):
            from tournaments.lineup_clock import start_lineup_clock

            start_lineup_clock()
