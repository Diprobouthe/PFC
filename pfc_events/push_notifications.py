"""Transient PFC notification delivery.

This module intentionally has no Match-state persistence. It delivers prompts
only after the surrounding database transaction commits successfully. The
existing Match/Friendly Game rows and Smart resolver remain authoritative.
"""

import json
import logging
from urllib.parse import urlparse

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from .models import WebPushSubscription

logger = logging.getLogger(__name__)

CONTINUE_TEXT = {
    "el": "Πάτησε το κεντρικό κουμπί για να συνεχίσεις.",
    "en": "Tap the central button to continue.",
}


def _locale(value):
    return "el" if str(value or "").lower().startswith("el") else "en"


def _safe_preview(value, limit=160):
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return f"{text[:limit - 1].rstrip()}…"


def _push_enabled():
    return bool(
        getattr(settings, "PFC_WEB_PUSH_VAPID_PUBLIC_KEY", "")
        and getattr(settings, "PFC_WEB_PUSH_VAPID_PRIVATE_KEY", "")
        and getattr(settings, "PFC_WEB_PUSH_VAPID_SUBJECT", "")
    )


def _send_open_session_event(player_id, event_type, payload):
    """Use the existing authenticated per-player InviteConsumer group."""
    layer = get_channel_layer()
    if layer is None:
        return
    try:
        async_to_sync(layer.group_send)(
            f"player_{player_id}",
            {"type": event_type, **payload},
        )
    except Exception as exc:
        logger.warning("Could not send transient event %s to player %s: %s", event_type, player_id, exc)


def _send_web_push(player_id, payload, dedupe_key=None, ttl=90, locale=None):
    """Deliver a small encrypted Push payload to active devices for one player."""
    if dedupe_key:
        cache_key = f"pfc-push:{dedupe_key}"
        if not cache.add(cache_key, True, timeout=45):
            return

    if not _push_enabled():
        return

    try:
        from pywebpush import WebPushException, webpush
    except ImportError:
        logger.warning("Web Push is configured but pywebpush is unavailable")
        return

    subscriptions_query = WebPushSubscription.objects.filter(
        player_id=player_id,
        is_active=True,
    )
    if locale:
        subscriptions_query = subscriptions_query.filter(locale=locale)
    subscriptions = list(subscriptions_query)
    if not subscriptions:
        return

    vapid_claims = {"sub": settings.PFC_WEB_PUSH_VAPID_SUBJECT}
    serialized_payload = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    for subscription in subscriptions:
        try:
            webpush(
                subscription_info={
                    "endpoint": subscription.endpoint,
                    "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth},
                },
                data=serialized_payload,
                vapid_private_key=settings.PFC_WEB_PUSH_VAPID_PRIVATE_KEY,
                vapid_claims=vapid_claims,
                ttl=ttl,
            )
            WebPushSubscription.objects.filter(pk=subscription.pk).update(
                is_active=True,
                last_success_at=timezone.now(),
            )
        except WebPushException as exc:
            response = getattr(exc, "response", None)
            status_code = getattr(response, "status_code", None)
            if status_code in (404, 410):
                WebPushSubscription.objects.filter(pk=subscription.pk).update(is_active=False)
                logger.info("Removed invalid Web Push subscription %s (%s)", subscription.pk, status_code)
            else:
                logger.warning("Web Push delivery failed for subscription %s: %s", subscription.pk, exc)
        except Exception as exc:
            logger.warning("Unexpected Web Push delivery failure for subscription %s: %s", subscription.pk, exc)


def _schedule_after_commit(callback):
    """Ensure notification delivery never runs for a rolled-back state change."""
    transaction.on_commit(callback)


