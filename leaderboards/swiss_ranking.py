"""
Swiss Tournament Ranking System with Buchholz Tie-Breaking
"""

import logging
from django.db.models import Q, F, Sum
from tournaments.models import Tournament, TournamentTeam, Stage
from matches.models import Match

logger = logging.getLogger(__name__)

def is_swiss_tournament(tournament):
    """Check if a tournament uses Swiss system (regular or smart)"""
    if tournament.format in ['swiss', 'smart_swiss']:
        return True
    
    # Check if any stage uses Swiss system
    if tournament.format == 'multi_stage':
        swiss_stages = tournament.stages.filter(format__in=['swiss', 'smart_swiss'])
        return swiss_stages.exists()
    
    return False

def is_wtf_tournament(tournament):
    """Check if a tournament uses WTF system"""
    if tournament.format == 'wtf':
        return True
    
    # Check if any stage uses WTF system
    if tournament.format == 'multi_stage':
        wtf_stages = tournament.stages.filter(format='wtf')
        return wtf_stages.exists()
    
    return False

def calculate_buchholz_scores(tournament, stage=None):
    """
    Calculate Buchholz scores for all teams in a tournament or stage.
    Buchholz score = sum of all opponents' Swiss points.
    Must be calculated after all Swiss points are updated.
    """
    logger.info(f"Calculating Buchholz scores for tournament {tournament.name}")
    
    # Get tournament teams
    if stage:
        # For multi-stage tournaments, only consider teams in this stage
        tournament_teams = TournamentTeam.objects.filter(
            tournament=tournament,
            current_stage_number=stage.stage_number,
            is_active=True
        )
        match_filter = Q(tournament=tournament, stage=stage, status='completed')
    else:
        tournament_teams = TournamentTeam.objects.filter(
            tournament=tournament,
            is_active=True
        )
        match_filter = Q(tournament=tournament, status='completed')
    
    # Calculate Buchholz for each team
    for team_tt in tournament_teams:
        buchholz_score = 0.0
        opponents_count = 0
        
        # Get all completed matches for this team
        team_matches = Match.objects.filter(match_filter).filter(
            Q(team1=team_tt.team) | Q(team2=team_tt.team)
        )
        
        for match in team_matches:
            # Determine opponent
            if match.team1 == team_tt.team:
                opponent = match.team2
            else:
                opponent = match.team1
            
            if opponent:
                # Get opponent's tournament team record
                try:
                    if stage:
                        opponent_tt = TournamentTeam.objects.get(
                            tournament=tournament,
                            team=opponent,
                            current_stage_number=stage.stage_number
                        )
                    else:
                        opponent_tt = TournamentTeam.objects.get(
                            tournament=tournament,
                            team=opponent
                        )
                    
                    # Add opponent's Swiss points to Buchholz score
                    buchholz_score += opponent_tt.swiss_points
                    opponents_count += 1
                    
                except TournamentTeam.DoesNotExist:
                    logger.warning(f"Opponent {opponent.name} not found in tournament teams")
                    continue
        
        # Handle bye rounds - typically count as playing against yourself
        if team_tt.received_bye_in_round:
            buchholz_score += team_tt.swiss_points
            opponents_count += 1
        
        # Update Buchholz score
        team_tt.buchholz_score = buchholz_score
        team_tt.save()
        
        logger.debug(f"{team_tt.team.name}: {team_tt.swiss_points} Swiss pts, {buchholz_score} Buchholz ({opponents_count} opponents)")
    
    logger.info(f"Buchholz calculation completed for {tournament_teams.count()} teams")

