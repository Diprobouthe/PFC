"""Lightweight derived images for Team photos.

The original upload remains untouched. Public/team-management UI uses small
WebP derivatives so card/hero surfaces never need multi-megabyte originals.
"""
from __future__ import annotations

import io
import warnings

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from PIL import Image, ImageOps, UnidentifiedImageError


TEAM_PHOTO_SIZES = (400, 800)
TEAM_PHOTO_QUALITY = 82
TEAM_PHOTO_DIRECTORY = "team_photos/variants"
TEAM_PHOTO_UPLOAD_MAX_BYTES = 5 * 1024 * 1024
TEAM_PHOTO_MAX_DIMENSION = 5000
TEAM_PHOTO_MAX_PIXELS = 13_000_000
_ALLOWED_SOURCE_FORMATS = {"JPEG", "PNG", "WEBP"}


def team_photo_variant_name(profile, size: int) -> str:
    if size not in TEAM_PHOTO_SIZES:
        raise ValueError(f"Unsupported Team photo size: {size}")
    if not getattr(profile, "team_id", None):
        raise ValueError("TeamProfile must be attached to a saved Team.")
    return f"{TEAM_PHOTO_DIRECTORY}/team_{profile.team_id}_{size}.webp"


def team_photo_variant_exists(profile, size: int) -> bool:
    photo = getattr(profile, "team_photo_jpg", None)
    if not photo:
        return False
    return photo.storage.exists(team_photo_variant_name(profile, size))


def team_photo_variant_url(profile, size: int) -> str:
    """Prefer a derived photo, falling back safely to the original."""
    photo = getattr(profile, "team_photo_jpg", None)
    if not photo:
        return ""
    variant = team_photo_variant_name(profile, size)
    if photo.storage.exists(variant):
        return photo.storage.url(variant)
    return photo.url


def validate_team_photo_upload(image_file):
    """Validate a new Team photo before persistence/Pillow processing."""
    if not image_file:
        return image_file

    if getattr(image_file, "size", 0) > TEAM_PHOTO_UPLOAD_MAX_BYTES:
        raise ValidationError("Team photo must be 5 MB or smaller.")

    try:
        pos = image_file.tell()
    except Exception:
        pos = None

    try:
        try:
            image_file.seek(0)
        except Exception:
            pass
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(image_file) as image:
                image_format = (image.format or "").upper()
                width, height = image.size
                if image_format != "JPEG":
                    raise ValidationError("Team photo must be a JPEG image.")
                if (
                    width <= 0
                    or height <= 0
                    or width > TEAM_PHOTO_MAX_DIMENSION
                    or height > TEAM_PHOTO_MAX_DIMENSION
                    or width * height > TEAM_PHOTO_MAX_PIXELS
                ):
                    raise ValidationError(
                        "Team photo is too large. Use an image up to 5000 px "
                        "per side and about 13 megapixels."
                    )
                image.verify()
    except ValidationError:
        raise
    except (Image.DecompressionBombWarning, Image.DecompressionBombError):
        raise ValidationError("Team photo dimensions are too large.")
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError):
        raise ValidationError("Please upload a valid JPEG Team photo.")
    finally:
        try:
            image_file.seek(0 if pos is None else pos)
        except Exception:
            pass

    return image_file


def generate_team_photo_variants(profile, *, force: bool = True) -> dict[int, str]:
    """Generate 400px/800px WebP derivatives while preserving aspect ratio."""
    photo = getattr(profile, "team_photo_jpg", None)
    if not photo:
        return {}

    storage = photo.storage
    generated: dict[int, str] = {}

    with storage.open(photo.name, "rb") as source:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(source) as opened:
                if (opened.format or "").upper() not in _ALLOWED_SOURCE_FORMATS:
                    raise ValidationError("Unsupported stored Team photo format.")
                width, height = opened.size
                if (
                    width <= 0
                    or height <= 0
                    or width > TEAM_PHOTO_MAX_DIMENSION
                    or height > TEAM_PHOTO_MAX_DIMENSION
                    or width * height > TEAM_PHOTO_MAX_PIXELS
                ):
                    raise ValidationError("Stored Team photo dimensions are too large.")

                image = ImageOps.exif_transpose(opened)
                if image.mode != "RGB":
                    if "A" in image.getbands():
                        background = Image.new("RGB", image.size, "white")
                        background.paste(image, mask=image.getchannel("A"))
                        image = background
                    else:
                        image = image.convert("RGB")

                largest = max(TEAM_PHOTO_SIZES)
                # We no longer need the full-resolution buffer after validation;
                # resize it in place instead of keeping a second full-size copy.
                image.thumbnail(
                    (largest, largest),
                    Image.Resampling.LANCZOS,
                )
                master = image

                for size in TEAM_PHOTO_SIZES:
                    variant_name = team_photo_variant_name(profile, size)
                    if not force and storage.exists(variant_name):
                        generated[size] = variant_name
                        continue

                    if size == largest:
                        variant = master
                    else:
                        variant = master.copy()
                        variant.thumbnail((size, size), Image.Resampling.LANCZOS)

                    output = io.BytesIO()
                    variant.save(
                        output,
                        format="WEBP",
                        quality=TEAM_PHOTO_QUALITY,
                        method=6,
                    )
                    payload = ContentFile(output.getvalue())

                    if storage.exists(variant_name):
                        storage.delete(variant_name)
                    generated[size] = storage.save(variant_name, payload)

    return generated
