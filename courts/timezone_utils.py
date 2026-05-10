"""
courts/timezone_utils.py
─────────────────────────
Centralised timezone helpers for court-presence / attendance logic.

All timestamps are stored in UTC (Django default with USE_TZ=True).
These helpers convert "now" to the local time of a specific CourtComplex
so that "today" and "current hour" comparisons are always correct for the
physical location of the courts, regardless of where the server runs.

Usage
-----
    from courts.timezone_utils import get_court_local_now, get_court_local_date

    local_now  = get_court_local_now(court_complex)   # timezone-aware datetime in court's tz
    local_date = get_court_local_date(court_complex)  # date object in court's tz
"""

from django.utils import timezone


def get_court_local_now(court_complex):
    """
    Return the current datetime expressed in the timezone of *court_complex*.

    The returned datetime is timezone-aware (it carries the court's ZoneInfo).
    It is safe to use in Django ORM comparisons — Django converts both sides
    to UTC before comparing.

    Falls back to Europe/Athens if the court has no timezone_name set or if
    the name is invalid.

    Parameters
    ----------
    court_complex : courts.models.CourtComplex

    Returns
    -------
    datetime.datetime  — timezone-aware, in court's local timezone
    """
    tz = court_complex.get_timezone()
    return timezone.now().astimezone(tz)


def get_court_local_date(court_complex):
    """
    Return today's date in the timezone of *court_complex*.

    Parameters
    ----------
    court_complex : courts.models.CourtComplex

    Returns
    -------
    datetime.date
    """
    return get_court_local_now(court_complex).date()
