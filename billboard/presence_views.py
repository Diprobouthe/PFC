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
import logging
from datetime import timedelta, date, datetime, timezone as datetime_timezone

from django.conf import settings
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from courts.models import CourtComplex
from courts.timezone_utils import get_court_local_now
from courts.proximity import distance_metres
from billboard.models import BillboardEntry, BillboardSettings
from billboard.presence_prefs import UserPresencePrefs

logger = logging.getLogger('billboard.presence')


# ── Auth helper ───────────────────────────────────────────────────────────────

def _get_codename(request):
    """Return the session codename (uppercase) or None."""
    codename = request.session.get("player_codename")
    if codename:
        return codename.upper()
    return None


def _current_manual_presence(codename, court=None):
    """Return the latest currently valid manual AT_COURTS session for a player.

    This deliberately mirrors the existing two-hour manual-presence window.  It
    never treats game-generated or post-game presence as Friendly pull consent.
    """
    if not codename:
        return None
    entries = BillboardEntry.objects.filter(
        codename=codename.upper(),
        action_type='AT_COURTS',
        presence_source=BillboardEntry.PRESENCE_SOURCE_MANUAL,
        is_active=True,
    ).select_related('court_complex').order_by('-created_at')
    if court is not None:
        entries = entries.filter(court_complex=court)
    for entry in entries:
        local_now = get_court_local_now(entry.court_complex)
        if entry.created_at >= local_now - timedelta(hours=2):
            return entry
    return None


# ── Smart defaults ────────────────────────────────────────────────────────────

def _get_defaults(codename, court_complex=None):
    """
    Return a dict of smart defaults for the one-tap form.
    Falls back gracefully when no history exists.
    Uses court-local time when a court_complex is provided.
    """
    if court_complex:
        now = get_court_local_now(court_complex)
    else:
        now = timezone.localtime()
    today_str = now.date().isoformat()
    tomorrow_str = (now.date() + timedelta(days=1)).isoformat()
    now_time = now.strftime("%H:%M")
    plus30_time = (now + timedelta(minutes=30)).strftime("%H:%M")

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
    preferred_time = prefs.preferred_time if prefs and prefs.preferred_time else now_time

    return {
        "court_id":       court_id,
        "court_name":     court_name,
        "today":          today_str,
        "tomorrow":       tomorrow_str,
        "now_time":       now_time,
        "plus30_time":    plus30_time,
        "preferred_time": preferred_time,
        "has_prefs":      prefs is not None,
    }


# ── API views ─────────────────────────────────────────────────────────────────

