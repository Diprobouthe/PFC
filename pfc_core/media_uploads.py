"""
pfc_core/media_uploads.py
=========================
Unified media upload policy for the PFC platform.

Rules:
- Every media type has exactly ONE folder prefix.
- Filenames are generated internally — original filenames from mobile/browser
  uploads are NEVER preserved.
- Naming scheme: <type>_<id>.<ext>  (e.g. player_42.jpg, team_7.jpg)
- If the object has no pk yet (pre-save), a UUID is used as a fallback so the
  file is still saved cleanly and the model's save() can rename it later.
- All extensions are lowercased and ASCII-safe.
- No nested/duplicated folder prefixes.

Usage in models:
    from pfc_core.media_uploads import player_profile_picture_path

    class PlayerProfile(models.Model):
        profile_picture = models.ImageField(
            upload_to=player_profile_picture_path,
            blank=True, null=True
        )
"""

import os
import uuid


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clean_ext(filename, default='.jpg'):
    """Return a lowercase, ASCII-safe extension from the original filename."""
    _, ext = os.path.splitext(filename)
    ext = ext.lower().strip()
    if not ext or not ext.startswith('.'):
        return default
    # Only allow safe extensions
    allowed = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg', '.bmp', '.tiff'}
    return ext if ext in allowed else default


def _id_or_uuid(instance):
    """Return the instance pk as a string, or a short UUID if pk is None."""
    if instance.pk:
        return str(instance.pk)
    return uuid.uuid4().hex[:12]


# ---------------------------------------------------------------------------
# Player profile pictures  →  player_profiles/player_<id>.<ext>
# ---------------------------------------------------------------------------

def player_profile_picture_path(instance, filename):
    """
    Deterministic path for PlayerProfile.profile_picture.
    Result: player_profiles/player_<id>.jpg  (or .png etc.)
    """
    ext = _clean_ext(filename, default='.jpg')
    name = f"player_{_id_or_uuid(instance)}{ext}"
    return f"player_profiles/{name}"


# ---------------------------------------------------------------------------
# Team logos  →  team_logos/team_<id>.<ext>
# ---------------------------------------------------------------------------

def team_logo_path(instance, filename):
    """
    Deterministic path for TeamProfile.logo_svg.
    Supports SVG and raster formats.
    Result: team_logos/team_<id>.svg  (or .png etc.)
    """
    ext = _clean_ext(filename, default='.png')
    # Allow SVG explicitly
    if filename.lower().endswith('.svg'):
        ext = '.svg'
    name = f"team_{_id_or_uuid(instance)}{ext}"
    return f"team_logos/{name}"


# ---------------------------------------------------------------------------
# Team photos  →  team_photos/team_<id>.<ext>
# ---------------------------------------------------------------------------

def team_photo_path(instance, filename):
    """
    Deterministic path for TeamProfile.team_photo_jpg.
    Result: team_photos/team_<id>.jpg
    """
    ext = _clean_ext(filename, default='.jpg')
    name = f"team_{_id_or_uuid(instance)}{ext}"
    return f"team_photos/{name}"


# ---------------------------------------------------------------------------
# Court complex photos  →  court_images/court_<id>.<ext>
# ---------------------------------------------------------------------------

def court_complex_photo_path(instance, filename):
    """
    Deterministic path for CourtComplexPhoto.image.
    Result: court_images/court_<id>.jpg
    """
    ext = _clean_ext(filename, default='.jpg')
    name = f"court_{_id_or_uuid(instance)}{ext}"
    return f"court_images/{name}"


# ---------------------------------------------------------------------------
# Match photo evidence  →  match_evidence/match_<id>.<ext>
# ---------------------------------------------------------------------------

def match_evidence_photo_path(instance, filename):
    """
    Deterministic path for MatchPlayer.photo_evidence.
    Result: match_evidence/match_<id>.jpg
    """
    ext = _clean_ext(filename, default='.jpg')
    name = f"match_{_id_or_uuid(instance)}{ext}"
    return f"match_evidence/{name}"


# ---------------------------------------------------------------------------
# Tournament banners  →  tournament_banners/tournament_<id>.<ext>
# ---------------------------------------------------------------------------

def tournament_banner_path(instance, filename):
    """
    Deterministic path for Tournament.banner_image.
    Result: tournament_banners/tournament_<id>.jpg
    """
    ext = _clean_ext(filename, default='.jpg')
    name = f"tournament_{_id_or_uuid(instance)}{ext}"
    return f"tournament_banners/{name}"


# ---------------------------------------------------------------------------
# Temporary uploads (used during multi-step player creation flow)
# These are cleaned up after the player is created.
# ---------------------------------------------------------------------------

def temp_upload_path(instance, filename):
    """
    Temporary path for files that are moved to their final location
    after the related object is saved.
    Result: temp/<uuid>.<ext>
    """
    ext = _clean_ext(filename, default='.jpg')
    return f"temp/{uuid.uuid4().hex}{ext}"
