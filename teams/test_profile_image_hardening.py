import io
import shutil
import tempfile
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from friendly_games.models import PlayerCodename
from teams.forms import PublicPlayerForm
from teams.image_utils import (
    PROFILE_IMAGE_MAX_BYTES,
    validate_profile_image_upload,
)
from teams.models import Player, PlayerProfile, Team


def make_image_upload(name="profile.jpg", *, fmt="JPEG", size=(320, 240)):
    buf = io.BytesIO()
    Image.new("RGB", size, (80, 120, 160)).save(buf, format=fmt)
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


class ProfileImageValidationTests(TestCase):
    def setUp(self):
        self.media_root = tempfile.mkdtemp(prefix="pfc-image-hardening-")
        self.override = override_settings(MEDIA_ROOT=self.media_root)
        self.override.enable()
        self.team = Team.objects.create(name="Image Hardening Team")
        self.player = Player.objects.create(name="Image Hardening Player", team=self.team)
        self.codename = PlayerCodename.objects.create(player=self.player, codename="IMG001")

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media_root, ignore_errors=True)

    def test_normal_jpeg_png_and_webp_are_accepted(self):
        for name, fmt in (
            ("normal.jpg", "JPEG"),
            ("normal.png", "PNG"),
            ("normal.webp", "WEBP"),
        ):
            with self.subTest(fmt=fmt):
                upload = make_image_upload(name, fmt=fmt)
                self.assertIs(validate_profile_image_upload(upload), upload)

    def test_common_4032x3024_phone_photo_dimensions_are_allowed(self):
        upload = make_image_upload()
        with patch(
            "teams.image_utils.Image.open",
            return_value=_MetadataOnlyImage(size=(4032, 3024)),
        ):
            self.assertIs(validate_profile_image_upload(upload), upload)

    def test_oversized_file_is_rejected_before_image_decode(self):
        upload = SimpleUploadedFile(
            "too-large.jpg",
            b"x" * (PROFILE_IMAGE_MAX_BYTES + 1),
            content_type="image/jpeg",
        )
        with patch("teams.image_utils.Image.open") as image_open:
            with self.assertRaises(ValidationError):
                validate_profile_image_upload(upload)
            image_open.assert_not_called()

    def test_excessive_dimensions_are_rejected_from_header_metadata(self):
        upload = make_image_upload()
        with patch(
            "teams.image_utils.Image.open",
            return_value=_MetadataOnlyImage(size=(8000, 6000)),
        ):
            with self.assertRaises(ValidationError):
                validate_profile_image_upload(upload)

    def test_corrupt_image_is_rejected(self):
        upload = SimpleUploadedFile(
            "broken.jpg",
            b"this is not an image",
            content_type="image/jpeg",
        )
        with self.assertRaises(ValidationError):
            validate_profile_image_upload(upload)

    def test_public_registration_form_uses_hardened_validator(self):
        upload = make_image_upload()
        with patch(
            "teams.forms.validate_profile_image_upload",
            wraps=validate_profile_image_upload,
        ) as validator:
            form = PublicPlayerForm(
                data={
                    "name": "New Player",
                    "codename": "NEW001",
                    "team_choice": "friendly",
                    "team_search": "",
                    "selected_team_id": "",
                    "team_pin": "",
                },
                files={"profile_picture": upload},
            )
            self.assertTrue(form.is_valid(), form.errors)
            validator.assert_called_once()

    def test_model_save_rejects_unsafe_uncommitted_upload_before_storage(self):
        upload = SimpleUploadedFile(
            "too-large.jpg",
            b"x" * (PROFILE_IMAGE_MAX_BYTES + 1),
            content_type="image/jpeg",
        )
        profile = PlayerProfile(player=self.player, profile_picture=upload)
        with self.assertRaises(ValidationError):
            profile.save()
        self.assertFalse(PlayerProfile.objects.filter(player=self.player).exists())

    def test_direct_profile_edit_rejects_unsafe_upload_without_replacing_picture(self):
        profile = PlayerProfile.objects.create(player=self.player)
        session = self.client.session
        session["player_codename"] = self.codename.codename
        session.save()

        upload = SimpleUploadedFile(
            "too-large.jpg",
            b"x" * (PROFILE_IMAGE_MAX_BYTES + 1),
            content_type="image/jpeg",
        )
        response = self.client.post(
            reverse("edit_player_profile"),
            {"action": "update_picture", "profile_picture": upload},
        )
        self.assertEqual(response.status_code, 302)
        profile.refresh_from_db()
        self.assertFalse(bool(profile.profile_picture))
