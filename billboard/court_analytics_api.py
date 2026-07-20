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
All historical metrics count **distinct players** (distinct codenames) per time
bucket, not raw BillboardEntry rows.  This prevents inflation from:
  - Multiple presence sources per session (game entry + post_game grace + manual)
  - Multiple matches per session (each match creates its own entry)
  - Repeated auto_register calls that create multiple entries for the same match

Specifically:
  Peak Hours:   distinct codenames whose first AT_COURTS entry in that hour falls
                in that bucket (i.e. each player counted once per hour).
  Day of Week:  distinct codenames per weekday bucket.
  Weekly Trend: distinct codenames per calendar week.
  total_7d:     distinct codenames in the last 7 days.
  total_30d:    distinct codenames in the last 30 days.
  Now (current): distinct codenames currently present (unchanged — already correct).

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
# The base queryset for analytics uses only AT_COURTS entries.
# GOING_TO_COURTS entries are intent/scheduling data, not physical presence,
# and must not be counted in the current-occupancy or historical visitor totals.
PRESENCE_TYPES = ("AT_COURTS",)


def _entry_qs(days=30, court=None):
    """Base queryset: AT_COURTS presence entries in the last N days."""
    cutoff = timezone.now() - timedelta(days=days)
    qs = BillboardEntry.objects.filter(
        action_type__in=PRESENCE_TYPES,
        created_at__gte=cutoff,
    )
    if court:
        qs = qs.filter(court_complex=court)
    return qs


# Maximum age for a game-generated presence entry to be considered "live".
# Mirrors the constant in analytics_utils.py.
_GAME_PRESENCE_MAX_AGE_HOURS = 6


