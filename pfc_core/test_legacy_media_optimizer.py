import io
import shutil
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.test import TestCase
from PIL import Image

from teams.models import Team, TeamProfile


class LegacyMediaOptimizerTests(TestCase):
    def setUp(self):
        self.test_dir = Path(settings.MEDIA_ROOT) / "legacy_optimizer_test"
        self.test_dir.mkdir(parents=True, exist_ok=True)
        self.team = Team.objects.create(name="Legacy Optimizer Test")
        self.profile = TeamProfile.objects.get(team=self.team)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _write_large_jpeg(self, name="large.jpg"):
        path = self.test_dir / name
        image = Image.new("RGB", (1600, 1200))
        # Add enough variation that the source is safely above the tiny test threshold.
        pixels = image.load()
        for y in range(0, 1200, 20):
            for x in range(0, 1600, 20):
                value = ((x // 20) * 13 + (y // 20) * 29) % 256
                for yy in range(y, min(y + 20, 1200)):
                    for xx in range(x, min(x + 20, 1600)):
                        pixels[xx, yy] = (value, (value * 3) % 256, (value * 7) % 256)
        image.save(path, format="JPEG", quality=96)
        return f"legacy_optimizer_test/{name}", path

    def test_default_mode_is_dry_run_and_does_not_modify_storage_or_db(self):
        rel, source = self._write_large_jpeg()
        TeamProfile.objects.filter(pk=self.profile.pk).update(team_photo_jpg=rel)

        call_command("optimize_legacy_media", threshold_kb=1)

        self.profile.refresh_from_db()
        self.assertEqual(self.profile.team_photo_jpg.name, rel)
        self.assertTrue(source.exists())
        self.assertFalse(source.with_suffix(".webp").exists())

    def test_apply_writes_verified_webp_updates_db_then_removes_original(self):
        rel, source = self._write_large_jpeg()
        TeamProfile.objects.filter(pk=self.profile.pk).update(team_photo_jpg=rel)
        before = source.stat().st_size

        call_command("optimize_legacy_media", threshold_kb=1, apply=True)

        self.profile.refresh_from_db()
        new_rel = self.profile.team_photo_jpg.name
        self.assertEqual(new_rel, "legacy_optimizer_test/large.webp")
        destination = Path(settings.MEDIA_ROOT) / new_rel
        self.assertTrue(destination.exists())
        self.assertFalse(source.exists())
        self.assertLess(destination.stat().st_size, before)

        with Image.open(destination) as image:
            self.assertEqual(image.format, "WEBP")
            self.assertLessEqual(image.width, 960)
            self.assertLessEqual(image.height, 720)

    def test_svg_is_always_skipped_even_with_apply(self):
        rel = "legacy_optimizer_test/large.svg"
        source = Path(settings.MEDIA_ROOT) / rel
        source.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">'
            '<rect width="10" height="10"/></svg>' + (" " * 5000),
            encoding="utf-8",
        )
        TeamProfile.objects.filter(pk=self.profile.pk).update(logo_svg=rel)

        call_command("optimize_legacy_media", threshold_kb=1, apply=True)

        self.profile.refresh_from_db()
        self.assertEqual(self.profile.logo_svg.name, rel)
        self.assertTrue(source.exists())
        self.assertFalse(source.with_suffix(".webp").exists())
