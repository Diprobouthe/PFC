"""
WTF Tournament Ranking System with πετΑ Index
"""

import logging
from django.db.models import Q, F, Sum
from tournaments.models import Tournament, TournamentTeam, Stage
from matches.models import Match
from tournaments.wtf_algorithm import WTFAlgorithm

logger = logging.getLogger(__name__)

def is_wtf_tournament(tournament):
    """Check if a tournament uses WTF system"""
    if tournament.format == 'wtf':
        return True
    
    # Check if any stage uses WTF system
    if tournament.format == 'multi_stage':
        wtf_stages = tournament.stages.filter(format='wtf')
        return wtf_stages.exists()
    
    return False

def get_wtf_rankings(tournament, stage=None):
    """
    Get WTF rankings for a tournament or stage using πετΑ Index.
    
    Returns list of team rankings sorted by πετΑ Index (descending).
    """
    logger.info(f"Getting WTF rankings for tournament {tournament.name}")
    
    # Get tournament teams
    if stage:
        # For multi-stage tournaments, only consider teams in this stage
        tournament_teams = list(TournamentTeam.objects.filter(
            tournament=tournament,
            current_stage_number=stage.stage_number,
            is_active=True
        ).select_related('team'))
    else:
        tournament_teams = list(TournamentTeam.objects.filter(
            tournament=tournament,
            is_active=True
        ).select_related('team'))
    
    if not tournament_teams:
        logger.warning(f"No active teams found for WTF tournament {tournament.name}")
        return []
    
    # Use WTF algorithm to get rankings
    wtf_algorithm = WTFAlgorithm(tournament, stage)
    rankings = wtf_algorithm.get_wtf_rankings(tournament_teams)
    
    logger.info(f"Generated WTF rankings for {len(rankings)} teams")
    return rankings

def get_wtf_stage_rankings(tournament):
    """
    Get WTF rankings for all stages in a multi-stage tournament.
    
    Returns dict mapping stage_number to rankings list.
    """
    stage_rankings = {}
    
    for stage in tournament.stages.filter(format='wtf').order_by('stage_number'):
        rankings = get_wtf_rankings(tournament, stage)
        stage_rankings[stage.stage_number] = {
            'stage': stage,
            'rankings': rankings
        }
    
    return stage_rankings

def update_wtf_statistics(tournament, stage=None):
    """
    Update WTF-specific statistics for tournament teams.
    
    This includes πετΑ Index components and other WTF metrics.
    """
    logger.info(f"Updating WTF statistics for tournament {tournament.name}")
    
    # Get tournament teams
    if stage:
        tournament_teams = list(TournamentTeam.objects.filter(
            tournament=tournament,
            current_stage_number=stage.stage_number,
            is_active=True
        ).select_related('team'))
    else:
        tournament_teams = list(TournamentTeam.objects.filter(
            tournament=tournament,
            is_active=True
        ).select_related('team'))
    
    if not tournament_teams:
        return
    
    # Calculate πετΑ Index and components
    wtf_algorithm = WTFAlgorithm(tournament, stage)
    peta_indices = wtf_algorithm.calculate_peta_index(tournament_teams)
    
    # Update TournamentTeam objects with WTF statistics
    for tt in tournament_teams:
        team_id = tt.team.id
        peta_data = peta_indices.get(team_id, {})
        
        # Store WTF metrics in TournamentTeam
        # Note: These fields would need to be added to the TournamentTeam model
        # For now, we'll store them in a JSON field or create separate model
        tt.wtf_peta_index = peta_data.get('PI', 0.0)
        tt.wtf_sos = peta_data.get('SoS', 0.0)
        tt.wtf_qor = peta_data.get('QoR', 0.0)
        tt.wtf_ssf = peta_data.get('SSF', 0.0)
        tt.wtf_base_rating = peta_data.get('BR', 0.0)
        
        # Store raw values for debugging
        tt.wtf_sos_raw = peta_data.get('SoS_raw', 0.0)
        tt.wtf_qor_raw = peta_data.get('QoR_raw', 0.0)
        tt.wtf_ssf_raw = peta_data.get('SSF_raw', 0.0)
        tt.wtf_base_rating_raw = peta_data.get('BR_raw', 0.0)
        
        try:
            tt.save()
        except Exception as e:
            logger.warning(f"Could not save WTF statistics for {tt.team.name}: {e}")
    
    logger.info(f"Updated WTF statistics for {len(tournament_teams)} teams")