@require_GET
def api_defaults(request):
    """
    GET /billboard/api/defaults/?court_id=<id>
    Return smart defaults for the current player.
    When court_id is provided, now_slot and plus30_slot are computed in
    that court's local timezone so relative quick options are correct.
    """
    codename = _get_codename(request)
    courts = list(
        CourtComplex.objects.order_by("name").values("id", "name", "latitude", "longitude")
    )
    # Resolve court from query param so time slots use court-local time
    court_complex = None
    raw_court_id = request.GET.get("court_id")
    if raw_court_id:
        try:
            court_complex = CourtComplex.objects.filter(pk=int(raw_court_id)).first()
        except (ValueError, TypeError):
            pass
    defaults = _get_defaults(codename, court_complex=court_complex)
    selected_court = court_complex
    if selected_court is None and defaults.get("court_id"):
        selected_court = CourtComplex.objects.filter(pk=defaults["court_id"]).first()
    manual_here_available = bool(selected_court and selected_court.has_coordinates())
    # Include the player's last anonymous choice so the UI can pre-select the toggle
    last_anonymous = False
    if codename:
        prefs = UserPresencePrefs.get_for_codename(codename)
        if prefs:
            last_anonymous = prefs.last_anonymous_choice

    current_presence = _current_manual_presence(codename, court_complex) if codename else None
    active_going = []
    recent_canceled_going = None
    if codename:
        active_going = [
            {
                "entry_id": entry.pk,
                "court_name": entry.court_complex.name,
                "scheduled_date": entry.scheduled_date.isoformat() if entry.scheduled_date else "",
                "scheduled_time": entry.scheduled_time or "",
                "arrival_at": entry.arrival_at.isoformat() if entry.arrival_at else "",
            }
            for entry in BillboardEntry.objects.filter(
                codename=codename,
                action_type="GOING_TO_COURTS",
                is_active=True,
                going_status=BillboardEntry.GOING_STATUS_ACTIVE,
            ).select_related("court_complex").order_by("arrival_at", "created_at")
        ]
        canceled = BillboardEntry.objects.filter(
            codename=codename,
            action_type="GOING_TO_COURTS",
            going_status=BillboardEntry.GOING_STATUS_CANCELED,
        ).select_related("court_complex").order_by("-canceled_at", "-updated_at").first()
        if canceled:
            recent_canceled_going = {
                "entry_id": canceled.pk,
                "court_name": canceled.court_complex.name,
                "scheduled_date": canceled.scheduled_date.isoformat() if canceled.scheduled_date else "",
                "scheduled_time": canceled.scheduled_time or "",
            }
    friendly_preference = False
    if codename:
        prefs = UserPresencePrefs.get_for_codename(codename)
        friendly_preference = bool(prefs and prefs.available_for_friendly)
    return JsonResponse({
        "ok": True,
        "codename": codename,
        "defaults": defaults,
        "courts": courts,
        "last_anonymous": last_anonymous,
        "friendly_presence_active": bool(current_presence),
        "active_going": active_going,
        "recent_canceled_going": recent_canceled_going,
        "available_for_friendly": friendly_preference,
        "manual_here_available": manual_here_available,
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

    # This GPS gate applies only to the explicit manual I'm Here action.
    # Game- and match-generated presence continues to create Billboard entries
    # directly through its existing lifecycle helpers without any GPS request.
    if not court.has_coordinates():
        return JsonResponse({
            "ok": False,
            "error": _("Manual check-in is unavailable because this Court Complex has no location configured."),
        }, status=409)
    try:
        device_latitude = float(data.get("latitude", ""))
        device_longitude = float(data.get("longitude", ""))
        if not (-90 <= device_latitude <= 90 and -180 <= device_longitude <= 180):
            raise ValueError
    except (TypeError, ValueError):
        return JsonResponse({
            "ok": False,
            "error": _("Location permission is required to check in at these courts."),
        }, status=400)

    proximity_distance_metres = distance_metres(
        device_latitude,
        device_longitude,
        float(court.latitude),
        float(court.longitude),
    )
    if proximity_distance_metres > settings.PFC_FRIENDLY_COURT_PROXIMITY_METERS:
        return JsonResponse({"ok": False, "error": _("You are not at the courts yet.")}, status=403)

    # No per-player daily limit — unlimited check-ins allowed.
    # Resolve date — use court-local date so Athens courts are not affected by server UTC offset
    raw_date = data.get("scheduled_date")
    court_local_now = get_court_local_now(court)
    try:
        sched_date = date.fromisoformat(raw_date) if raw_date else court_local_now.date()
    except ValueError:
        sched_date = court_local_now.date()

    # ── DEBUG: log server UTC vs court-local time ────────────────────────────────
    server_now = timezone.now()
    logger.info(
        "[PRESENCE][AT_COURTS] codename=%s court=%s(%s) "
        "server_utc=%s court_local=%s sched_date=%s",
        codename, court.name, court.timezone_name,
        server_now.strftime("%Y-%m-%d %H:%M:%S UTC"),
        court_local_now.strftime("%Y-%m-%d %H:%M:%S %Z"),
        sched_date,
    )
    print(
        f"[PRESENCE][AT_COURTS] codename={codename} court={court.name}({court.timezone_name}) "
        f"server_utc={server_now.strftime('%Y-%m-%d %H:%M:%S UTC')} "
        f"court_local={court_local_now.strftime('%Y-%m-%d %H:%M:%S %Z')} "
        f"sched_date={sched_date}"
    )
    # ───────────────────────────────────────────────────────────────────

    message = str(data.get("message", ""))[:200]
    # Anonymous presence: player is counted as verified but name is hidden publicly.
    is_anonymous = bool(data.get("is_anonymous", False))
    entry = BillboardEntry.objects.create(
        codename=codename,
        action_type="AT_COURTS",
        court_complex=court,
        scheduled_date=sched_date,
        message=message,
        is_anonymous=is_anonymous,
    )

    # Completing a GPS-protected manual check-in means the player has arrived
    # at this Court Complex.  Close every active Going declaration for this
    # player and complex in one persistent state transition so neither a
    # duplicate declaration nor an overdue reminder can trigger again.
    arrival_completed_at = timezone.now()
    completed_going_entry_ids = list(
        BillboardEntry.objects.filter(
            codename=codename,
            action_type="GOING_TO_COURTS",
            court_complex=court,
            is_active=True,
            going_status=BillboardEntry.GOING_STATUS_ACTIVE,
        ).values_list("pk", flat=True)
    )
    if completed_going_entry_ids:
        BillboardEntry.objects.filter(pk__in=completed_going_entry_ids).update(
            going_status=BillboardEntry.GOING_STATUS_ARRIVED,
            arrived_at=arrival_completed_at,
            is_active=False,
            updated_at=arrival_completed_at,
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
        "completed_going_entry_id": completed_going_entry_ids[0] if completed_going_entry_ids else None,
        "completed_going_entry_ids": completed_going_entry_ids,
    })


@csrf_exempt
@require_POST
def api_friendly_availability(request):
    """Persist the caller's Friendly pull preference independently of presence.

    The preference never creates presence by itself.  Friendly creator selection
    still requires a valid manual AT_COURTS entry at the same Court Complex.
    """
    codename = _get_codename(request)
    if not codename:
        return JsonResponse({"ok": False, "error": "Sign in before changing Friendly availability."}, status=401)
    try:
        data = json.loads(request.body or "{}")
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"ok": False, "error": "Invalid availability request."}, status=400)
    prefs, _ = UserPresencePrefs.objects.get_or_create(codename=codename.upper())
    prefs.available_for_friendly = bool(data.get("available_for_friendly", False))
    prefs.save(update_fields=["available_for_friendly", "updated_at"])
    return JsonResponse({
        "ok": True,
        "available_for_friendly": prefs.available_for_friendly,
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

    # No per-player daily limit — unlimited check-ins allowed.
    # Resolve date — use court-local date so Athens courts are not affected by server UTC offset
    court_local_now = get_court_local_now(court)
    raw_date = data.get("scheduled_date")
    try:
        sched_date = date.fromisoformat(raw_date) if raw_date else court_local_now.date()
    except ValueError:
        sched_date = court_local_now.date()

    # ── DEBUG: log server UTC vs court-local time ────────────────────────────────
    server_now = timezone.now()
    logger.info(
        "[PRESENCE][GOING] codename=%s court=%s(%s) "
        "server_utc=%s court_local=%s sched_date=%s",
        codename, court.name, court.timezone_name,
        server_now.strftime("%Y-%m-%d %H:%M:%S UTC"),
        court_local_now.strftime("%Y-%m-%d %H:%M:%S %Z"),
        sched_date,
    )
    print(
        f"[PRESENCE][GOING] codename={codename} court={court.name}({court.timezone_name}) "
        f"server_utc={server_now.strftime('%Y-%m-%d %H:%M:%S UTC')} "
        f"court_local={court_local_now.strftime('%Y-%m-%d %H:%M:%S %Z')} "
        f"sched_date={sched_date}"
    )
    # ───────────────────────────────────────────────────────────────────

    # Resolve the exact arrival moment in the selected Court Complex timezone.
    # The quick +30 choice is calculated server-side from the actual court-local
    # time so it is never rounded to a fixed half-hour slot.
    arrival_mode = str(data.get("arrival_mode", "manual"))
    if arrival_mode == "plus30":
        arrival_local = court_local_now + timedelta(minutes=30)
    else:
        raw_time = str(data.get("scheduled_time", "")).strip()
        try:
            local_clock = datetime.strptime(raw_time, "%H:%M").time()
        except ValueError:
            return JsonResponse({"ok": False, "error": _("Enter a valid arrival time.")}, status=400)
        arrival_local = court_local_now.replace(
            year=sched_date.year,
            month=sched_date.month,
            day=sched_date.day,
            hour=local_clock.hour,
            minute=local_clock.minute,
            second=0,
            microsecond=0,
        )

    sched_date = arrival_local.date()
    sched_time = arrival_local.strftime("%H:%M")
    message = str(data.get("message", ""))[:200]

    # A player can have only one active arrival declaration per Court Complex.
    # Replacing it closes the prior declaration persistently before recording
    # the new exact arrival time.
    try:
        with transaction.atomic():
            superseded_at = timezone.now()
            previous_active_entries = BillboardEntry.objects.select_for_update().filter(
                codename=codename,
                action_type="GOING_TO_COURTS",
                court_complex=court,
                is_active=True,
                going_status=BillboardEntry.GOING_STATUS_ACTIVE,
            )
            previous_active_entries.update(
                going_status=BillboardEntry.GOING_STATUS_CANCELED,
                canceled_at=superseded_at,
                is_active=False,
                updated_at=superseded_at,
            )
            entry = BillboardEntry.objects.create(
                codename=codename,
                action_type="GOING_TO_COURTS",
                court_complex=court,
                scheduled_date=sched_date,
                scheduled_time=sched_time,
                arrival_at=arrival_local.astimezone(datetime_timezone.utc),
                message=message,
            )
    except IntegrityError:
        # The database constraint preserves one active declaration even if two
        # requests race. Return the declaration created by the winning request.
        entry = BillboardEntry.objects.filter(
            codename=codename,
            action_type="GOING_TO_COURTS",
            court_complex=court,
            is_active=True,
            going_status=BillboardEntry.GOING_STATUS_ACTIVE,
        ).order_by("-created_at", "-pk").first()
        if not entry:
            return JsonResponse({"ok": False, "error": _("Unable to save arrival time. Please try again.")}, status=409)

    return JsonResponse({
        "ok": True,
        "entry_id": entry.pk,
        "court": court.name,
        "date": sched_date.isoformat(),
        "time": sched_time,
        "arrival_at": entry.arrival_at.isoformat(),
    })


@csrf_exempt
@require_POST
def api_cancel_going(request):
    """Persistently cancel one active Going declaration owned by the player."""
    codename = _get_codename(request)
    try:
        data = json.loads(request.body or "{}")
    except (json.JSONDecodeError, ValueError):
        data = {}
    if not codename:
        codename = str(data.get("codename", "")).upper()
    if not codename or len(codename) != 6:
        return JsonResponse({"ok": False, "error": _("Codename required")}, status=400)
    try:
        entry_id = int(data.get("entry_id"))
    except (TypeError, ValueError):
        return JsonResponse({"ok": False, "error": _("Going declaration not found.")}, status=404)

    entry = BillboardEntry.objects.filter(
        pk=entry_id,
        codename=codename,
        action_type="GOING_TO_COURTS",
        is_active=True,
        going_status=BillboardEntry.GOING_STATUS_ACTIVE,
    ).first()
    if not entry:
        return JsonResponse({"ok": False, "error": _("Going declaration not found.")}, status=404)

    entry.going_status = BillboardEntry.GOING_STATUS_CANCELED
    entry.canceled_at = timezone.now()
    entry.is_active = False
    entry.save(update_fields=["going_status", "canceled_at", "is_active", "updated_at"])
    return JsonResponse({"ok": True, "entry_id": entry.pk, "status": "canceled"})


@require_GET
def api_arrival_reminder(request):
    """Return the current player's due active Going declaration, if any.

    This endpoint is intentionally read-only. It powers the active/open/resume
    in-app reminder fallback and never creates an AT_COURTS presence by itself.
    """
    codename = _get_codename(request)
    if not codename:
        return JsonResponse({"ok": True, "due": None})
    now = timezone.now()
    entry = BillboardEntry.objects.filter(
        codename=codename,
        action_type="GOING_TO_COURTS",
        is_active=True,
        going_status=BillboardEntry.GOING_STATUS_ACTIVE,
        arrival_at__isnull=False,
    ).filter(arrival_at__lte=now).select_related("court_complex").order_by("arrival_at").first()
    if not entry:
        next_entry = BillboardEntry.objects.filter(
            codename=codename,
            action_type="GOING_TO_COURTS",
            is_active=True,
            going_status=BillboardEntry.GOING_STATUS_ACTIVE,
            arrival_at__gt=now,
        ).order_by("arrival_at").first()
        return JsonResponse({
            "ok": True,
            "due": None,
            "next_arrival_at": next_entry.arrival_at.isoformat() if next_entry else None,
        })
    return JsonResponse({
        "ok": True,
        "due": {
            "entry_id": entry.pk,
            "court_id": entry.court_complex_id,
            "court_name": entry.court_complex.name,
            "arrival_at": entry.arrival_at.isoformat(),
            "check_in_url": (
                f"/billboard/?action=arrival&court_id={entry.court_complex_id}"
                f"&going_entry_id={entry.pk}"
            ),
        },
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

    # Deactivate ALL active AT_COURTS entries for this player, regardless of age or source.
    # This includes manual check-ins, game-generated entries, and post-game grace entries.
    count = BillboardEntry.objects.filter(
        codename=codename,
        action_type="AT_COURTS",
        is_active=True,
    ).update(is_active=False)

    return JsonResponse({"ok": True, "deactivated": count})