def _current_occupancy(qs, two_hours_ago):
    """
    Count distinct players currently at court from *qs* (already filtered to AT_COURTS).

    Presence rules (consistent with BillboardListView and analytics_utils):
    - Game entries (friendly_game / tournament_match): is_active=True AND created
      within the last _GAME_PRESENCE_MAX_AGE_HOURS hours.  The age cap is a safety
      net against lifecycle failures (match left in 'active' without a result).
    - Post-game grace (post_game): is_active=True AND expires_at >= now.
    - Manual / legacy entries: is_active=True AND within the 2-hour window.
    - Returns a distinct codename count so one player with multiple entries = 1 person.
    """
    now = timezone.now()
    game_cutoff = now - timedelta(hours=_GAME_PRESENCE_MAX_AGE_HOURS)
    return (
        qs.filter(
            action_type="AT_COURTS",
            is_active=True,
        )
        # Exclude soft-expired entries (post_game grace that has elapsed).
        .filter(Q(expires_at__isnull=True) | Q(expires_at__gte=now))
        .filter(
            # Game entries: lifecycle-managed + safety age cap.
            Q(
                presence_source__in=[
                    BillboardEntry.PRESENCE_SOURCE_FRIENDLY,
                    BillboardEntry.PRESENCE_SOURCE_MATCH,
                ],
                created_at__gte=game_cutoff,
            ) |
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


def _distinct_players_by_bucket(qs, court_tz, bucket_fn):
    """
    Count distinct players (codenames) per time bucket.

    For each entry, compute a bucket key using *bucket_fn(local_datetime)*.
    Each codename is counted at most once per bucket — if a player has multiple
    presence entries in the same bucket (e.g. a game entry + a post_game entry),
    they still count as 1 visitor for that bucket.

    Args:
        qs:         BillboardEntry queryset (already filtered to AT_COURTS + date range)
        court_tz:   pytz timezone for the court complex
        bucket_fn:  callable(aware_datetime) -> hashable bucket key

    Returns:
        defaultdict(set): bucket_key → set of codenames
    """
    bucket_codenames = defaultdict(set)
    for created_at, codename in qs.values_list("created_at", "codename"):
        local_dt = created_at.astimezone(court_tz)
        key = bucket_fn(local_dt)
        bucket_codenames[key].add(codename)
    return bucket_codenames


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
        # total_30d: distinct players, not raw rows
        total = qs.values("codename").distinct().count()
        current = _current_occupancy(qs, two_hours_ago)

        # Peak hour — bucket by court-local hour, count distinct players per hour
        import pytz
        try:
            court_tz = pytz.timezone(court.timezone_name)
        except Exception:
            court_tz = pytz.utc

        hour_buckets = _distinct_players_by_bucket(qs, court_tz, lambda dt: dt.hour)
        # Peak hour = the hour with the most distinct players
        peak_hour = max(hour_buckets, key=lambda h: len(hour_buckets[h])) if hour_buckets else None

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

    All historical metrics count **distinct players per time bucket**:
      - hourly:   distinct codenames per hour-of-day (0-23), aggregated over 30 days
      - daily:    distinct codenames per weekday (Mon-Sun), aggregated over 30 days
      - weekly:   distinct codenames per calendar week (last 8 weeks)
      - total_7d: distinct codenames in the last 7 days
      - total_30d: distinct codenames in the last 30 days
      - current:  distinct codenames currently present (live, unchanged)

    Response shape:
    {
      "ok": true,
      "court": {"id": 1, "name": "..."},
      "hourly":  [{"hour": 9, "label": "09:00", "count": 3}, ...],   // 0-23
      "daily":   [{"day": 0, "label": "Mon", "count": 2}, ...],      // 0-6
      "weekly":  [{"date": "2026-04-01", "count": 4}, ...],          // last 8 weeks
      "current": 4,
      "total_7d": 4,
      "total_30d": 10,
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

    import pytz
    try:
        court_tz = pytz.timezone(court.timezone_name)
    except Exception:
        court_tz = pytz.utc

    # ── Hourly distribution (0-23) — distinct players per hour-of-day ────────
    # Each player counted once per hour-of-day bucket across the 30-day window.
    # e.g. if a player appears at 10:00 on Monday and 10:00 on Wednesday,
    # they count as 1 distinct player for the 10:00 bucket (not 2).
    hour_buckets = _distinct_players_by_bucket(qs_30, court_tz, lambda dt: dt.hour)
    hourly = [
        {"hour": h, "label": f"{h:02d}:00", "count": len(hour_buckets.get(h, set()))}
        for h in range(9, 23)  # 09:00 – 22:00 (typical playing hours)
    ]

    # ── Day-of-week distribution — distinct players per weekday ───────────────
    # Each player counted once per weekday bucket across the 30-day window.
    day_buckets = _distinct_players_by_bucket(qs_30, court_tz, lambda dt: dt.weekday())
    daily = [
        {"day": d, "label": DAY_NAMES[d], "count": len(day_buckets.get(d, set()))}
        for d in range(7)
    ]

    # ── Weekly trend (last 8 weeks) — distinct players per calendar week ──────
    # Each player counted once per week even if they appeared multiple times.
    qs_56 = _entry_qs(days=56, court=court)
    week_buckets = _distinct_players_by_bucket(
        qs_56, court_tz,
        lambda dt: (dt.date() - timedelta(days=dt.weekday())).isoformat()
    )
    weekly = sorted(
        [{"date": k, "count": len(v)} for k, v in week_buckets.items()],
        key=lambda x: x["date"],
    )

    # ── Current occupancy (distinct players) — unchanged ─────────────────────
    current = _current_occupancy(qs_30, two_hours_ago)

    # ── Totals: distinct players (not raw row counts) ─────────────────────────
    total_7d  = qs_7.values("codename").distinct().count()
    total_30d = qs_30.values("codename").distinct().count()

    return JsonResponse({
        "ok":       True,
        "court":    {"id": court.pk, "name": court.name},
        "hourly":   hourly,
        "daily":    daily,
        "weekly":   weekly,
        "current":  current,
        "total_7d": total_7d,
        "total_30d": total_30d,
    })
