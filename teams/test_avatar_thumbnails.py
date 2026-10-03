import io
import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.template.loader import get_template
from django.test import TestCase, override_settings
from PIL import Image

from teams.avatar_utils import AVATAR_SIZES, profile_avatar_name, profile_avatar_url
from teams.models import Player, PlayerProfile, Team


class PlayerAvatarDerivativeTests(TestCase):
    def setUp(self):
        self.media_root = tempfile.mkdtemp(prefix="pfc-avatar-test-")
        self.override = override_settings(MEDIA_ROOT=self.media_root)
        self.override.enable()
        self.team = Team.objects.create(name="Avatar Test Team")
        self.player = Player.objects.create(name="Avatar Test Player", team=self.team)

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media_root, ignore_errors=True)

    @staticmethod
    def _upload(name="portrait.jpg", size=(1200, 900), color=(80, 120, 160)):
        buf = io.BytesIO()
        Image.new("RGB", size, color).save(buf, format="JPEG", quality=95)
        return SimpleUploadedFile(name, buf.getvalue(), content_type="image/jpeg")

    def test_new_upload_keeps_original_and_generates_small_webp_variants(self):
        profile = PlayerProfile.objects.create(
            player=self.player,
            profile_picture=self._upload(),
        )

        with profile.profile_picture.storage.open(profile.profile_picture.name, "rb") as source:
            with Image.open(source) as original:
                self.assertEqual(original.size, (1200, 900))

        for size in AVATAR_SIZES:
            variant = profile_avatar_name(profile, size)
            self.assertTrue(profile.profile_picture.storage.exists(variant))
            with profile.profile_picture.storage.open(variant, "rb") as source:
                with Image.open(source) as avatar:
                    self.assertEqual(avatar.size, (size, size))
                    self.assertEqual(avatar.format, "WEBP")
            self.assertEqual(profile_avatar_url(profile, size), profile.profile_picture.storage.url(variant))

    def test_replacing_picture_regenerates_existing_avatar_files(self):
        profile = PlayerProfile.objects.create(
            player=self.player,
            profile_picture=self._upload(color=(220, 20, 20)),
        )
        variant = profile_avatar_name(profile, 96)
        with profile.profile_picture.storage.open(variant, "rb") as source:
            before = source.read()

        profile.profile_picture = self._upload(name="replacement.jpg", color=(20, 180, 40))
        profile.save()

        with profile.profile_picture.storage.open(variant, "rb") as source:
            after = source.read()
        self.assertNotEqual(before, after)

    def test_backfill_command_generates_missing_legacy_variants(self):
        profile = PlayerProfile.objects.create(player=self.player)
        stored_name = profile.profile_picture.storage.save(
            "player_profiles/legacy-large.jpg",
            self._upload(size=(1600, 1200)),
        )
        PlayerProfile.objects.filter(pk=profile.pk).update(profile_picture=stored_name)
        profile.refresh_from_db()

        for size in AVATAR_SIZES:
            self.assertFalse(profile.profile_picture.storage.exists(profile_avatar_name(profile, size)))

        call_command("backfill_profile_avatars")

        for size in AVATAR_SIZES:
            self.assertTrue(profile.profile_picture.storage.exists(profile_avatar_name(profile, size)))

    def test_avatar_templates_compile(self):
        for template_name in (
            "home.html",
            "teams/pfc_market.html",
            "teams/player_leaderboard.html",
            "teams/player_profile.html",
            "teams/partials/position_leaderboard_table.html",
            "teams/team_detail.html",
            "teams/team_login.html",
            "teams/edit_player_profile.html",
        ):
            with self.subTest(template=template_name):
                get_template(template_name)
