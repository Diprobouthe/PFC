"""Authoritative request-time authorization for tournament Match mutations."""

from __future__ import annotations

from friendly_games.models import PlayerCodename
from pfc_core.qr_action_auth import get_qr_action_player
from pfc_core.team_access import request_has_team_access

from .melee_roster_resolution import resolve_player_match_side


def request_has_match_side_access(request, match, team) -> bool:
    """Return true only for staff, an established Team session, or a scoped Player proof.

    URL ``team_id`` values and browser-supplied identifiers never grant access.
    The existing session codename and one-page QR proof are resolved server-side
    and must map to the exact side of this concrete Match.
    """
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated and user.is_staff:
        return True

    if request_has_team_access(request, team):
        return True

    codename = request.session.get("player_codename")
    if codename:
        try:
            player = PlayerCodename.objects.get(codename=codename.upper()).player
        except PlayerCodename.DoesNotExist:
            player = None
        if player is not None and resolve_player_match_side(match, player) == team:
            return True

    qr_player = get_qr_action_player(request)
    return bool(qr_player and resolve_player_match_side(match, qr_player) == team)
