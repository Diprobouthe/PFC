"""
billboard/court_analytics_api.py
==================================
Lightweight analytics API that reads directly from BillboardEntry data.
No pre-aggregation needed — queries are fast enough for the volumes involved.

Endpoints:
  GET /billboard/api/analytics/summary/          — all-courts overview
  GET /billboard/api/analytics/court/<id>/       — per-court detail (JSON for charts)

Presence counting rules
-----------------------
Game-generated entries (presence_source = 'friendly_game' or 'tournament_match'):
  Lifecycle-managed: is_active is cleared when the specific match/game ends.
  A player is "currently present" as long as is_active=True, regardless of age
  or tournament state.  Active tournament ≠ active physical presence.

Post-game grace entries (presence_source = 'post_game'):
  Created when a match/game ends; visible for 30 minutes (expires_at).
  Allows players to be found for a rematch or new game after the match ends.

Manual check-ins (presence_source = 'manual', or legacy entries with no source):
  Time-window managed: counted as present only within a 2-hour rolling window.

In all cases, distinct codenames are counted so one player with multiple
active entries (e.g. a manual check-in AND a game entry) counts as 1 person.
"""
from collections import defaultdict
from datetime import timedelta

from django.db.models import Q
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET

from courts.models import CourtComplex
from courts.timezone_utils import get_court_local_now
from billboard.models import BillboardEntry


DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
PRESENCE_TYPES = ("AT_COURTS", "GOING_TO_COURTS")


def _entry_qs(days=30, court=None):
    """Base queryset: presence entries in the last N days."""
    cutoff = timezone.now() - timedelta(days=days)
    qs = BillboardEntry.objects.filter(
        action_type__in=PRESENCE_TYPES,
        created_at__gte=cutoff,
    )
    if court:
        qs = qs.filter(court_complex=court)
    return qs


def _current_occupancy(qs, two_hours_ago):
    """
    Count distinct players currently at court from *qs* (already filtered to AT_COURTS).

    Presence rules (consistent with BillboardListView and analytics_utils):
    - Game entries (friendly_game / tournament_match): is_active=True is sufficient.
      Cleared by the lifecycle when the specific match/game ends, regardless of
      tournament state or calendar date.
    - Post-game grace (post_game): is_active=True AND expires_at >= now.
    - Manual / legacy entries: is_active=True AND within the 2-hour window.
    - Returns a distinct codename count so one player with multiple entries = 1 person.
    """
    now = timezone.now()
    return (
        qs.filter(
            action_type="AT_COURTS",
            is_active=True,
        )
        # Exclude soft-expired entries (post_game grace that has elapsed).
        .filter(Q(expires_at__isnull=True) | Q(expires_at__gte=now))
        .filter(
            # Game entries: lifecycle-managed, no date guard.
            Q(presence_source__in=[
                BillboardEntry.PRESENCE_SOURCE_FRIENDLY,
                BillboardEntry.PRESENCE_SOURCE_MATCH,
            ]) |
            # Post-game grace: expires_at already checked above.
            Q(presence_source=BillboardEntry.PRESENCE_SOURCE_POST_GAME) |
            Q(
                presence_source=BillboardEntry.PRESENCE_SOURCE_MANUAL,
                created_at__gte=two_hours_ago,
            ) |
            # Legacy entries with NULL presence_source — safety net.
            Q(
                presence_source__isnull=True,
                created_at__gte=two_hours_ago,
            )
        )
        .values("codename")
        .distinct()
        .count()
    )


