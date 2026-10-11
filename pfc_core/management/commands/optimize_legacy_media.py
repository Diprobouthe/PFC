from __future__ import annotations

import io
import os
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from django.conf import settings
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from PIL import Image, ImageOps, UnidentifiedImageError

from courts.models import CourtComplexPhoto
from simple_creator.models import TournamentScenario
from teams.models import PlayerProfile, TeamProfile
from tournaments.models import Tournament


@dataclass(frozen=True)
class MediaSpec:
    label: str
    model: type
    field_name: str
    max_width: int
    max_height: int
    quality: int


MEDIA_SPECS = (
    MediaSpec("player_profile", PlayerProfile, "profile_picture", 720, 720, 78),
    MediaSpec("team_photo", TeamProfile, "team_photo_jpg", 960, 720, 78),
    MediaSpec("team_logo", TeamProfile, "logo_svg", 640, 640, 82),
    MediaSpec("court_photo", CourtComplexPhoto, "image", 960, 720, 78),
    MediaSpec("scenario_image", TournamentScenario, "image", 960, 720, 78),
    MediaSpec("tournament_banner", Tournament, "banner_image", 1200, 600, 80),
)


class Command(BaseCommand):
    help = (
        "Convert oversized DB-referenced legacy raster media to compact WebP files. "
        "SVG files are always skipped. Dry-run is the default; pass --apply to write."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Actually write optimized files, update DB paths, and remove replaced originals.",
        )
        parser.add_argument(
            "--threshold-kb",
            type=int,
            default=300,
            help="Only process source files larger than this size (default: 300 KB).",
        )

    def handle(self, *args, **options):
        apply_changes = bool(options["apply"])
        threshold_bytes = max(1, int(options["threshold_kb"])) * 1024

        if not hasattr(default_storage, "path"):
            raise CommandError(
                "This command requires local filesystem media storage because it performs "
                "verified atomic replacement on the mounted media disk."
            )

        media_root = Path(settings.MEDIA_ROOT).resolve()
        if not media_root.exists():
            raise CommandError(f"MEDIA_ROOT does not exist: {media_root}")

        referenced_paths = self._all_referenced_paths()
        processed_paths: set[str] = set()

        totals = {
            "candidates": 0,
            "optimized": 0,
            "would_optimize": 0,
            "skipped_small": 0,
            "skipped_svg": 0,
            "skipped_missing": 0,
            "skipped_collision": 0,
            "skipped_no_gain": 0,
            "failed": 0,
            "before_bytes": 0,
            "after_bytes": 0,
        }

        mode = "APPLY" if apply_changes else "DRY-RUN"
        self.stdout.write(
            self.style.WARNING(
                f"Legacy media optimizer: {mode}; threshold={threshold_bytes // 1024} KB"
            )
        )

        for spec in MEDIA_SPECS:
            field = spec.field_name
            queryset = (
                spec.model.objects.exclude(**{field: ""})
                .exclude(**{f"{field}__isnull": True})
                .only("pk", field)
                .order_by("pk")
            )

            for obj in queryset.iterator():
                field_file = getattr(obj, field)
                name = getattr(field_file, "name", "") or ""
                if not name or name in processed_paths:
                    continue
                processed_paths.add(name)

                suffix = PurePosixPath(name).suffix.lower()
                if suffix == ".svg":
                    totals["skipped_svg"] += 1
                    self.stdout.write(f"SKIP SVG       {name}")
                    continue

                try:
                    source_path = Path(default_storage.path(name)).resolve()
                except Exception as exc:
                    totals["failed"] += 1
                    self.stderr.write(f"ERROR PATH     {name}: {exc}")
                    continue

                try:
                    source_path.relative_to(media_root)
                except ValueError:
                    totals["failed"] += 1
                    self.stderr.write(f"ERROR OUTSIDE  {name}")
                    continue

                if not source_path.exists():
                    totals["skipped_missing"] += 1
                    self.stdout.write(f"SKIP MISSING   {name}")
                    continue

                before = source_path.stat().st_size
                if before <= threshold_bytes:
                    totals["skipped_small"] += 1
                    continue

                totals["candidates"] += 1

                new_name = str(PurePosixPath(name).with_suffix(".webp"))
                if new_name != name and new_name in referenced_paths:
                    totals["skipped_collision"] += 1
                    self.stderr.write(
                        f"SKIP COLLISION {name} -> {new_name} is already DB-referenced"
                    )
                    continue

                try:
                    payload, output_size = self._optimize_to_webp(source_path, spec)
                except (
                    UnidentifiedImageError,
                    OSError,
                    ValueError,
                    Image.DecompressionBombError,
                ) as exc:
                    totals["failed"] += 1
                    self.stderr.write(f"ERROR IMAGE    {name}: {exc}")
                    continue
                except Exception as exc:
                    totals["failed"] += 1
                    self.stderr.write(f"ERROR          {name}: {exc}")
                    continue

                if output_size >= before:
                    totals["skipped_no_gain"] += 1
                    self.stdout.write(
                        f"SKIP NO GAIN   {name}: {self._kb(before)} -> {self._kb(output_size)}"
                    )
                    continue

                totals["before_bytes"] += before
                totals["after_bytes"] += output_size

                if not apply_changes:
                    totals["would_optimize"] += 1
                    self.stdout.write(
                        f"WOULD OPTIMIZE [{spec.label}] {name} -> {new_name}: "
                        f"{self._kb(before)} -> {self._kb(output_size)}"
                    )
                    continue

                try:
                    self._commit_replacement(
                        spec=spec,
                        source_name=name,
                        source_path=source_path,
                        new_name=new_name,
                        payload=payload,
                    )
                except Exception as exc:
                    totals["failed"] += 1
                    self.stderr.write(f"ERROR COMMIT   {name}: {exc}")
                    continue

                totals["optimized"] += 1
                self.stdout.write(
                    self.style.SUCCESS(
                        f"OPTIMIZED [{spec.label}] {name} -> {new_name}: "
                        f"{self._kb(before)} -> {self._kb(output_size)}"
                    )
                )

        saved = totals["before_bytes"] - totals["after_bytes"]
        action_count = totals["optimized"] if apply_changes else totals["would_optimize"]
        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"{mode} complete: actionable={action_count}, "
                f"before={self._mb(totals['before_bytes'])}, "
                f"after={self._mb(totals['after_bytes'])}, "
                f"saved={self._mb(saved)}"
            )
        )
        self.stdout.write(
            "skipped: "
            f"svg={totals['skipped_svg']}, "
            f"small={totals['skipped_small']}, "
            f"missing={totals['skipped_missing']}, "
            f"collision={totals['skipped_collision']}, "
            f"no_gain={totals['skipped_no_gain']}; "
            f"failed={totals['failed']}"
        )

        if totals["failed"]:
            raise CommandError(
                f"Legacy media optimizer completed with {totals['failed']} failure(s)."
            )

    def _all_referenced_paths(self) -> set[str]:
        paths: set[str] = set()
        for spec in MEDIA_SPECS:
            field = spec.field_name
            values = (
                spec.model.objects.exclude(**{field: ""})
                .exclude(**{f"{field}__isnull": True})
                .values_list(field, flat=True)
            )
            paths.update(str(value) for value in values if value)
        return paths

    def _optimize_to_webp(self, source_path: Path, spec: MediaSpec) -> tuple[bytes, int]:
        with Image.open(source_path) as opened:
            if getattr(opened, "is_animated", False):
                raise ValueError("animated images are not supported")

            image = ImageOps.exif_transpose(opened)
            image.load()

            if image.mode not in ("RGB", "RGBA"):
                has_alpha = "A" in image.getbands()
                image = image.convert("RGBA" if has_alpha else "RGB")

            image.thumbnail(
                (spec.max_width, spec.max_height),
                Image.Resampling.LANCZOS,
            )

            output = io.BytesIO()
            image.save(
                output,
                format="WEBP",
                quality=spec.quality,
                method=6,
            )
            payload = output.getvalue()

        # Verify the generated bytes before touching production files/DB.
        with Image.open(io.BytesIO(payload)) as check:
            check.verify()

        return payload, len(payload)

    def _commit_replacement(
        self,
        *,
        spec: MediaSpec,
        source_name: str,
        source_path: Path,
        new_name: str,
        payload: bytes,
    ) -> None:
        destination_path = Path(default_storage.path(new_name)).resolve()
        media_root = Path(settings.MEDIA_ROOT).resolve()
        destination_path.relative_to(media_root)
        destination_path.parent.mkdir(parents=True, exist_ok=True)

        temp_path = destination_path.with_name(
            f".{destination_path.name}.tmp-{uuid.uuid4().hex}"
        )
        temp_path.write_bytes(payload)

        try:
            with Image.open(temp_path) as check:
                check.verify()

            # Place the verified optimized file first. The original remains intact
            # until every DB row that referenced it has been redirected.
            os.replace(temp_path, destination_path)

            with transaction.atomic():
                updated = spec.model.objects.filter(
                    **{spec.field_name: source_name}
                ).update(**{spec.field_name: new_name})
                if updated < 1:
                    raise RuntimeError(
                        f"No DB rows referenced {source_name}; refusing to delete original"
                    )

            # DB now points at a verified file. Removing the old source is the last step.
            if source_path != destination_path and source_path.exists():
                source_path.unlink()
        finally:
            if temp_path.exists():
                temp_path.unlink()

    @staticmethod
    def _kb(value: int) -> str:
        return f"{value / 1024:.1f} KB"

    @staticmethod
    def _mb(value: int) -> str:
        return f"{value / 1024 / 1024:.2f} MB"
