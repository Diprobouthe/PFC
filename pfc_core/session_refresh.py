"""Legacy Team-session compatibility for pre-P4 transferred Mêlée events.

P4 keeps ``Player.team`` and existing Team-PIN session identity stable. Its
round assignments are resolved server-side and never enumerate sessions or
enable the obsolete client Team-session polling loop.
"""

import logging

from django.contrib.sessions.models import Session
from django.utils import timezone

logger = logging.getLogger(__name__)


def _is_assignment_based_melee_tournament(tournament):
    """Whether P4 must not touch legacy Team-session polling state."""
    return bool(
        tournament
        and getattr(tournament, "melee_roster_mode", None) == "assignment_based"
    )


def _active_player_sessions(player):
    """Yield decoded active sessions belonging to one authenticated Player."""
    for session in Session.objects.filter(expire_date__gte=timezone.now()):
        try:
            session_data = session.get_decoded()
        except Exception as exc:
            logger.error("Error decoding session %s: %s", session.session_key, exc)
            continue
        if session_data.get("player_id") == player.id:
            yield session, session_data


def set_player_melee_assignment_session(player, *, tournament=None, round=None):
    """Mark transient Mêlée context without changing the normal Team session.

    ``tournament`` and ``round`` are informational, non-authoritative session
    hints. Runtime authorization continues to resolve the Player in each exact
    Match via MatchPlayer/MeleeRoundAssignment.
    """
    # P4 assignment-based Mêlée does not use a Team-session projection or the
    # legacy 10-second client poll. Guard before querying or decoding sessions.
    if not player or _is_assignment_based_melee_tournament(tournament):
        return 0

    updated_count = 0
    for session, session_data in _active_player_sessions(player):
        try:
            session_data["in_melee_assignment"] = True
            if tournament is not None:
                session_data["melee_tournament_id"] = tournament.id
            if round is not None:
                session_data["melee_round_id"] = round.id
            session.session_data = Session.objects.encode(session_data)
            session.save(update_fields=["session_data"])
            updated_count += 1
        except Exception as exc:
            logger.error("Error updating session %s: %s", session.session_key, exc)
    return updated_count


def clear_player_melee_assignment_session(player, *, tournament=None):
    """End transient Mêlée context while preserving normal Team session keys."""
    # P4 never set this legacy transient context. Do not enumerate, decode, or
    # update sessions at completion for assignment-based tournaments.
    if not player or _is_assignment_based_melee_tournament(tournament):
        return 0

    updated_count = 0
    for session, session_data in _active_player_sessions(player):
        try:
            session_data["in_melee_assignment"] = False
            session_data.pop("melee_tournament_id", None)
            session_data.pop("melee_round_id", None)
            session.session_data = Session.objects.encode(session_data)
            session.save(update_fields=["session_data"])
            updated_count += 1
        except Exception as exc:
            logger.error("Error updating session %s: %s", session.session_key, exc)
    return updated_count


def refresh_legacy_player_team_session(player, team, *, in_melee_assignment=True):
    """Maintain a pre-P4 transferred Team session for a legacy tournament.

    This is intentionally not used by P4 assignment-based generation/shuffle.
    It exists only so an already-started legacy tournament can complete with
    the same transient Team/PIN session semantics it had before cutover.
    """
    if not player or not team:
        return 0

    updated_count = 0
    for session, session_data in _active_player_sessions(player):
        try:
            session_data["team_id"] = team.id
            session_data["team_name"] = team.name
            if team.pin:
                session_data["team_pin"] = team.pin
                session_data["team_session_active"] = True
                session_data["team_pin_session"] = {
                    "is_logged_in": True,
                    "team_pin": team.pin,
                    "team_name": team.name,
                    "team_id": team.id,
                    "login_time": timezone.now().isoformat(),
                }
            session_data["in_melee_assignment"] = in_melee_assignment
            session.session_data = Session.objects.encode(session_data)
            session.save(update_fields=["session_data"])
            updated_count += 1
        except Exception as exc:
            logger.error("Error updating legacy session %s: %s", session.session_key, exc)
    return updated_count


def refresh_player_team_session(
    player,
    in_melee_assignment=True,
    *,
    assignment_team=None,
    tournament=None,
    round=None,
):
    """Compatibility wrapper for legacy call sites.

    P4 deliberately ignores ``assignment_team`` and returns before session
    access: temporary competition Teams may never replace a Player's normal
    Team session or enable legacy fast polling.
    """
    if _is_assignment_based_melee_tournament(tournament):
        return 0
    if in_melee_assignment:
        return set_player_melee_assignment_session(
            player,
            tournament=tournament,
            round=round,
        )
    return clear_player_melee_assignment_session(player, tournament=tournament)


def restore_player_team_session(player, *, restored_team=None):
    """Compatibility wrapper ending transient Mêlée context only.

    ``restored_team`` is retained for old callers but is intentionally not used
    to overwrite an established normal Team session.
    """
    return clear_player_melee_assignment_session(player)


def refresh_multiple_players_team_sessions(
    players,
    in_melee_assignment=True,
    *,
    assignment_teams=None,
    tournament=None,
    round=None,
):
    """Refresh legacy transient Mêlée context for a set of Players."""
    # Guard before the per-player loop, avoiding all legacy full-session
    # enumeration for P4 generation and shuffle calls.
    if _is_assignment_based_melee_tournament(tournament):
        return 0

    total_updated = 0
    for player in players:
        total_updated += refresh_player_team_session(
            player,
            in_melee_assignment=in_melee_assignment,
            tournament=tournament,
            round=round,
        )
    logger.info(
        "Refreshed Mêlée session context for %s Players — %s sessions updated",
        len(players),
        total_updated,
    )
    return total_updated
