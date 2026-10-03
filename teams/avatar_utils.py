"""Small derived avatars for player profile pictures.

The original upload remains the source of truth.  UI surfaces use deterministic
WebP derivatives so a 32-78 CSS-pixel avatar never downloads a multi-megabyte
original image.
"""
from __future__ import annotations

import io

from django.core.files.base import ContentFile
from PIL import Image, ImageOps


AVATAR_SIZES = (96, 192)
AVATAR_QUALITY = 82
AVATAR_DIRECTORY = "player_profiles/avatars"


def profile_avatar_name(profile, size: int) -> str:
    """Return the deterministic storage name for one derived avatar."""
    if size not in AVATAR_SIZES:
        raise ValueError(f"Unsupported avatar size: {size}")
    if not getattr(profile, "player_id", None):
        raise ValueError("PlayerProfile must be attached to a saved Player.")
    return f"{AVATAR_DIRECTORY}/player_{profile.player_id}_{size}.webp"


def profile_avatar_exists(profile, size: int) -> bool:
    if not getattr(profile, "profile_picture", None):
        return False
    return profile.profile_picture.storage.exists(profile_avatar_name(profile, size))


def profile_avatar_url(profile, size: int) -> str:
    """Prefer the derived avatar, falling back to the original until backfill."""
    picture = getattr(profile, "profile_picture", None)
    if not picture:
        return ""
    storage = picture.storage
    variant = profile_avatar_name(profile, size)
    if storage.exists(variant):
        return storage.url(variant)
    # Safe rollout fallback: existing profiles still render before the one-off
    # backfill has generated their derivatives.
    return picture.url


def generate_profile_avatar_variants(profile, *, force: bool = True) -> dict[int, str]:
    """Generate 96px and 192px square WebP variants without altering the original."""
    picture = getattr(profile, "profile_picture", None)
    if not picture:
        return {}

    storage = picture.storage
    generated: dict[int, str] = {}

    with storage.open(picture.name, "rb") as source:
        with Image.open(source) as opened:
            image = ImageOps.exif_transpose(opened)
            if image.mode not in ("RGB", "RGBA"):
                image = image.convert("RGB")

            for size in AVATAR_SIZES:
                variant_name = profile_avatar_name(profile, size)
                if not force and storage.exists(variant_name):
                    generated[size] = variant_name
                    continue

                avatar = ImageOps.fit(
                    image.copy(),
                    (size, size),
                    method=Image.Resampling.LANCZOS,
                    centering=(0.5, 0.5),
                )
                if avatar.mode != "RGB":
                    # Profile avatars are displayed on opaque UI backgrounds;
                    # RGB avoids carrying an unnecessary alpha channel.
                    background = Image.new("RGB", avatar.size, "white")
                    if "A" in avatar.getbands():
                        background.paste(avatar, mask=avatar.getchannel("A"))
                    else:
                        background.paste(avatar.convert("RGB"))
                    avatar = background

                output = io.BytesIO()
                avatar.save(
                    output,
                    format="WEBP",
                    quality=AVATAR_QUALITY,
                    method=6,
                )
                payload = ContentFile(output.getvalue())

                if storage.exists(variant_name):
                    storage.delete(variant_name)
                saved_name = storage.save(variant_name, payload)
                generated[size] = saved_name

    return generated
