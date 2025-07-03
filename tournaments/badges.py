# tournaments/badges.py
"""
Tournament Badge Management System

This module handles automatic badge assignment for tournament completion
without interfering with the existing match creation mechanism.
"""

import logging
from django.utils import timezone
from teams.models import TeamProfile

logger = logging.getLogger('tournaments')

# Tournament Badge Definitions
TOURNAMENT_BADGES = {
    'tournament_1st_place': {
        'name': 'tournament_1st_place',
        'display_name': '🥇 Tournament Winner',
        'description': 'First place in tournament',
        'emoji': '🥇'
    },
    'tournament_2nd_place': {
        'name': 'tournament_2nd_place', 
        'display_name': '🥈 Tournament Runner-up',
        'description': 'Second place in tournament',
        'emoji': '🥈'
    },
    'tournament_3rd_place': {
        'name': 'tournament_3rd_place',
        'display_name': '🥉 Tournament Third Place', 
        'description': 'Third place in tournament',
        'emoji': '🥉'
    },
    'tournament_last_place': {
        'name': 'tournament_last_place',
        'display_name': '🎯 Tournament Participant',
        'description': 'Last place in tournament (participation badge)',
        'emoji': '🎯'
    }
}

def assign_tournament_badges(tournament, final_standings):
    """
    Assign badges to teams based on final tournament standings.
    
    Args:
        tournament: Tournament instance
        final_standings: List of teams ordered by final ranking (1st, 2nd, 3rd, etc.)
        
    Returns:
        dict: Summary of badges assigned
    """
    logger.info(f"Assigning tournament badges for {tournament.name}")
    
    if not final_standings:
        logger.warning(f"No final standings provided for tournament {tournament.name}")
        return {}
        
    badges_assigned = {}
    total_teams = len(final_standings)
    
    # Assign badges based on position
    for position, team in enumerate(final_standings, 1):
        team_badges = []
        
        # Get or create team profile
        team_profile, created = TeamProfile.objects.get_or_create(team=team)
        if created:
            logger.info(f"Created new TeamProfile for {team.name}")
            
        # Assign position-based badges
        if position == 1 and total_teams >= 1:
            # First place
            badge_data = {
                'tournament_id': tournament.id,
                'tournament_name': tournament.name,
                'position': 1,
                'total_teams': total_teams,
                'tournament_format': tournament.format
            }
            if team_profile.add_badge('tournament_1st_place', badge_data):
                team_badges.append('🥇 1st Place')
                logger.info(f"Awarded 1st place badge to {team.name}")
                
        elif position == 2 and total_teams >= 2:
            # Second place
            badge_data = {
                'tournament_id': tournament.id,
                'tournament_name': tournament.name,
                'position': 2,
                'total_teams': total_teams,
                'tournament_format': tournament.format
            }
            if team_profile.add_badge('tournament_2nd_place', badge_data):
                team_badges.append('🥈 2nd Place')
                logger.info(f"Awarded 2nd place badge to {team.name}")
                
        elif position == 3 and total_teams >= 3:
            # Third place
            badge_data = {
                'tournament_id': tournament.id,
                'tournament_name': tournament.name,
                'position': 3,
                'total_teams': total_teams,
                'tournament_format': tournament.format
            }
            if team_profile.add_badge('tournament_3rd_place', badge_data):
                team_badges.append('🥉 3rd Place')
                logger.info(f"Awarded 3rd place badge to {team.name}")
                
        # Special case: Last place badge
        if position == total_teams and total_teams >= 2:
            # Last place (but not if there are only 2 teams, as 2nd place is not "last")
            if total_teams >= 3:
                badge_data = {
                    'tournament_id': tournament.id,
                    'tournament_name': tournament.name,
                    'position': total_teams,
                    'total_teams': total_teams,
                    'tournament_format': tournament.format
                }
                if team_profile.add_badge('tournament_last_place', badge_data):
                    team_badges.append('🎯 Participation')
                    logger.info(f"Awarded last place badge to {team.name}")
        
        # Store badges assigned to this team
        if team_badges:
            badges_assigned[team.name] = team_badges
            
    logger.info(f"Tournament badge assignment completed for {tournament.name}: {badges_assigned}")
    return badges_assigned

def get_tournament_final_standings(tournament):
    """
    Calculate final standings for a completed tournament.
    
    Args:
        tournament: Tournament instance
        
    Returns:
        list: Teams ordered by final ranking (1st, 2nd, 3rd, etc.)
    """
    logger.info(f"Calculating final standings for tournament {tournament.name}")
    
    # Get all tournament teams
    tournament_teams = tournament.tournamentteam_set.all().select_related('team')
    
    if not tournament_teams.exists():
        logger.warning(f"No teams found for tournament {tournament.name}")
        return []
    
    # Different ranking logic based on tournament format
    if tournament.format == "knockout":
        return _get_knockout_standings(tournament, tournament_teams)
    elif tournament.format == "round_robin":
        return _get_round_robin_standings(tournament, tournament_teams)
    elif tournament.format == "swiss":
        return _get_swiss_standings(tournament, tournament_teams)
    elif tournament.format == "multi_stage":
        return _get_multi_stage_standings(tournament, tournament_teams)
    else:
        logger.warning(f"Unknown tournament format: {tournament.format}")
        return [tt.team for tt in tournament_teams]

