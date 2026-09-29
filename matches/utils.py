from django.utils.translation import gettext as _
import logging
import random
from courts.models import Court

logger = logging.getLogger(__name__)

def detect_match_type(team1_players, team2_players):
    """
    Detect match type based on the number of players from each team.
    
    Args:
        team1_players: List of players from team 1
        team2_players: List of players from team 2
        
    Returns:
        tuple: (match_type, team1_count, team2_count)
            match_type: String - 'doublet', 'triplet', 'tete_a_tete', or 'mixed'
            team1_count: Integer - Number of players from team 1
            team2_count: Integer - Number of players from team 2
    """
    team1_count = len(team1_players)
    team2_count = len(team2_players)
    
    # Check if teams have different player counts (mixed match)
    if team1_count != team2_count:
        return 'mixed', team1_count, team2_count
    
    # Determine match type based on player count
    if team1_count == 1:
        return 'tete_a_tete', team1_count, team2_count
    elif team1_count == 2:
        return 'doublet', team1_count, team2_count
    elif team1_count == 3:
        return 'triplet', team1_count, team2_count
    else:
        # Default to 'unknown' for unexpected player counts
        logger.warning(f"Unexpected player count: {team1_count} vs {team2_count}")
        return 'unknown', team1_count, team2_count

def validate_match_type(match_type, team1_count, team2_count, tournament):
    """
    Validate if the detected match type is allowed in the tournament.
    
    Args:
        match_type: String - 'doublet', 'triplet', 'tete_a_tete', 'mixed', or 'unknown'
        team1_count: Integer - Number of players from team 1
        team2_count: Integer - Number of players from team 2
        tournament: Tournament object
        
    Returns:
        tuple: (is_valid, error_message)
            is_valid: Boolean - True if match type is valid, False otherwise
            error_message: String - Error message if match type is invalid, None otherwise
    """
    # Get tournament configuration
    config = getattr(tournament, 'allowed_match_types', None)
    
    # If no configuration is set, allow all match types (backward compatibility)
    if not config:
        return True, None
    
    # For mixed matches, check if mixed formats are allowed
    if match_type == 'mixed':
        if not config.get('allow_mixed', False):
            # Provide specific error message about player counts
            return False, _("Mixed matches are not allowed in this tournament. Both teams must have the same number of players. Team 1 has {} players, Team 2 has {} players.").format(team1_count, team2_count)
    
    # Check if the match type is in the allowed list
    allowed_types = config.get('allowed_match_types', [])
    if not allowed_types or match_type in allowed_types:
        return True, None
    
    # If we get here, the match type is not allowed - provide specific guidance
    if match_type == 'doublet':
        required_count = get_required_player_count(allowed_types)
        error_message = _("Doublet matches (2 players per team) are not allowed in this tournament. Please select {} players per team.").format(required_count)
    elif match_type == 'triplet':
        required_count = get_required_player_count(allowed_types)
        error_message = _("Triplet matches (3 players per team) are not allowed in this tournament. Please select {} players per team.").format(required_count)
    elif match_type == 'tete_a_tete':
        required_count = get_required_player_count(allowed_types)
        error_message = _("Tête-à-tête matches (1 player per team) are not allowed in this tournament. Please select {} players per team.").format(required_count)
    else:
        error_message = _("This match format ({}) is not allowed in this tournament. Allowed formats: {}").format(
            get_match_type_display(match_type),
            ", ".join([get_match_type_display(t) for t in allowed_types])
        )
    return False, error_message

def get_required_player_count(allowed_types):
    """
    Helper function to determine the required player count based on allowed match types.
    
    Args:
        allowed_types: List of allowed match types
        
    Returns:
        Integer: Required player count (1, 2, or 3) or None if multiple types are allowed
    """
    if len(allowed_types) == 1:
        if 'triplet' in allowed_types:
            return 3
        elif 'doublet' in allowed_types:
            return 2
        elif 'tete_a_tete' in allowed_types:
            return 1
    return "the correct number of"  # Generic message if multiple types are allowed

def get_match_type_display(match_type):
    """
    Get a human-readable display name for a match type.
    
    Args:
        match_type: String - 'doublet', 'triplet', 'tete_a_tete', 'mixed', or 'unknown'
        
    Returns:
        String: Human-readable display name
    """
    display_names = {
        'doublet': _("Doublet (2 players)"),
        'triplet': _("Triplet (3 players)"),
        'tete_a_tete': _("Tête-à-tête (1 player)"),
        'mixed': _("Mixed format"),
        'unknown': _("Unknown format")
    }
    return display_names.get(match_type, match_type)

def auto_assign_court(match):
    """Compatibility wrapper for the centralized activation transition.

    Legacy callers receive the assigned Court only after the Match, Court, and
    occupancy invariant have been committed together.  New code should call
    ``matches.lifecycle.activate_verified_match`` directly so it can inspect the
    complete outcome rather than performing a second state transition.
    """
    from .lifecycle import MatchLifecycleError, activate_verified_match

    try:
        outcome = activate_verified_match(match.id)
    except MatchLifecycleError as exc:
        logger.warning("Court allocation was rejected for Match %s: %s", match.id, exc)
        return None
    if not outcome.activated:
        return None
    match.refresh_from_db(fields=["court", "status", "waiting_for_court"])
    return match.court

def get_court_assignment_status(match):
    """
    Get a status message for court assignment.
    
    Args:
        match: Match object
        
    Returns:
        String: Status message
    """
    if match.court:
        return _("The court %(court_name)s has been assigned to your match.") % {
            'court_name': match.court.name,
        }
    elif match.waiting_for_court:
        return _("Your match is waiting for a court to become available.")
    else:
        return _("No court has been assigned to your match yet.")
