"""Shared authorisation helper for existing PFC Team sessions.

This module deliberately recognises the Team session formats already used by
PFC: the legacy ``team_id`` compatibility key, the current Team PIN session,
and the older TeamSessionManager PIN key.  It does not create a new ownership
model or change any Team membership semantics.
"""

from __future__ import annotations

import secrets

from pfc_core.session_utils import TeamPinSessionManager
from pfc_core.team_session_utils import TeamSessionManager


def request_has_team_access(request, team) -> bool:
    """Return whether this request is authorised to act for ``team``.

    Staff retain an explicit operational override.  Ordinary requests must
    already hold one of PFC's established Team sessions for the target Team.
    """
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated and user.is_staff:
        return True

    session_team_id = request.session.get("team_id")
    if session_team_id is not None and str(session_team_id) == str(team.pk):
        return True

    expected_pin = str(team.pin or "").upper()
    if not expected_pin:
        return False

    pins = (
        TeamPinSessionManager.get_logged_in_pin(request),
        TeamSessionManager.get_team_pin(request),
    )
    return any(
        pin and secrets.compare_digest(str(pin).upper(), expected_pin)
        for pin in pins
    )


def establish_team_access_session(request, team) -> None:
    """Persist the existing Team session state after a successful PIN action."""
    request.session["team_id"] = team.pk
    request.session["team_name"] = team.name
    TeamPinSessionManager.login_team(request, team.pin)
