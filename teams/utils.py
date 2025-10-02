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