def notify_invitation_created(invitation):
    """Deliver Push for any persisted Invitation, independent of invite subtype."""
    recipient_id = invitation.recipient_id
    sender_name = invitation.sender.name
    invite_token = str(invitation.token)
    message = invitation.message or invitation.play_notes or ""
    invite_type = invitation.invite_type

    def deliver():
        locales = {
            _locale(value)
            for value in WebPushSubscription.objects.filter(
                player_id=recipient_id, is_active=True
            ).values_list("locale", flat=True)
        }
        for locale in locales:
            if message:
                body = f"{sender_name}: {_safe_preview(message)}"
            elif locale == "el":
                body = (
                    f"Ο/Η {sender_name} σού έστειλε πρόσκληση ομάδας."
                    if invite_type == "team_build"
                    else f"Ο/Η {sender_name} σού έστειλε πρόσκληση για παιχνίδι."
                )
            else:
                body = (
                    f"{sender_name} sent you a team invitation."
                    if invite_type == "team_build"
                    else f"{sender_name} sent you a play invitation."
                )
            _send_web_push(
                recipient_id,
                {
                    "type": "invitation",
                    "title": "PFC",
                    "body": body,
                    "tag": f"pfc-invitation-{invite_token}",
                    "url": "/invites/",
                },
                dedupe_key=f"invitation:{invite_token}:{locale}",
                ttl=300,
                locale=locale,
            )

    _schedule_after_commit(deliver)


def _match_body(event_kind, locale):
    continuation = CONTINUE_TEXT[locale]
    greek = locale == "el"
    if event_kind == "new_match":
        lead = "Ένας νέος αγώνας είναι διαθέσιμος και χρειάζεται ενέργεια από την πλευρά σου." if greek else "A new match is available and requires action from your side."
    elif event_kind == "opponent_started":
        lead = "Η αντίπαλη ομάδα ξεκίνησε τον αγώνα και περιμένει τη δική σου πλευρά." if greek else "The opposing team has started the match and is waiting for your side."
    elif event_kind == "result_validation":
        lead = "Η αντίπαλη ομάδα υπέβαλε αποτέλεσμα και περιμένει την επιβεβαίωσή σου." if greek else "The opposing team submitted a result and is waiting for your validation."
    else:
        lead = "Υπάρχει νέα ενέργεια για τον αγώνα σου." if greek else "There is a new action for your match."
    return f"{lead} {continuation}"


def notify_match_action_required(players, event_kind, object_type, object_id):
    """Send transient action prompts after commit to unique affected players.

    The event carries no score, Match status, or resolved next URL. The central
    PFC button remains the sole current-action resolver.
    """
    player_ids = sorted({
        player if isinstance(player, int) else getattr(player, "id", None)
        for player in players
        if (isinstance(player, int) and player > 0) or getattr(player, "id", None)
    })
    player_ids = [player_id for player_id in player_ids if player_id]
    if not player_ids:
        return

    def deliver():
        for player_id in player_ids:
            # The open-session payload intentionally contains only a prompt.
            _send_open_session_event(
                player_id,
                "match.action_required",
                {
                    "event_kind": event_kind,
                    "object_type": object_type,
                    "object_id": object_id,
                },
            )

            # The same prompt is sent to subscribed devices. Each device gets a
            # locale-specific body; clicking only opens/focuses PFC root.
            locales = {
                _locale(value)
                for value in WebPushSubscription.objects.filter(
                    player_id=player_id, is_active=True
                ).values_list("locale", flat=True)
            }
            for locale in locales:
                _send_web_push(
                    player_id,
                    {
                        "type": "match_action_required",
                        "title": "PFC",
                        "body": _match_body(event_kind, locale),
                        "tag": f"pfc-match-{object_type}-{object_id}",
                        "url": "/",
                    },
                    dedupe_key=f"match:{object_type}:{object_id}:{event_kind}:{player_id}:{locale}",
                    ttl=90,
                    locale=locale,
                )

    _schedule_after_commit(deliver)


def valid_subscription_payload(payload):
    """Return sanitized subscription values or None for malformed input."""
    if not isinstance(payload, dict):
        return None
    endpoint = str(payload.get("endpoint", "")).strip()
    keys = payload.get("keys") or {}
    p256dh = str(keys.get("p256dh", "")).strip()
    auth = str(keys.get("auth", "")).strip()
    parsed = urlparse(endpoint)
    if parsed.scheme != "https" or not parsed.netloc or not p256dh or not auth:
        return None
    return {
        "endpoint": endpoint,
        "p256dh": p256dh[:255],
        "auth": auth[:255],
        "content_encoding": str(payload.get("contentEncoding", "aes128gcm"))[:32],
    }
