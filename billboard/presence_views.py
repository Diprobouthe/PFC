"""
billboard/presence_views.py
============================
One-tap presence API for the redesigned Billboard.

Endpoints:
  GET  /billboard/api/defaults/       — return smart defaults for the current player
  POST /billboard/api/im-here/        — one-tap "I'm here" (AT_COURTS)
  POST /billboard/api/going/          — one-tap "I'm going" (GOING_TO_COURTS)
  POST /billboard/api/leave/          — mark player as no longer at courts
"""
import json
from datetime import timedelta, date

from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from courts.models import CourtComplex
from billboard.models import BillboardEntry, BillboardSettings
from billboard.presence_prefs import UserPresencePrefs


# ── Auth helper ───────────────────────────────────────────────────────────────

def _get_codename(request):
    """Return the session codename (uppercase) or None."""
    codename = request.session.get("player_codename")
    if codename:
        return codename.upper()
    return None


# ── Smart defaults ────────────────────────────────────────────────────────────

def _snap_to_slot(dt):
    """Round a datetime down to the nearest 30-min slot, return 'HH:MM' string."""
    minute = 0 if dt.minute < 30 else 30
    return f"{dt.hour:02d}:{minute:02d}"


def _get_defaults(codename):
    """
    Return a dict of smart defaults for the one-tap form.
    Falls back gracefully when no history exists.
    """
    now = timezone.localtime()
    today_str = now.date().isoformat()
    tomorrow_str = (now.date() + timedelta(days=1)).isoformat()
    now_slot = _snap_to_slot(now)
    plus30_slot = _snap_to_slot(now + timedelta(minutes=30))

    prefs = UserPresencePrefs.get_for_codename(codename) if codename else None

    # Court: last used or first available
    court = None
    court_id = None
    court_name = ""
    if prefs and prefs.last_court_complex_id:
        court = prefs.last_court_complex
        court_id = court.pk
        court_name = court.name
    else:
        first = CourtComplex.objects.order_by("name").first()
        if first:
            court_id = first.pk
            court_name = first.name

    # Preferred time
    preferred_time = prefs.preferred_time if prefs and prefs.preferred_time else now_slot

    return {
        "court_id":       court_id,
        "court_name":     court_name,
        "today":          today_str,
        "tomorrow":       tomorrow_str,
        "now_slot":       now_slot,
        "plus30_slot":    plus30_slot,
        "preferred_time": preferred_time,
        "has_prefs":      prefs is not None,
    }


# ── API views ─────────────────────────────────────────────────────────────────

@require_GET
def api_defaults(request):
    """GET /billboard/api/defaults/ — smart defaults for the current player."""
    codename = _get_codename(request)
    courts = list(
        CourtComplex.objects.order_by("name").values("id", "name")
    )
    defaults = _get_defaults(codename)
    return JsonResponse({
        "ok": True,
        "codename": codename,
        "defaults": defaults,
        "courts": courts,
    })


@csrf_exempt
@require_POST
def api_im_here(request):
    """
    POST /billboard/api/im-here/
    Body (JSON):
        codename      : str (6-char, optional if session is set)
        court_id      : int (optional, falls back to last used)
        scheduled_date: "YYYY-MM-DD" (optional, defaults to today)
        message       : str (optional)
    """
    codename = _get_codename(request)
    try:
        data = json.loads(request.body or "{}")
    except (json.JSONDecodeError, ValueError):
        data = {}

    # Allow codename override from body (for unauthenticated flow)
    if not codename:
        codename = str(data.get("codename", "")).upper()
    if not codename or len(codename) != 6:
        return JsonResponse({"ok": False, "error": "Codename required (6 chars)"}, status=400)

    # Resolve court
    court_id = data.get("court_id")
    if court_id:
        court = CourtComplex.objects.filter(pk=court_id).first()
    else:
        prefs = UserPresencePrefs.get_for_codename(codename)
        court = prefs.last_court_complex if prefs else None
    if not court:
        court = CourtComplex.objects.order_by("name").first()
    if not court:
        return JsonResponse({"ok": False, "error": "No court complex available"}, status=400)

    # Check daily limit
    settings = BillboardSettings.get_settings()
    if not BillboardEntry.can_create_entry(codename, "AT_COURTS"):
        return JsonResponse({
            "ok": False,
            "error": f"You can only post {settings.max_entries_per_day} 'I'm here' entries per day.",
        }, status=400)

    # Resolve date
    raw_date = data.get("scheduled_date")
    try:
        sched_date = date.fromisoformat(raw_date) if raw_date else timezone.localtime().date()
    except ValueError:
        sched_date = timezone.localtime().date()

    message = str(data.get("message", ""))[:200]

    entry = BillboardEntry.objects.create(
        codename=codename,
        action_type="AT_COURTS",
        court_complex=court,
        scheduled_date=sched_date,
        message=message,
    )

    # Trigger analytics snapshot
    try:
        from billboard.analytics_utils import trigger_analytics_update
        trigger_analytics_update(court)
    except Exception:
        pass

    return JsonResponse({
        "ok": True,
        "entry_id": entry.pk,
        "court": court.name,
        "date": sched_date.isoformat(),
    })


