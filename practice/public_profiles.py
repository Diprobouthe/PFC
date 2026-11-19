"""Consent-gated, read-only practice progress for another player's profile.

Only aggregate recent performance. Individual sessions, timestamps, durations,
shot sequences, codenames and detail URLs are never exposed to the template.
"""
from practice.history_progress import (
    WINDOW, FIXED_DISTANCE_CODES, summarize_accuracy_views,
)


def public_practice_progress_for_player(player, *, grouped=False):
    """Return aggregate display data only if this exact player opted in.

    None means private or globally hidden, so the caller should omit the tab.
    No request/session codename fallback is ever used.
    """
    profile = getattr(player, "profile", None)
    if not profile or not profile.share_practice_statistics or profile.hide_public_statistics:
        return None

    from friendly_games.models import PlayerCodename
    from practice.models import PracticeSession

    owner_codename = (
        PlayerCodename.objects.filter(player_id=player.pk)
        .values_list("codename", flat=True)
        .first()
    )
    if not owner_codename:
        empty = summarize_accuracy_views([])
        return empty if grouped else empty["all"]

    series = []
    # Last 12 in each source, per discipline; otherwise older training would
    # disappear when the player's 12 most recent sessions were all InG.
    for kind in ("shooting", "pointing"):
        for distances in (FIXED_DISTANCE_CODES, ("ing",)):
            series.extend(
                PracticeSession.objects.filter(
                    player_codename=owner_codename,
                    practice_type=kind,
                    distance__in=distances,
                    is_active=False,
                    ended_at__isnull=False,
                    total_shots__gt=0,
                    drill_type__in=("", "open"),
                ).order_by("-started_at")[:WINDOW]
            )
    series.sort(key=lambda item: item.started_at, reverse=True)
    views = summarize_accuracy_views(series)
    return views if grouped else views["all"]
