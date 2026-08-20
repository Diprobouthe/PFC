"""Display-only Court Complex timezone helpers for Live Score timestamps.

Stored ScoreUpdate timestamps remain canonical Django datetimes.  These helpers are
used only where the UI serializes a timestamp for display.
"""
from __future__ import annotations

from django.utils import timezone


def get_scoreboard_court_complex(scoreboard):
    """Return the Court Complex for a scoreboard's assigned match/game, if any."""
    tournament_match = getattr(scoreboard, "tournament_match", None)
    if tournament_match and tournament_match.court_id:
        return tournament_match.court.courtcomplex_set.order_by("id").first()

    friendly_game = getattr(scoreboard, "friendly_game", None)
    if friendly_game:
        return friendly_game.court_complex

    return None


def format_score_update_time(timestamp, scoreboard, time_format="%H:%M:%S"):
    """Format a score-update timestamp in its assigned Court Complex timezone.

    If no Court Complex is assigned, preserve the existing Django active-timezone
    fallback.  This function never mutates the stored timestamp or score data.
    """
    if timestamp is None:
        return ""

    court_complex = get_scoreboard_court_complex(scoreboard)
    if court_complex is not None:
        return timestamp.astimezone(court_complex.get_timezone()).strftime(time_format)

    return timezone.localtime(timestamp).strftime(time_format)
