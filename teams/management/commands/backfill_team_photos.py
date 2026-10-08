from django.core.management.base import BaseCommand, CommandError

from teams.models import TeamProfile
from teams.team_photo_utils import (
    TEAM_PHOTO_SIZES,
    generate_team_photo_variants,
    team_photo_variant_exists,
)


class Command(BaseCommand):
    help = "Generate lightweight WebP derivatives for existing Team photos."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Regenerate Team photo files even when both variants already exist.",
        )

    def handle(self, *args, **options):
        force = options["force"]
        profiles = (
            TeamProfile.objects.exclude(team_photo_jpg="")
            .exclude(team_photo_jpg__isnull=True)
            .select_related("team")
            .order_by("team_id")
        )

        generated = 0
        skipped = 0
        failed = 0

        for profile in profiles.iterator():
            if not force and all(
                team_photo_variant_exists(profile, size)
                for size in TEAM_PHOTO_SIZES
            ):
                skipped += 1
                continue

            try:
                generate_team_photo_variants(profile, force=True)
                generated += 1
            except Exception as exc:
                failed += 1
                self.stderr.write(
                    self.style.ERROR(
                        f"Team {profile.team_id} ({profile.team.name}): {exc}"
                    )
                )

        self.stdout.write(
            self.style.SUCCESS(
                "Team photo backfill complete: "
                f"generated={generated}, skipped={skipped}, failed={failed}"
            )
        )
        if failed:
            raise CommandError(
                f"Team photo backfill failed for {failed} profile(s)."
            )
