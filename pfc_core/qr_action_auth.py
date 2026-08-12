"""Ephemeral QR action proof for one existing match/game action page.

The proof is signed, bound to the current browser session and exact action path,
and is passed only in the rendered page/form. Client JavaScript removes it from
the address bar immediately, so a page refresh has no authorization proof.
"""

from urllib.parse import urlsplit
import json

from django.core import signing


QR_ACTION_SALT = "pfc.qr-action.v1"
QR_ACTION_MAX_AGE_SECONDS = 300


def issue_qr_action_token(request, player, action_url):
    """Issue a non-persistent proof for *player* and one exact action path."""
    if not request.session.session_key:
        request.session.save()
    return signing.dumps(
        {
            "player_id": player.pk,
            "path": urlsplit(action_url).path,
            "session_key": request.session.session_key,
        },
        salt=QR_ACTION_SALT,
        compress=True,
    )


def get_qr_action_player(request):
    """Return the scanned player for a valid proof scoped to this request path."""
    token = request.GET.get("qr_action") or request.POST.get("qr_action")
    if not token and request.content_type and 'application/json' in request.content_type:
        try:
            token = json.loads(request.body.decode('utf-8')).get('qr_action')
        except (ValueError, UnicodeDecodeError, AttributeError):
            token = None
    if not token:
        return None
    try:
        payload = signing.loads(
            token,
            salt=QR_ACTION_SALT,
            max_age=QR_ACTION_MAX_AGE_SECONDS,
        )
    except signing.BadSignature:
        return None

    if payload.get("path") != request.path:
        return None
    if payload.get("session_key") != request.session.session_key:
        return None

    from teams.models import Player
    try:
        return Player.objects.get(pk=payload.get("player_id"))
    except (Player.DoesNotExist, TypeError, ValueError):
        return None


def get_qr_action_token(request):
    """Expose only the opaque proof for a matching page/form handoff."""
    token = request.GET.get("qr_action") or request.POST.get("qr_action")
    return token if get_qr_action_player(request) else ""
