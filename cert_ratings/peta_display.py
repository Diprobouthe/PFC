"""Read-only presentation data for settled PETA Travel Points.

Never infer Travel Points from global ratings or unfinalized matches.
"""
from decimal import Decimal

from .peta_models import PetaCompetitor, PetaEvent, PetaEventEntry


def profile_travel_points(player):
    competitors = list(
        PetaCompetitor.objects.filter(player=player)
        .select_related("series").order_by("series__name")
    )
    if not competitors:
        return []
    entries = (
        PetaEventEntry.objects.filter(
            player=player, event__series_id__in=[c.series_id for c in competitors],
            event__settled_at__isnull=False,
        )
        .select_related("event", "event__tournament")
        .order_by("event__series_id", "event__ordinal")
    )
    history = {}
    for entry in entries:
        audit = entry.event.settlement_audit or {}
        after = audit.get("travel_points_after", {})
        total = after.get(str(player.id), after.get(player.id))
        if total is None:
            continue
        history.setdefault(entry.event.series_id, []).append({
            "event": entry.event,
            "earned": entry.personal_earnings + entry.dividend,
            "total": Decimal(str(total)),
            "personal": entry.personal_earnings,
            "dividend": entry.dividend,
        })
    return [
        {"series": competitor.series, "total": competitor.travel_points,
         "events": list(reversed(history.get(competitor.series_id, [])))}
        for competitor in competitors
    ]


def tournament_travel_points(tournament):
    event = (
        PetaEvent.objects.filter(tournament=tournament)
        .select_related("series").first()
    )
    if event is None:
        return None
    if event.settled_at is None:
        return {"event": event, "settled": False, "rows": []}
    after = (event.settlement_audit or {}).get("travel_points_after", {})
    entries = (
        PetaEventEntry.objects.filter(event=event)
        .select_related("player").order_by("player__name")
    )
    rows = []
    for entry in entries:
        total = after.get(str(entry.player_id), after.get(entry.player_id))
        if total is None:
            continue
        rows.append({
            "player": entry.player, "earned": entry.personal_earnings + entry.dividend,
            "personal": entry.personal_earnings, "dividend": entry.dividend,
            "total": Decimal(str(total)),
        })
    rows.sort(key=lambda row: (-row["total"], row["player"].name, row["player"].id))
    return {"event": event, "settled": True, "rows": rows}
