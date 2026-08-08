"""
billboard/community_presence_views.py
======================================
API endpoints for the community-reported presence count feature.

Endpoints:
  POST /billboard/api/community-report/         — report or update the total count
  POST /billboard/api/community-confirm/        — confirm the current count
  GET  /billboard/api/community-status/<court>/ — get current report for a court
"""
import json
import logging

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from courts.models import CourtComplex
from billboard.community_presence import CommunityPresenceReport

logger = logging.getLogger('billboard.presence')


def _get_codename(request):
    """Return the session codename (uppercase) or None."""
    codename = request.session.get("player_codename")
    if codename:
        return codename.upper()
    return None


def _report_to_dict(report):
    """Serialise a CommunityPresenceReport to a JSON-safe dict."""
    if report is None:
        return None
    return {
        "reported_count":     report.reported_count,
        "confirmation_count": report.confirmation_count,
        "minutes_ago":        report.minutes_ago(),
        "is_stale":           report.is_stale(),
        "court_id":           report.court_complex_id,
        "court_name":         report.court_complex.name,
    }


@csrf_exempt
@require_POST
def api_community_report(request):
    """
    POST /billboard/api/community-report/
    Body (JSON):
        court_id : int
        count    : int  (1–999)

    Creates or updates the community presence report for the given court.
    Any logged-in player may call this.
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

    court_id = data.get("court_id")
    if not court_id:
        return JsonResponse({"ok": False, "error": "court_id required"}, status=400)
    court = CourtComplex.objects.filter(pk=court_id).first()
    if not court:
        return JsonResponse({"ok": False, "error": "Court not found"}, status=404)

    try:
        count = int(data.get("count", 0))
    except (TypeError, ValueError):
        return JsonResponse({"ok": False, "error": "count must be an integer"}, status=400)
    if count < 1 or count > 999:
        return JsonResponse({"ok": False, "error": "count must be between 1 and 999"}, status=400)

    report = CommunityPresenceReport.create_or_update(court, count, codename)
    return JsonResponse({"ok": True, "report": _report_to_dict(report)})


@csrf_exempt
@require_POST
def api_community_confirm(request):
    """
    POST /billboard/api/community-confirm/
    Body (JSON):
        court_id : int

    Confirms the current community presence count for the given court.
    Resets the staleness timer.  Idempotent per codename.
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

    court_id = data.get("court_id")
    if not court_id:
        return JsonResponse({"ok": False, "error": "court_id required"}, status=400)
    court = CourtComplex.objects.filter(pk=court_id).first()
    if not court:
        return JsonResponse({"ok": False, "error": "Court not found"}, status=404)

    report = CommunityPresenceReport.get_active_for_court(court)
    if not report:
        return JsonResponse({"ok": False, "error": "No active report for this court"}, status=404)

    report.add_confirmation(codename)
    return JsonResponse({"ok": True, "report": _report_to_dict(report)})


@require_GET
def api_community_status(request, court_id):
    """
    GET /billboard/api/community-status/<court_id>/
    Returns the current active community presence report for the given court,
    or null if no active (non-stale) report exists.
    """
    court = CourtComplex.objects.filter(pk=court_id).first()
    if not court:
        return JsonResponse({"ok": False, "error": "Court not found"}, status=404)

    report = CommunityPresenceReport.get_active_for_court(court)
    return JsonResponse({"ok": True, "report": _report_to_dict(report)})