@csrf_exempt
@require_POST
def api_going(request):
    """
    POST /billboard/api/going/
    Body (JSON):
        codename       : str
        court_id       : int (optional)
        scheduled_date : "YYYY-MM-DD" (optional, defaults to today)
        scheduled_time : "HH:MM"      (optional, defaults to smart default)
        message        : str (optional)
    """
    codename = _get_codename(request)
    try:
        data = json.loads(request.body or "{}")
    except (json.JSONDecodeError, ValueError):
        data = {}

    if not codename:
        codename = str(data.get("codename", "")).upper()
    if not codename or len(codename) != 6:
        return JsonResponse({"ok": False, "error": "Codename required (6 chars)"}, status=400)

    # Resolve court
    court_id = data.get("court_id")
    if court_id:
        court = CourtComplex.objects.filter(pk=court_id).first()
    else:
        prefs = UserPresencePrefs.get_for_codename(codename)
        court = prefs.last_court_complex if prefs else None
    if not court:
        court = CourtComplex.objects.order_by("name").first()
    if not court:
        return JsonResponse({"ok": False, "error": "No court complex available"}, status=400)

    # Check daily limit
    settings = BillboardSettings.get_settings()
    if not BillboardEntry.can_create_entry(codename, "GOING_TO_COURTS"):
        return JsonResponse({
            "ok": False,
            "error": f"You can only post {settings.max_entries_per_day} 'Going' entries per day.",
        }, status=400)

    # Resolve date
    raw_date = data.get("scheduled_date")
    try:
        sched_date = date.fromisoformat(raw_date) if raw_date else timezone.localtime().date()
    except ValueError:
        sched_date = timezone.localtime().date()

    # Resolve time
    now = timezone.localtime()
    defaults = _get_defaults(codename)
    raw_time = data.get("scheduled_time") or defaults["preferred_time"]
    # Validate against TIME_SLOTS
    valid_slots = [s[0] for s in BillboardEntry.TIME_SLOTS]
    sched_time = raw_time if raw_time in valid_slots else _snap_to_slot(now)

    message = str(data.get("message", ""))[:200]

    entry = BillboardEntry.objects.create(
        codename=codename,
        action_type="GOING_TO_COURTS",
        court_complex=court,
        scheduled_date=sched_date,
        scheduled_time=sched_time,
        message=message,
    )

    return JsonResponse({
        "ok": True,
        "entry_id": entry.pk,
        "court": court.name,
        "date": sched_date.isoformat(),
        "time": sched_time,
    })


@csrf_exempt
@require_POST
def api_leave(request):
    """
    POST /billboard/api/leave/
    Deactivates all active AT_COURTS entries for the current player.
    Body (JSON):
        codename : str (optional if session is set)
    """
    codename = _get_codename(request)
    try:
        data = json.loads(request.body or "{}")
    except (json.JSONDecodeError, ValueError):
        data = {}

    if not codename:
        codename = str(data.get("codename", "")).upper()
    if not codename or len(codename) != 6:
        return JsonResponse({"ok": False, "error": "Codename required"}, status=400)

    cutoff = timezone.now() - timedelta(hours=24)
    count = BillboardEntry.objects.filter(
        codename=codename,
        action_type="AT_COURTS",
        is_active=True,
        created_at__gte=cutoff,
    ).update(is_active=False)

    return JsonResponse({"ok": True, "deactivated": count})
