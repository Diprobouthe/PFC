from django import template

from teams.avatar_utils import profile_avatar_url
from teams.team_photo_utils import team_photo_variant_url


register = template.Library()


@register.simple_tag
def player_avatar_url(profile, size=96):
    """Return a small derived avatar URL, with rollout-safe original fallback."""
    try:
        return profile_avatar_url(profile, int(size))
    except (AttributeError, TypeError, ValueError):
        return ""


@register.simple_tag
def team_photo_url(profile, size=400):
    """Return a lightweight Team photo URL, with original fallback."""
    try:
        return team_photo_variant_url(profile, int(size))
    except (AttributeError, TypeError, ValueError):
        return ""
