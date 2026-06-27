"""
Session Refresh Utilities
Utilities to update player sessions when their team assignments change.
"""

import logging
from django.contrib.sessions.models import Session
from django.utils import timezone
from pfc_core.session_utils import TeamPinSessionManager

logger = logging.getLogger(__name__)


def refresh_player_team_session(player, in_melee_assignment=True):
    """
    Refresh the team session data for a specific player across all their active sessions.

    This is crucial for Mêlée tournaments where players are automatically assigned to new teams.
    Without this, players would need to logout/login to see their new team PIN.

    Args:
        player:               The Player object whose team has changed.
        in_melee_assignment:  True  → player has just been assigned/reshuffled into a Mêlée team;
                              False → player has been restored to their original team after the
                                      tournament ended.  Controls the client-side polling scope:
                                      True  → fast 10-second /auth/team/check/ loop is active.
                                      False → no recurring polling; single on-load check only.
    """
    if not player or not player.team:
        logger.warning(f"Cannot refresh session for player {player.id if player else 'None'} - no team assigned")
        return 0

    updated_count = 0

    try:
        # Get all active sessions
        active_sessions = Session.objects.filter(expire_date__gte=timezone.now())

        for session in active_sessions:
            try:
                session_data = session.get_decoded()

                # Check if this session belongs to our player
                if session_data.get('player_id') == player.id:
                    # Update team-related session data
                    session_data['team_id'] = player.team.id
                    session_data['team_name'] = player.team.name

                    # Update team PIN if the team has one
                    if player.team.pin:
                        session_data['team_pin'] = player.team.pin
                        session_data['team_session_active'] = True

                        # Also update TeamPinSessionManager data
                        session_data['team_pin_session'] = {
                            'is_logged_in': True,
                            'team_pin': player.team.pin,
                            'team_name': player.team.name,
                            'team_id': player.team.id,
                            'login_time': timezone.now().isoformat()
                        }

                    # Signal to the client whether fast polling should be active.
                    # True  → player is in an active Mêlée assignment window.
                    # False → player has been restored; no recurring polling needed.
                    session_data['in_melee_assignment'] = in_melee_assignment

                    # Save the updated session
                    session.session_data = Session.objects.encode(session_data)
                    session.save()

                    updated_count += 1
                    logger.info(
                        f"Refreshed team session for player {player.name} (ID: {player.id}) "
                        f"- new team: {player.team.name}, in_melee_assignment={in_melee_assignment}"
                    )

            except Exception as e:
                logger.error(f"Error updating session {session.session_key}: {e}")
                continue

    except Exception as e:
        logger.error(f"Error refreshing player team session for player {player.id}: {e}")

    return updated_count


def restore_player_team_session(player):
    """
    Convenience wrapper: refresh session after restoring a player to their original team.
    Sets in_melee_assignment=False so the client stops fast polling.
    """
    return refresh_player_team_session(player, in_melee_assignment=False)


def refresh_multiple_players_team_sessions(players, in_melee_assignment=True):
    """
    Refresh team session data for multiple players at once.

    Args:
        players:              List or QuerySet of Player objects whose teams have changed.
        in_melee_assignment:  Passed through to refresh_player_team_session for each player.

    Returns:
        int: Total number of sessions updated
    """
    total_updated = 0

    for player in players:
        updated = refresh_player_team_session(player, in_melee_assignment=in_melee_assignment)
        total_updated += updated

    logger.info(f"Refreshed team sessions for {len(players)} players - {total_updated} sessions updated")
    return total_updated