@require_GET
def api_analytics_summary(request):
    """
    GET /billboard/api/analytics/summary/
    Returns per-court overview stats for the last 30 days.
    """
    courts = CourtComplex.objects.order_by("name")
    result = []

    for court in courts:
        # Use court-local now so the 2-hour cutoff is correct for each court's timezone
        court_now = get_court_local_now(court)
        two_hours_ago = court_now - timedelta(hours=2)

        qs = _entry_qs(days=30, court=court)
        total = qs.count()
        current = _current_occupancy(qs, two_hours_ago)

        # Peak hour — bucket by court-local hour
        import pytz
        try:
            court_tz = pytz.timezone(court.timezone_name)
        except Exception:
            court_tz = pytz.utc
        hour_counts = defaultdict(int)
        for e in qs.values_list("created_at", flat=True):
            local_dt = e.astimezone(court_tz)
            hour_counts[local_dt.hour] += 1
        peak_hour = max(hour_counts, key=hour_counts.get) if hour_counts else None

        result.append({
            "id":         court.pk,
            "name":       court.name,
            "current":    current,
            "total_30d":  total,
            "peak_hour":  f"{peak_hour:02d}:00" if peak_hour is not None else "—",
        })

    return JsonResponse({"ok": True, "courts": result})


@require_GET
def api_analytics_court(request, court_id):
    """
    GET /billboard/api/analytics/court/<id>/
    Returns chart-ready data for a single court complex.

    Response shape:
    {
      "ok": true,
      "court": {"id": 1, "name": "..."},
      "hourly":  [{"hour": 9, "label": "09:00", "count": 12}, ...],   // 0-23
      "daily":   [{"day": 0, "label": "Mon", "count": 8}, ...],       // 0-6
      "weekly":  [{"date": "2026-04-01", "count": 3}, ...],           // last 8 weeks
      "current": 4,
      "total_7d": 22,
      "total_30d": 87,
    }
    """
    try:
        court = CourtComplex.objects.get(pk=court_id)
    except CourtComplex.DoesNotExist:
        return JsonResponse({"ok": False, "error": "Court not found"}, status=404)

    # Use court-local now so the 2-hour cutoff is correct for this court's timezone
    court_now = get_court_local_now(court)
    two_hours_ago = court_now - timedelta(hours=2)
    qs_30 = _entry_qs(days=30, court=court)
    qs_7  = _entry_qs(days=7,  court=court)

    # ── Hourly distribution (0-23) — bucket by court-local hour ──────────────
    import pytz
    try:
        court_tz = pytz.timezone(court.timezone_name)
    except Exception:
        court_tz = pytz.utc
    hour_counts = defaultdict(int)
    for e in qs_30.values_list("created_at", flat=True):
        local_dt = e.astimezone(court_tz)
        hour_counts[local_dt.hour] += 1
    hourly = [
        {"hour": h, "label": f"{h:02d}:00", "count": hour_counts.get(h, 0)}
        for h in range(9, 23)  # 09:00 – 22:00 (typical playing hours)
    ]

    # ── Day-of-week distribution ──────────────────────────────────────────────
    day_counts = defaultdict(int)
    for e in qs_30.values_list("created_at", flat=True):
        local_dt = e.astimezone(court_tz)
        day_counts[local_dt.weekday()] += 1
    daily = [
        {"day": d, "label": DAY_NAMES[d], "count": day_counts.get(d, 0)}
        for d in range(7)
    ]

    # ── Weekly trend (last 8 weeks, by week start) ────────────────────────────
    qs_56 = _entry_qs(days=56, court=court)
    week_counts = defaultdict(int)
    for e in qs_56.values_list("created_at", flat=True):
        local_dt = e.astimezone(court_tz)
        week_start = (local_dt.date() - timedelta(days=local_dt.weekday())).isoformat()
        week_counts[week_start] += 1
    weekly = sorted(
        [{"date": k, "count": v} for k, v in week_counts.items()],
        key=lambda x: x["date"],
    )

    # ── Current occupancy (distinct players) ─────────────────────────────────
    current = _current_occupancy(qs_30, two_hours_ago)

    return JsonResponse({
        "ok":       True,
        "court":    {"id": court.pk, "name": court.name},
        "hourly":   hourly,
        "daily":    daily,
        "weekly":   weekly,
        "current":  current,
        "total_7d": qs_7.count(),
        "total_30d": qs_30.count(),
    })
