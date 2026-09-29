from django.core.management.base import BaseCommand, CommandError

from matches.lifecycle import retry_failed_tournament_transitions


class Command(BaseCommand):
    help = (
        "Retry pending or failed tournament Match lifecycle transitions. "
        "This is an explicit operational command; it does not run as a worker."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--tournament-id",
            type=int,
            help="Retry only transitions for one tournament.",
        )

    def handle(self, *args, **options):
        tournament_id = options.get("tournament_id")
        if tournament_id is not None and tournament_id <= 0:
            raise CommandError("--tournament-id must be a positive integer.")
        succeeded = retry_failed_tournament_transitions(tournament_id=tournament_id)
        self.stdout.write(
            self.style.SUCCESS(f"Completed {succeeded} tournament lifecycle transition retry/retries.")
        )