def get_wtf_team_details(tournament_team, tournament, stage=None):
    """
    Get detailed WTF metrics for a specific team.
    
    Returns dict with all πετΑ Index components and analysis.
    """
    wtf_algorithm = WTFAlgorithm(tournament, stage)
    
    # Calculate metrics for this team
    tournament_teams = [tournament_team]
    peta_indices = wtf_algorithm.calculate_peta_index(tournament_teams)
    
    team_id = tournament_team.team.id
    peta_data = peta_indices.get(team_id, {})
    
    # Get match history for analysis
    if stage:
        matches = Match.objects.filter(
            Q(team1=tournament_team.team) | Q(team2=tournament_team.team),
            tournament=tournament,
            stage=stage,
            status='completed'
        ).order_by('round_number')
    else:
        matches = Match.objects.filter(
            Q(team1=tournament_team.team) | Q(team2=tournament_team.team),
            tournament=tournament,
            status='completed'
        ).order_by('round_number')
    
    # Analyze match performance
    match_analysis = []
    for match in matches:
        is_team1 = match.team1 == tournament_team.team
        opponent = match.team2 if is_team1 else match.team1
        team_score = match.team1_score if is_team1 else match.team2_score
        opponent_score = match.team2_score if is_team1 else match.team1_score
        
        if team_score is not None and opponent_score is not None:
            margin = abs(team_score - opponent_score)
            won = team_score > opponent_score
            
            match_analysis.append({
                'round': match.round_number,
                'opponent': opponent.name,
                'score': f"{team_score}-{opponent_score}",
                'margin': margin,
                'won': won,
                'closeness': 1.0 - min(margin, 13) / 13  # Using default margin cap
            })
    
    return {
        'peta_index': peta_data.get('PI', 0.0),
        'sos': peta_data.get('SoS', 0.0),
        'qor': peta_data.get('QoR', 0.0),
        'ssf': peta_data.get('SSF', 0.0),
        'base_rating': peta_data.get('BR', 0.0),
        'sos_raw': peta_data.get('SoS_raw', 0.0),
        'qor_raw': peta_data.get('QoR_raw', 0.0),
        'ssf_raw': peta_data.get('SSF_raw', 0.0),
        'base_rating_raw': peta_data.get('BR_raw', 0.0),
        'matches_played': len(match_analysis),
        'match_analysis': match_analysis,
        'swiss_points': tournament_team.swiss_points,
    }

def compare_wtf_teams(team1_tt, team2_tt, tournament, stage=None):
    """
    Compare two teams using WTF metrics.
    
    Returns detailed comparison of πετΑ Index components.
    """
    wtf_algorithm = WTFAlgorithm(tournament, stage)
    
    # Calculate metrics for both teams
    tournament_teams = [team1_tt, team2_tt]
    peta_indices = wtf_algorithm.calculate_peta_index(tournament_teams)
    
    team1_data = peta_indices.get(team1_tt.team.id, {})
    team2_data = peta_indices.get(team2_tt.team.id, {})
    
    comparison = {
        'team1': {
            'name': team1_tt.team.name,
            'peta_index': team1_data.get('PI', 0.0),
            'sos': team1_data.get('SoS', 0.0),
            'qor': team1_data.get('QoR', 0.0),
            'ssf': team1_data.get('SSF', 0.0),
            'base_rating': team1_data.get('BR', 0.0),
            'swiss_points': team1_tt.swiss_points,
        },
        'team2': {
            'name': team2_tt.team.name,
            'peta_index': team2_data.get('PI', 0.0),
            'sos': team2_data.get('SoS', 0.0),
            'qor': team2_data.get('QoR', 0.0),
            'ssf': team2_data.get('SSF', 0.0),
            'base_rating': team2_data.get('BR', 0.0),
            'swiss_points': team2_tt.swiss_points,
        }
    }
    
    # Calculate differences
    comparison['differences'] = {
        'peta_index': team1_data.get('PI', 0.0) - team2_data.get('PI', 0.0),
        'sos': team1_data.get('SoS', 0.0) - team2_data.get('SoS', 0.0),
        'qor': team1_data.get('QoR', 0.0) - team2_data.get('QoR', 0.0),
        'ssf': team1_data.get('SSF', 0.0) - team2_data.get('SSF', 0.0),
        'base_rating': team1_data.get('BR', 0.0) - team2_data.get('BR', 0.0),
        'swiss_points': team1_tt.swiss_points - team2_tt.swiss_points,
    }
    
    return comparison
