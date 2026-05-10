"""
billboard/templatetags/court_tz_tags.py
========================================
Template tags/filters for converting UTC datetimes to court-local time.

Usage in templates:
    {% load court_tz_tags %}

    {# Display a UTC datetime in the court's local timezone #}
    {{ entry.created_at|court_localtime:entry.court_complex|time:"H:i" }}

    {# Or use the combined filter that returns "HH:MM" string directly #}
    {{ entry.created_at|court_time:entry.court_complex }}

    {# timesince equivalent using court-local now #}
    {{ entry.created_at|court_timesince:entry.court_complex }}
"""
import zoneinfo
from datetime import datetime, timezone as dt_timezone

from django import template
from django.utils import timezone
from django.utils.timesince import timesince

register = template.Library()


def _get_court_tz(court_complex):
    """Return a ZoneInfo object for the court, falling back to Europe/Athens."""
    if court_complex is None:
        return zoneinfo.ZoneInfo("Europe/Athens")
    tz_name = getattr(court_complex, "timezone_name", "Europe/Athens") or "Europe/Athens"
    try:
        return zoneinfo.ZoneInfo(tz_name)
    except Exception:
        return zoneinfo.ZoneInfo("Europe/Athens")


@register.filter
def court_localtime(dt, court_complex):
    """
    Convert a UTC-aware datetime to the court's local timezone.
    Returns a timezone-aware datetime in the court's tz.

    Usage: {{ entry.created_at|court_localtime:entry.court_complex }}
    Then chain with Django's built-in |time, |date filters.
    """
    if dt is None:
        return dt
    tz = _get_court_tz(court_complex)
    return dt.astimezone(tz)


@register.filter
def court_time(dt, court_complex):
    """
    Return the time portion of a UTC datetime expressed in the court's
    local timezone, formatted as "HH:MM".

    Usage: {{ entry.created_at|court_time:entry.court_complex }}
    """
    if dt is None:
        return ""
    tz = _get_court_tz(court_complex)
    local_dt = dt.astimezone(tz)
    return local_dt.strftime("%H:%M")


@register.filter
def court_timesince(dt, court_complex):
    """
    Return a human-readable "X minutes ago" string computed relative to
    court-local now (so the offset is correct for the court's timezone).

    Usage: {{ entry.created_at|court_timesince:entry.court_complex }}
    """
    if dt is None:
        return ""
    tz = _get_court_tz(court_complex)
    now_local = timezone.now().astimezone(tz)
    return timesince(dt, now=now_local)
