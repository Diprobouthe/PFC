"""Authenticated endpoints for optional PFC Web Push device subscriptions."""

import json

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST

from friendly_games.models import PlayerCodename

from .models import WebPushSubscription
from .push_notifications import valid_subscription_payload


def _current_player(request):
    codename = request.session.get("player_codename")
    if not codename:
        return None
    try:
        return PlayerCodename.objects.select_related("player").get(
            codename=codename.upper()
        ).player
    except PlayerCodename.DoesNotExist:
        return None


@require_GET
def push_config(request):
    """Return public configuration only; private VAPID data never leaves the server."""
    player = _current_player(request)
    if not player:
        return JsonResponse({"ok": False, "authenticated": False}, status=401)
    public_key = getattr(settings, "PFC_WEB_PUSH_VAPID_PUBLIC_KEY", "")
    return JsonResponse({
        "ok": True,
        "authenticated": True,
        "enabled": bool(public_key),
        "public_key": public_key,
    })


@require_POST
def subscribe(request):
    """Upsert one browser subscription for the authenticated current player."""
    player = _current_player(request)
    if not player:
        return JsonResponse({"ok": False, "error": "Not authenticated"}, status=401)
    try:
        payload = json.loads(request.body or "{}")
    except (TypeError, ValueError):
        return JsonResponse({"ok": False, "error": "Invalid subscription"}, status=400)
    cleaned = valid_subscription_payload(payload)
    if not cleaned:
        return JsonResponse({"ok": False, "error": "Invalid subscription"}, status=400)

    locale = request.LANGUAGE_CODE if getattr(request, "LANGUAGE_CODE", "") in {"en", "el"} else "en"
    subscription, created = WebPushSubscription.objects.update_or_create(
        endpoint=cleaned.pop("endpoint"),
        defaults={
            "player": player,
            "locale": locale,
            "is_active": True,
            **cleaned,
        },
    )
    return JsonResponse({"ok": True, "created": created, "subscription_id": subscription.pk})


@require_POST
def unsubscribe(request):
    """Deactivate a supplied device subscription owned by the current player."""
    player = _current_player(request)
    if not player:
        return JsonResponse({"ok": False, "error": "Not authenticated"}, status=401)
    try:
        endpoint = str(json.loads(request.body or "{}").get("endpoint", "")).strip()
    except (TypeError, ValueError):
        endpoint = ""
    if not endpoint:
        return JsonResponse({"ok": False, "error": "Invalid subscription"}, status=400)
    WebPushSubscription.objects.filter(player=player, endpoint=endpoint).update(is_active=False)
    return JsonResponse({"ok": True})