def get_swiss_rankings(tournament, stage=None):
    """
    Get Swiss tournament rankings with proper tie-breaking.
    Returns teams ordered by: Swiss points (desc), Buchholz score (desc), points scored (desc)
    """
    logger.info(f"Getting Swiss rankings for tournament {tournament.name}")
    
    # First, ensure all Swiss points are up to date
    update_all_swiss_points(tournament, stage)
    
    # Then calculate Buchholz scores
    calculate_buchholz_scores(tournament, stage)
    
    # Get tournament teams with proper ordering
    if stage:
        tournament_teams = TournamentTeam.objects.filter(
            tournament=tournament,
            current_stage_number=stage.stage_number,
            is_active=True
        )
    else:
        tournament_teams = TournamentTeam.objects.filter(
            tournament=tournament,
            is_active=True
        )
    
    # Calculate additional stats for each team
    rankings = []
    for i, team_tt in enumerate(tournament_teams.order_by('-swiss_points', '-buchholz_score', '-id')):
        # Get match statistics
        if stage:
            team_matches = Match.objects.filter(
                tournament=tournament,
                stage=stage,
                status='completed'
            ).filter(Q(team1=team_tt.team) | Q(team2=team_tt.team))
        else:
            team_matches = Match.objects.filter(
                tournament=tournament,
                status='completed'
            ).filter(Q(team1=team_tt.team) | Q(team2=team_tt.team))
        
        matches_played = team_matches.count()
        matches_won = team_matches.filter(winner=team_tt.team).count()
        matches_lost = matches_played - matches_won
        
        # Calculate points scored and conceded
        points_scored = 0
        points_conceded = 0
        
        for match in team_matches:
            if match.team1 == team_tt.team:
                points_scored += match.team1_score or 0
                points_conceded += match.team2_score or 0
            else:
                points_scored += match.team2_score or 0
                points_conceded += match.team1_score or 0
        
        rankings.append({
            'position': i + 1,
            'team': team_tt.team,
            'tournament_team': team_tt,
            'swiss_points': team_tt.swiss_points,
            'buchholz_score': team_tt.buchholz_score,
            'matches_played': matches_played,
            'matches_won': matches_won,
            'matches_lost': matches_lost,
            'points_scored': points_scored,
            'points_conceded': points_conceded,
            'point_difference': points_scored - points_conceded,
        })
    
    logger.info(f"Swiss rankings calculated for {len(rankings)} teams")
    return rankings

def update_all_swiss_points(tournament, stage=None):
    """Update Swiss points for all teams in a tournament or stage"""
    logger.info(f"Updating Swiss points for tournament {tournament.name}")
    
    if stage:
        tournament_teams = TournamentTeam.objects.filter(
            tournament=tournament,
            current_stage_number=stage.stage_number,
            is_active=True
        )
    else:
        tournament_teams = TournamentTeam.objects.filter(
            tournament=tournament,
            is_active=True
        )
    
    for team_tt in tournament_teams:
        team_tt.update_swiss_stats()
    
    logger.info(f"Swiss points updated for {tournament_teams.count()} teams")

def get_stage_rankings(tournament, stage_number):
    """Get rankings for a specific stage in a multi-stage tournament"""
    try:
        stage = tournament.stages.get(stage_number=stage_number)
        
        if stage.format in ['swiss', 'smart_swiss']:
            return get_swiss_rankings(tournament, stage)
        else:
            # For non-Swiss stages, use traditional ranking
            return get_traditional_rankings(tournament, stage)
            
    except Stage.DoesNotExist:
        logger.error(f"Stage {stage_number} not found in tournament {tournament.name}")
        return []

def get_traditional_rankings(tournament, stage=None):
    """Get traditional rankings (wins, point difference) for non-Swiss tournaments"""
    logger.info(f"Getting traditional rankings for tournament {tournament.name}")
    
    if stage:
        tournament_teams = TournamentTeam.objects.filter(
            tournament=tournament,
            current_stage_number=stage.stage_number,
            is_active=True
        )
        match_filter = Q(tournament=tournament, stage=stage, status='completed')
    else:
        tournament_teams = TournamentTeam.objects.filter(
            tournament=tournament,
            is_active=True
        )
        match_filter = Q(tournament=tournament, status='completed')
    
    rankings = []
    for team_tt in tournament_teams:
        # Get match statistics
        team_matches = Match.objects.filter(match_filter).filter(
            Q(team1=team_tt.team) | Q(team2=team_tt.team)
        )
        
        matches_played = team_matches.count()
        matches_won = team_matches.filter(winner=team_tt.team).count()
        matches_lost = matches_played - matches_won
        
        # Calculate points scored and conceded
        points_scored = 0
        points_conceded = 0
        
        for match in team_matches:
            if match.team1 == team_tt.team:
                points_scored += match.team1_score or 0
                points_conceded += match.team2_score or 0
            else:
                points_scored += match.team2_score or 0
                points_conceded += match.team1_score or 0
        
        rankings.append({
            'team': team_tt.team,
            'tournament_team': team_tt,
            'matches_played': matches_played,
            'matches_won': matches_won,
            'matches_lost': matches_lost,
            'points_scored': points_scored,
            'points_conceded': points_conceded,
            'point_difference': points_scored - points_conceded,
        })
    
    # Sort by wins (desc), then point difference (desc), then points scored (desc)
    rankings.sort(key=lambda x: (x['matches_won'], x['point_difference'], x['points_scored']), reverse=True)
    
    # Add positions
    for i, ranking in enumerate(rankings):
        ranking['position'] = i + 1
    
    logger.info(f"Traditional rankings calculated for {len(rankings)} teams")
    return rankings
