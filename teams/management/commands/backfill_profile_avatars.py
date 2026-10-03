from django.core.management.base import BaseCommand, CommandError

from teams.avatar_utils import AVATAR_SIZES, generate_profile_avatar_variants, profile_avatar_exists
from teams.models import PlayerProfile


class Command(BaseCommand):
    help = "Generate small WebP avatar derivatives for existing player profile pictures."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Regenerate avatar files even when both expected variants already exist.",
        )

    def handle(self, *args, **options):
        force = options["force"]
        profiles = (
            PlayerProfile.objects.exclude(profile_picture="")
            .exclude(profile_picture__isnull=True)
            .select_related("player")
            .order_by("player_id")
        )

        generated = 0
        skipped = 0
        failed = 0

        for profile in profiles.iterator():
            if not force and all(profile_avatar_exists(profile, size) for size in AVATAR_SIZES):
                skipped += 1
                continue
            try:
                generate_profile_avatar_variants(profile, force=True)
                generated += 1
            except Exception as exc:
                failed += 1
                self.stderr.write(
                    self.style.ERROR(
                        f"Player {profile.player_id} ({profile.player.name}): {exc}"
                    )
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"Avatar backfill complete: generated={generated}, skipped={skipped}, failed={failed}"
            )
        )
        if failed:
            raise CommandError(f"Avatar backfill failed for {failed} profile(s).")
