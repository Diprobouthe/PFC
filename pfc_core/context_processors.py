# Context Processor for Authentication
from .session_utils import SessionManager
from .team_session_utils import TeamSessionManager

def auth_context(request):
    """
    Add authentication context to all templates
    """
    # Get codename session data
    codename_context = SessionManager.get_session_context(request)
    
    # Get team session data
    team_context = TeamSessionManager.get_team_session_data(request)
    
    # Combine both contexts
    return {
        **codename_context,
        'team_session': team_context
    }

