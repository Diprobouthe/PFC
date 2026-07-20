"""
expire_stale_match_presence
===========================
Management command that finds tournament matches stuck in ``status='active'``
longer than a configurable threshold (default: 6 hours) and performs a safe,
idempotent cleanup:

1. Deactivates all game-generated BillboardEntry presence records for the
   stale match (``is_active=False``).  No post-game grace entries are created
   — the match was never properly finished, so players are simply no longer
   visible.

2. Releases the court held by the stale match:
   - Checks that no *other* currently-active match is using the same court.
   - If the court is free, sets ``court.is_available = True``.
   - Clears the ``match.court`` FK so the court is no longer associated with
     the stale match.

3. Marks the stale match as ``cancelled`` (the correct non-result terminal
   status in Match.STATUS_CHOICES).  The match is never marked ``completed``
   because no result was submitted or validated.

4. Does NOT affect standings, scores, or any tournament progression logic.

Usage
-----
    # Preview — no changes made
    python manage.py expire_stale_match_presence --dry-run

    # Run with default 6-hour threshold
    python manage.py expire_stale_match_presence

    # Custom threshold (e.g. 4 hours)
    python manage.py expire_stale_match_presence --max-age-hours 4

Recommended: run every 30 minutes via Render Cron Job.
"""

import logging
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

logger = logging.getLogger(__name__)

# A real petanque match cannot last more than 6 hours.
DEFAULT_MAX_AGE_HOURS = 6


class Command(BaseCommand):
    help = (
        "Cancel stale active matches (no result submitted), release their courts, "
        "and deactivate their game-generated presence entries."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--max-age-hours",
            type=float,
            default=DEFAULT_MAX_AGE_HOURS,
            help=(
                f"Matches active for longer than this many hours are considered "
                f"stale (default: {DEFAULT_MAX_AGE_HOURS})."
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Preview what would be cleaned up without making any changes.",
        )

    def handle(self, *args, **options):
        max_age_hours = options["max_age_hours"]
        dry_run = options["dry_run"]

        from matches.models import Match

        cutoff = timezone.now() - timedelta(hours=max_age_hours)

        stale_matches = (
            Match.objects.filter(
                status="active",
                start_time__lt=cutoff,
            )
            .select_related("court", "tournament")
            .order_by("start_time")
        )

        total = stale_matches.count()

        if total == 0:
            self.stdout.write(
                self.style.SUCCESS(
                    f"No stale active matches found (threshold: {max_age_hours}h). "
                    "Nothing to do."
                )
            )
            return

        prefix = "[DRY RUN] " if dry_run else ""
        self.stdout.write(
            self.style.WARNING(
                f"{prefix}Found {total} stale active match(es) "
                f"(threshold: {max_age_hours}h):"
            )
        )

        now = timezone.now()
        cleaned = 0

        for match in stale_matches:
            age_hours = (now - match.start_time).total_seconds() / 3600
            court_info = (
                f"court_id={match.court_id} ({match.court.name})"
                if match.court_id
                else "no court"
            )
            self.stdout.write(
                f"  match id={match.id}  tournament={match.tournament_id}  "
                f"age={age_hours:.1f}h  {court_info}"
            )

            if dry_run:
                continue

            # ── 1. Deactivate presence (skip post-game grace) ────────────────
            try:
                from matches.views import _deactivate_match_presence

                _deactivate_match_presence(match, skip_grace=True)
                self.stdout.write(
                    self.style.SUCCESS(
                        f"    ✓ Presence deactivated (no grace entries created)"
                    )
                )
            except Exception as exc:
                logger.error(
                    f"expire_stale_match_presence: presence deactivation failed "
                    f"for match {match.id}: {exc}",
                    exc_info=True,
                )
                self.stdout.write(
                    self.style.WARNING(
                        f"    ⚠ Presence deactivation failed: {exc}"
                    )
                )

            # ── 2. Release the court ─────────────────────────────────────────
            if match.court_id:
                court = match.court
                # Only mark available if no other active match is using this court.
                other_active = (
                    Match.objects.filter(status="active", court=court)
                    .exclude(id=match.id)
                    .exists()
                )
                if not other_active:
                    court.is_available = True
                    court.save(update_fields=["is_available"])
                    logger.info(
                        f"expire_stale_match_presence: court {court.id} "
                        f"({court.name}) released by stale match {match.id}."
                    )
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"    ✓ Court {court.id} ({court.name}) → is_available=True"
                        )
                    )
                else:
                    self.stdout.write(
                        self.style.WARNING(
                            f"    ⚠ Court {court.id} still used by another active "
                            f"match — not marking available."
                        )
                    )

            # ── 3. Cancel the match ──────────────────────────────────────────
            # Use 'cancelled' — the correct non-result terminal status in
            # Match.STATUS_CHOICES.  Never use 'completed' here because no
            # result was submitted or validated.
            match.status = "cancelled"
            match.court = None  # clear the FK so the court is fully released
            match.save(update_fields=["status", "court"])
            logger.info(
                f"expire_stale_match_presence: match {match.id} → cancelled "
                f"(was active for {age_hours:.1f}h with no result submitted)."
            )
            self.stdout.write(
                self.style.SUCCESS(f"    ✓ Match {match.id} → status=cancelled")
            )
            cleaned += 1

        if not dry_run:
            self.stdout.write(
                self.style.SUCCESS(
                    f"\nDone. Cancelled {cleaned} stale match(es) and released their courts."
                )
            )
        else:
            self.stdout.write(
                self.style.WARNING(
                    f"\n[DRY RUN] Would cancel {total} stale match(es) and release "
                    f"their courts. Run without --dry-run to apply."
                )
            )
