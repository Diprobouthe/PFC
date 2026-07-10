"""
matches/management/commands/expire_stale_match_presence.py
===========================================================
Management command that finds tournament matches that have been stuck in
'active' status for longer than a configurable threshold and deactivates
their billboard presence entries.

This is a PRESENCE-ONLY cleanup command.  It does NOT change match status.
Match status changes are the responsibility of the normal result-submission
flow.  This command only ensures that orphaned presence entries (created when
the match was activated) are closed so they do not show phantom players on
the Billboard and home page.

Usage:
    python manage.py expire_stale_match_presence
    python manage.py expire_stale_match_presence --max-age-hours 4
    python manage.py expire_stale_match_presence --dry-run

Recommended: run every 30–60 minutes via cron or Render Cron Job.
"""
import logging
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from matches.models import Match

logger = logging.getLogger(__name__)

# Default: a match active for longer than this is considered stale.
# A real petanque match cannot last more than 6 hours.
DEFAULT_MAX_AGE_HOURS = 6


class Command(BaseCommand):
    help = (
        "Deactivate billboard presence entries for tournament matches that have "
        "been stuck in 'active' status for too long (presence-only cleanup, "
        "does not change match status)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--max-age-hours",
            type=float,
            default=DEFAULT_MAX_AGE_HOURS,
            help=(
                f"Matches active for longer than this many hours will have their "
                f"presence deactivated (default: {DEFAULT_MAX_AGE_HOURS})."
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be done without making any changes.",
        )

    def handle(self, *args, **options):
        max_age_hours = options["max_age_hours"]
        dry_run = options["dry_run"]

        now = timezone.now()
        cutoff = now - timedelta(hours=max_age_hours)

        # Find matches that are still 'active' but were activated (start_time set)
        # more than max_age_hours ago.
        stale_matches = Match.objects.filter(
            status="active",
            start_time__lt=cutoff,
        ).select_related("court")

        total = stale_matches.count()

        if total == 0:
            self.stdout.write(
                self.style.SUCCESS("No stale active matches found. Nothing to do.")
            )
            return

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f"[DRY RUN] Would deactivate presence for {total} stale match(es):"
                )
            )
            for m in stale_matches:
                age_h = (now - m.start_time).total_seconds() / 3600
                self.stdout.write(
                    f"  match id={m.id} tournament={m.tournament} "
                    f"start_time={m.start_time} age={age_h:.1f}h"
                )
            return

        # Import here to avoid circular imports at module load time.
        from matches.views import _deactivate_match_presence

        deactivated_matches = 0
        deactivated_entries = 0

        for match in stale_matches:
            age_h = (now - match.start_time).total_seconds() / 3600
            try:
                from billboard.models import BillboardEntry
                before = BillboardEntry.objects.filter(
                    game_ref=f"match:{match.id}",
                    is_active=True,
                ).count()

                _deactivate_match_presence(match)

                after = BillboardEntry.objects.filter(
                    game_ref=f"match:{match.id}",
                    is_active=True,
                ).count()

                closed = before - after
                deactivated_entries += closed
                deactivated_matches += 1

                self.stdout.write(
                    f"  match id={match.id} age={age_h:.1f}h: "
                    f"closed {closed} presence entry/entries"
                )
                logger.info(
                    f"expire_stale_match_presence: match {match.id} "
                    f"(age={age_h:.1f}h) — closed {closed} presence entries"
                )
            except Exception as exc:
                self.stderr.write(
                    self.style.ERROR(
                        f"  ERROR processing match {match.id}: {exc}"
                    )
                )
                logger.error(
                    f"expire_stale_match_presence: error on match {match.id}: {exc}"
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. Deactivated presence for {deactivated_matches} match(es), "
                f"{deactivated_entries} entry/entries total."
            )
        )
