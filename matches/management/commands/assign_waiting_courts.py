from django.core.management.base import BaseCommand

from matches.lifecycle import promote_one_waiting_match


class Command(BaseCommand):
    help = "Assign available courts to verified tournament matches waiting for a court"

    def handle(self, *args, **options):
        assigned_count = 0
        while True:
            outcome = promote_one_waiting_match()
            if outcome is None:
                break
            assigned_count += 1
            self.stdout.write(
                self.style.SUCCESS(
                    f"Assigned Court {outcome.court_id} to Match {outcome.match_id} and activated it"
                )
            )

        if assigned_count:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Successfully assigned courts to {assigned_count} waiting match(es)."
                )
            )
        else:
            self.stdout.write(self.style.WARNING("No waiting Match could claim an available Court."))
