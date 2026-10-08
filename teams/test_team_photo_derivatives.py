import io
import shutil
import tempfile
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.template.loader import get_template
from django.test import TestCase, override_settings
from PIL import Image

from teams.forms import TeamProfileForm
from teams.models import Team, TeamProfile
from teams.team_photo_utils import (
    TEAM_PHOTO_SIZES,
    generate_team_photo_variants,
    team_photo_variant_name,
    team_photo_variant_url,
    validate_team_photo_upload,
)


def make_upload(
    name="team.jpg",
    *,
    fmt="JPEG",
    size=(1600, 1200),
    quality=95,
    color=(90, 120, 150),
):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format=fmt, quality=quality)
    content_type = {
        "JPEG": "image/jpeg",
        "PNG": "image/png",
        "WEBP": "image/webp",
    }[fmt]
    return SimpleUploadedFile(name, buf.getvalue(), content_type=content_type)


class _MetadataOnlyImage:
    def __init__(self, *, size, fmt="JPEG"):
        self.size = size
        self.format = fmt

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def verify(self):
        return None


class TeamPhotoDerivativeTests(TestCase):
    def setUp(self):
        self.media_root = tempfile.mkdtemp(prefix="pfc-team-photo-test-")
        self.override = override_settings(MEDIA_ROOT=self.media_root)
        self.override.enable()
        self.team = Team.objects.create(name="Team Photo Test")
        self.profile = TeamProfile.objects.get(team=self.team)

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media_root, ignore_errors=True)

    def test_new_team_photo_keeps_original_and_generates_webp_variants(self):
        self.profile.team_photo_jpg = make_upload(size=(1600, 1200))
        self.profile.save()

        with self.profile.team_photo_jpg.storage.open(
            self.profile.team_photo_jpg.name, "rb"
        ) as source:
            with Image.open(source) as original:
                self.assertEqual(original.size, (1600, 1200))

        for size in TEAM_PHOTO_SIZES:
            variant_name = team_photo_variant_name(self.profile, size)
            self.assertTrue(self.profile.team_photo_jpg.storage.exists(variant_name))
            with self.profile.team_photo_jpg.storage.open(variant_name, "rb") as source:
                with Image.open(source) as variant:
                    self.assertEqual(variant.format, "WEBP")
                    self.assertLessEqual(max(variant.size), size)
            self.assertEqual(
                team_photo_variant_url(self.profile, size),
                self.profile.team_photo_jpg.storage.url(variant_name),
            )

    def test_replacing_team_photo_regenerates_derivatives(self):
        self.profile.team_photo_jpg = make_upload(size=(1200, 900))
        self.profile.save()
        variant_name = team_photo_variant_name(self.profile, 400)
        with self.profile.team_photo_jpg.storage.open(variant_name, "rb") as source:
            before = source.read()

        self.profile.team_photo_jpg = make_upload(
            name="replacement.jpg",
            size=(1200, 900),
            quality=80,
            color=(180, 60, 40),
        )
        self.profile.save()

        with self.profile.team_photo_jpg.storage.open(variant_name, "rb") as source:
            after = source.read()
        self.assertNotEqual(before, after)

    def test_backfill_generates_variants_for_legacy_png_source(self):
        stored = self.profile.team_photo_jpg.storage.save(
            "team_photos/legacy-team.png",
            make_upload(name="legacy-team.png", fmt="PNG", size=(1400, 900)),
        )
        TeamProfile.objects.filter(pk=self.profile.pk).update(team_photo_jpg=stored)
        self.profile.refresh_from_db()

        for size in TEAM_PHOTO_SIZES:
            self.assertFalse(
                self.profile.team_photo_jpg.storage.exists(
                    team_photo_variant_name(self.profile, size)
                )
            )

        call_command("backfill_team_photos")

        for size in TEAM_PHOTO_SIZES:
            self.assertTrue(
                self.profile.team_photo_jpg.storage.exists(
                    team_photo_variant_name(self.profile, size)
                )
            )

    def test_team_photo_validator_rejects_excessive_dimensions_before_decode(self):
        upload = make_upload(size=(320, 240))
        with patch(
            "teams.team_photo_utils.Image.open",
            return_value=_MetadataOnlyImage(size=(8000, 6000)),
        ):
            with self.assertRaises(ValidationError):
                validate_team_photo_upload(upload)

    def test_team_photo_form_uses_hardened_validator(self):
        upload = make_upload(size=(1000, 750))
        with patch(
            "teams.forms.validate_team_photo_upload",
            wraps=validate_team_photo_upload,
        ) as validator:
            form = TeamProfileForm(
                data={
                    "description": "",
                    "motto": "",
                    "founded_date": "",
                    "profile_type": "full",
                },
                files={"team_photo_jpg": upload},
                instance=self.profile,
            )
            self.assertTrue(form.is_valid(), form.errors)
            validator.assert_called_once()

    def test_templates_compile_with_team_photo_tag(self):
        for template_name in (
            "teams/team_list.html",
            "teams/team_detail.html",
            "teams/team_login.html",
        ):
            with self.subTest(template=template_name):
                get_template(template_name)

    def test_generator_does_not_require_model_save(self):
        stored = self.profile.team_photo_jpg.storage.save(
            "team_photos/manual.jpg",
            make_upload(name="manual.jpg", size=(1000, 700)),
        )
        TeamProfile.objects.filter(pk=self.profile.pk).update(team_photo_jpg=stored)
        self.profile.refresh_from_db()
        generated = generate_team_photo_variants(self.profile, force=True)
        self.assertEqual(set(generated), set(TEAM_PHOTO_SIZES))
