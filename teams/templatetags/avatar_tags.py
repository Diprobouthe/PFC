from django import template

from teams.avatar_utils import profile_avatar_url


register = template.Library()


@register.simple_tag
def player_avatar_url(profile, size=96):
    """Return a small derived avatar URL, with rollout-safe original fallback."""
    try:
        return profile_avatar_url(profile, int(size))
    except (AttributeError, TypeError, ValueError):
        return ""
