"""
Utility functions for team and player statistics
"""

def get_recent_matches_with_participation(player, matches):
    """
    Get recent matches with participation data for a player.
    Returns match data with 'played' flag indicating if player actually participated.
    """
    recent_matches = []
    
    try:
        from matches.models_participant import TeamMatchParticipant
        
        for match in matches:
            # Check if player has participation record for this match
            participation = TeamMatchParticipant.objects.filter(
                match=match,
                player=player
            ).first()
            
            # Determine opponent team
            if match.team1 == player.team:
                opponent_team = match.team2.name
                team_score = match.team1_score
                opponent_score = match.team2_score
                won = match.winner == match.team1 if match.winner else False
            else:
                opponent_team = match.team1.name
                team_score = match.team2_score
                opponent_score = match.team1_score
                won = match.winner == match.team2 if match.winner else False
            
            match_data = {
                'date': match.end_time or match.start_time,
                'opponent_team': opponent_team,
                'team_score': team_score,
                'opponent_score': opponent_score,
                'played': participation.played if participation else False,
                'position': participation.position if participation and participation.played else None,
                'won': won if participation and participation.played else False,
                'match_id': match.id,
                'tournament': match.tournament.name if match.tournament else 'Unknown'
            }
            
            recent_matches.append(match_data)
            
    except ImportError:
        # Fallback to old method if TeamMatchParticipant doesn't exist yet
        for match in matches:
            # Determine opponent team
            if match.team1 == player.team:
                opponent_team = match.team2.name
                team_score = match.team1_score
                opponent_score = match.team2_score
                won = match.winner == match.team1 if match.winner else False
            else:
                opponent_team = match.team1.name
                team_score = match.team2_score
                opponent_score = match.team1_score
                won = match.winner == match.team2 if match.winner else False
            
            # Assume all players played (old behavior)
            match_data = {
                'date': match.end_time or match.start_time,
                'opponent_team': opponent_team,
                'team_score': team_score,
                'opponent_score': opponent_score,
                'played': True,  # Assume played in old system
                'position': 'Unknown',
                'won': won,
                'match_id': match.id,
                'tournament': match.tournament.name if match.tournament else 'Unknown'
            }
            
            recent_matches.append(match_data)
    
    return recent_matches


def get_player_participation_summary(player):
    """
    Get summary of player participation across all matches.
    Returns dict with total matches, matches played, DNP count, etc.
    """
    try:
        from matches.models_participant import TeamMatchParticipant
        from matches.models import Match
        
        # Get all matches where player's team participated
        team_matches = Match.objects.filter(
            models.Q(team1=player.team) | models.Q(team2=player.team),
            status='completed'
        )
        
        total_team_matches = team_matches.count()
        
        # Get participation records
        participations = TeamMatchParticipant.objects.filter(
            player=player,
            match__in=team_matches
        )
        
        matches_with_participation_data = participations.count()
        matches_played = participations.filter(played=True).count()
        matches_dnp = participations.filter(played=False).count()
        
        # Matches without participation data (legacy matches)
        matches_without_data = total_team_matches - matches_with_participation_data
        
        return {
            'total_team_matches': total_team_matches,
            'matches_with_data': matches_with_participation_data,
            'matches_without_data': matches_without_data,
            'matches_played': matches_played,
            'matches_dnp': matches_dnp,
            'participation_rate': round((matches_played / total_team_matches * 100), 1) if total_team_matches > 0 else 0
        }
        
    except ImportError:
        # Fallback if TeamMatchParticipant doesn't exist
        from matches.models import Match
        
        team_matches = Match.objects.filter(
            models.Q(team1=player.team) | models.Q(team2=player.team),
            status='completed'
        ).count()
        
        return {
            'total_team_matches': team_matches,
            'matches_with_data': 0,
            'matches_without_data': team_matches,
            'matches_played': team_matches,  # Assume all played in old system
            'matches_dnp': 0,
            'participation_rate': 100.0 if team_matches > 0 else 0
        }



# ============================================================================
# Team PIN Automation Utilities
# ============================================================================

def get_team_pin_from_codename(codename):
    """
    Get team PIN for a player based on their codename.
    
    Args:
        codename (str): Player's codename (e.g., "P11111")
    
    Returns:
        dict: Dictionary containing team info and PIN, or None if not found
        {
            'team_name': str,
            'team_pin': str,
            'player_name': str,
            'player_id': int,
            'team_id': int
        }
    """
    try:
        from friendly_games.models import PlayerCodename
        
        # Find the player codename object
        player_codename = PlayerCodename.objects.select_related(
            'player__team'
        ).get(codename=codename)
        
        player = player_codename.player
        team = player.team
        
        return {
            'team_name': team.name,
            'team_pin': team.pin,
            'player_name': player.name,
            'player_id': player.id,
            'team_id': team.id,
            'is_captain': player.is_captain
        }
    except Exception as e:
        # Return None if codename not found or any error occurs
        return None


def get_team_pin_from_player(player):
    """
    Get team PIN for a player object.
    
    Args:
        player: Player model instance
    
    Returns:
        str: Team PIN or None if player has no team
    """
    try:
        if player and hasattr(player, 'team') and player.team:
            return player.team.pin
    except Exception:
        pass
    return None


def get_player_from_session(request):
    """
    Get player object from session data.
    
    Args:
        request: Django request object
    
    Returns:
        Player: Player object or None
    """
    try:
        from teams.models import Player
        
        player_id = request.session.get('player_id')
        if player_id:
            return Player.objects.select_related('team').get(id=player_id)
    except Exception:
        pass
    return None


def get_team_info_from_session(request):
    """
    Get complete team information from session.
    Checks team login, player_id, and codename in session.
    
    Args:
        request: Django request object
    
    Returns:
        dict: Team info dictionary or None
    """
    from pfc_core.team_session_utils import TeamSessionManager
    
    # First priority: Check if team is logged in directly via Team Login
    if TeamSessionManager.is_team_logged_in(request):
        team_pin = TeamSessionManager.get_team_pin(request)
        team_name = TeamSessionManager.get_team_name(request)
        
        # Get full team info from PIN
        try:
            from teams.models import Team
            team = Team.objects.get(pin=team_pin)
            return {
                'team_name': team_name,
                'team_pin': team_pin,
                'team_id': team.id,
                'player_name': None,  # No specific player when team logs in
                'player_id': None,
                'is_captain': False  # Not applicable for team login
            }
        except Team.DoesNotExist:
            pass
    
    # Second priority: Try to get from player_id
    player = get_player_from_session(request)
    if player:
        return {
            'team_name': player.team.name,
            'team_pin': player.team.pin,
            'player_name': player.name,
            'player_id': player.id,
            'team_id': player.team.id,
            'is_captain': player.is_captain
        }
    
    # Third priority: Try to get from codename if player_id not found
    codename = request.session.get('player_codename')
    if codename:
        return get_team_pin_from_codename(codename)
    
    return None