def _get_knockout_standings(tournament, tournament_teams):
    """Calculate standings for knockout tournaments."""
    from matches.models import Match
    
    # In knockout, we need to determine standings based on elimination rounds
    # Winner is the team that won the final match
    # Runner-up is the team that lost the final match
    # Others are ranked by how far they progressed
    
    teams_by_elimination_round = {}
    
    for tt in tournament_teams:
        team = tt.team
        
        # Find the last match this team played
        last_match = Match.objects.filter(
            tournament=tournament,
            status="completed"
        ).filter(
            models.Q(team1=team) | models.Q(team2=team)
        ).order_by('-round__number').first()
        
        if last_match:
            if last_match.winner == team:
                # This team won their last match - they might be the winner
                # Check if there are any later matches
                later_matches = Match.objects.filter(
                    tournament=tournament,
                    round__number__gt=last_match.round.number
                ).exists()
                
                if not later_matches:
                    # This is the tournament winner
                    elimination_round = float('inf')  # Winner never eliminated
                else:
                    # They advanced but were eliminated later
                    elimination_round = last_match.round.number + 1
            else:
                # This team lost their last match
                elimination_round = last_match.round.number
        else:
            # No matches found - shouldn't happen in a proper tournament
            elimination_round = 0
            
        if elimination_round not in teams_by_elimination_round:
            teams_by_elimination_round[elimination_round] = []
        teams_by_elimination_round[elimination_round].append(team)
    
    # Sort by elimination round (later elimination = better ranking)
    standings = []
    for round_num in sorted(teams_by_elimination_round.keys(), reverse=True):
        standings.extend(teams_by_elimination_round[round_num])
    
    return standings

def _get_round_robin_standings(tournament, tournament_teams):
    """Calculate standings for round robin tournaments."""
    # Sort by wins, then by points differential
    team_stats = []
    
    for tt in tournament_teams:
        team = tt.team
        wins = 0
        points_for = 0
        points_against = 0
        
        from matches.models import Match
        matches = Match.objects.filter(
            tournament=tournament,
            status="completed"
        ).filter(
            models.Q(team1=team) | models.Q(team2=team)
        )
        
        for match in matches:
            if match.team1 == team:
                points_for += match.team1_score or 0
                points_against += match.team2_score or 0
                if match.winner == team:
                    wins += 1
            else:
                points_for += match.team2_score or 0
                points_against += match.team1_score or 0
                if match.winner == team:
                    wins += 1
        
        team_stats.append({
            'team': team,
            'wins': wins,
            'points_diff': points_for - points_against,
            'points_for': points_for
        })
    
    # Sort by wins (desc), then points differential (desc), then points for (desc)
    team_stats.sort(key=lambda x: (x['wins'], x['points_diff'], x['points_for']), reverse=True)
    
    return [stat['team'] for stat in team_stats]

def _get_swiss_standings(tournament, tournament_teams):
    """Calculate standings for Swiss system tournaments."""
    # Sort by Swiss points, then by Buchholz score
    team_stats = []
    
    for tt in tournament_teams:
        team_stats.append({
            'team': tt.team,
            'swiss_points': tt.swiss_points,
            'buchholz_score': tt.buchholz_score
        })
    
    # Sort by Swiss points (desc), then Buchholz score (desc)
    team_stats.sort(key=lambda x: (x['swiss_points'], x['buchholz_score']), reverse=True)
    
    return [stat['team'] for stat in team_stats]

def _get_multi_stage_standings(tournament, tournament_teams):
    """Calculate standings for multi-stage tournaments."""
    # For multi-stage, use the final stage results if available,
    # otherwise fall back to overall performance
    
    # Get the highest stage number
    max_stage = max(tt.current_stage_number for tt in tournament_teams)
    
    # Teams in the highest stage are ranked first
    teams_by_stage = {}
    for tt in tournament_teams:
        stage = tt.current_stage_number
        if stage not in teams_by_stage:
            teams_by_stage[stage] = []
        teams_by_stage[stage].append(tt)
    
    standings = []
    
    # Process stages from highest to lowest
    for stage_num in sorted(teams_by_stage.keys(), reverse=True):
        stage_teams = teams_by_stage[stage_num]
        
        if stage_num == max_stage and len(stage_teams) <= 4:
            # Final stage - use knockout-style ranking
            stage_standings = _get_knockout_standings(tournament, stage_teams)
        else:
            # Earlier stages - use Swiss or round-robin ranking
            stage_standings = _get_swiss_standings(tournament, stage_teams)
        
        standings.extend(stage_standings)
    
    return standings

# Import models at the end to avoid circular imports
from django.db import models

