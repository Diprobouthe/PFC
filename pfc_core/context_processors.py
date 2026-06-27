# Context Processor for Authentication
from .session_utils import SessionManager
from .team_session_utils import TeamSessionManager


def auth_context(request):
    """
    Add authentication context to all templates.

    In addition to the standard session/team data, injects
    ``notify_player_id`` — the integer PK of the currently logged-in
    Player — so that base.html can open the per-player WebSocket
    notification channel (ws/invites/<player_id>/) without an extra
    DB query in the template.

    ``notify_player_id`` is None when no player is logged in, which
    prevents the global notification script from opening a connection
    for unauthenticated visitors.
    """
    # Get codename session data (includes logged_in_player Player instance)
    codename_context = SessionManager.get_session_context(request)

    # Get team session data
    team_context = TeamSessionManager.get_team_session_data(request)

    # Derive the Player PK for the global notification WebSocket.
    # logged_in_player is a Player model instance (or None) already
    # resolved by SessionManager.get_session_context.
    logged_in_player = codename_context.get('logged_in_player')
    notify_player_id = logged_in_player.pk if logged_in_player else None

    return {
        **codename_context,
        'team_session': team_context,
        'notify_player_id': notify_player_id,
    }
