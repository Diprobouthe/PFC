"""Consent-gated, read-only practice progress for another player's profile.

Only aggregate recent performance. Individual sessions, timestamps, durations,
shot sequences, codenames and detail URLs are never exposed to the template.
"""
from practice.history_progress import WINDOW, summarize_practice_progress


def public_practice_progress_for_player(player):
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
        return {kind: {"count": 0, "total_shots": 0} for kind in ("shooting", "pointing")}

    series = []
    for kind in ("shooting", "pointing"):
        series.extend(
            PracticeSession.objects.filter(
                player_codename=owner_codename,
                practice_type=kind,
                is_active=False,
                ended_at__isnull=False,
                total_shots__gt=0,
                drill_type__in=("", "open"),
            )
            .order_by("-started_at")[:WINDOW]
        )
    # The shared progression engine requires newest-first order; keep the
    # window per type instead of truncating both types together.
    series.sort(key=lambda item: item.started_at, reverse=True)
    return summarize_practice_progress(series)
