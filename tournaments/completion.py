# tournaments/completion.py
"""
Tournament Completion Detection and Badge Assignment

This module handles automatic detection of tournament completion
and assigns badges to teams without interfering with match creation logic.
"""

import logging
from django.db import transaction
from django.utils import timezone
from .badges import assign_tournament_badges, get_tournament_final_standings

logger = logging.getLogger('tournaments')

def check_and_complete_tournament(tournament):
    """
    Check if a tournament is completed and assign badges if so.
    
    This function is called when a tournament's automation_status becomes "completed"
    or when all matches are finished but the tournament hasn't been marked as complete.
    
    Args:
        tournament: Tournament instance
        
    Returns:
        bool: True if tournament was completed and badges assigned, False otherwise
    """
    logger.info(f"Checking completion status for tournament {tournament.name}")
    
    # Check if tournament is already marked as completed
    if tournament.automation_status == "completed":
        logger.info(f"Tournament {tournament.name} already marked as completed")
        return _assign_badges_if_needed(tournament)
    
    # Check if all matches are completed and no more can be generated
    if _is_tournament_truly_finished(tournament):
        logger.info(f"Tournament {tournament.name} is finished - marking as completed")
        
        with transaction.atomic():
            # Mark tournament as completed
            tournament.automation_status = "completed"
            tournament.save()
            
            # Assign badges
            return _assign_badges_if_needed(tournament)
    
    return False

def _is_tournament_truly_finished(tournament):
    """
    Determine if a tournament is truly finished (no more matches possible).
    
    Args:
        tournament: Tournament instance
        
    Returns:
        bool: True if tournament is finished, False otherwise
    """
    from matches.models import Match
    
    # Get all matches for this tournament
    all_matches = Match.objects.filter(tournament=tournament)
    
    if not all_matches.exists():
        logger.warning(f"No matches found for tournament {tournament.name}")
        return False
    
    # Check if all matches are completed
    incomplete_matches = all_matches.exclude(status="completed")
    if incomplete_matches.exists():
        logger.debug(f"Tournament {tournament.name} has {incomplete_matches.count()} incomplete matches")
        return False
    
    # All matches are completed - now check if more matches could be generated
    return _no_more_matches_possible(tournament)

def _no_more_matches_possible(tournament):
    """
    Check if no more matches can be generated for this tournament.
    
    Args:
        tournament: Tournament instance
        
    Returns:
        bool: True if no more matches can be generated, False otherwise
    """
    if tournament.format == "knockout":
        return _knockout_is_finished(tournament)
    elif tournament.format == "round_robin":
        return _round_robin_is_finished(tournament)
    elif tournament.format == "swiss":
        return _swiss_is_finished(tournament)
    elif tournament.format == "multi_stage":
        return _multi_stage_is_finished(tournament)
    else:
        logger.warning(f"Unknown tournament format: {tournament.format}")
        return True  # Assume finished if format unknown

def _knockout_is_finished(tournament):
    """Check if knockout tournament is finished."""
    from matches.models import Match
    
    # In knockout, tournament is finished when there's only one team left
    # or when the final match has been played
    
    # Get the latest round
    latest_round = tournament.rounds.order_by('-number').first()
    if not latest_round:
        return False
    
    # Get matches in the latest round
    latest_matches = Match.objects.filter(
        tournament=tournament,
        round=latest_round,
        status="completed"
    )
    
    # If there's only one match in the latest round, it's the final
    if latest_matches.count() == 1:
        logger.info(f"Knockout tournament {tournament.name} finished - final match completed")
        return True
    
    # If there are no completed matches in the latest round, check previous round
    if latest_matches.count() == 0:
        return False
    
    # If there are multiple matches, check if only one team advanced
    winners = [match.winner for match in latest_matches if match.winner]
    if len(winners) <= 1:
        logger.info(f"Knockout tournament {tournament.name} finished - only {len(winners)} winner(s)")
        return True
    
    return False

def _round_robin_is_finished(tournament):
    """Check if round robin tournament is finished."""
    from matches.models import Match
    
    # Round robin is finished when all possible matches have been played
    teams = list(tournament.teams.all())
    total_teams = len(teams)
    
    if total_teams < 2:
        return True
    
    # Calculate expected number of matches
    expected_matches = (total_teams * (total_teams - 1)) // 2
    
    # Count actual completed matches
    completed_matches = Match.objects.filter(
        tournament=tournament,
        status="completed"
    ).count()
    
    is_finished = completed_matches >= expected_matches
    if is_finished:
        logger.info(f"Round robin tournament {tournament.name} finished - {completed_matches}/{expected_matches} matches completed")
    
    return is_finished

def _swiss_is_finished(tournament):
    """Check if Swiss tournament is finished."""
    # Swiss tournaments are finished when the configured number of rounds is reached
    # or when the automation system determines no more rounds are needed
    
    # Check if we've reached the maximum number of rounds
    current_round = tournament.current_round_number or 0
    
    # Swiss tournaments typically run for log2(n) rounds where n is number of teams
    teams_count = tournament.teams.count()
    if teams_count < 2:
        return True
    
    import math
    max_rounds = math.ceil(math.log2(teams_count))
    
    # Also check if the tournament has been explicitly marked as needing no more rounds
    if current_round >= max_rounds:
        logger.info(f"Swiss tournament {tournament.name} finished - reached maximum rounds ({current_round}/{max_rounds})")
        return True
    
    return False

def _multi_stage_is_finished(tournament):
    """Check if multi-stage tournament is finished."""
    # Multi-stage is finished when the final stage is completed
    
    # Get the highest stage number
    max_stage = tournament.stages.aggregate(
        max_stage=models.Max('stage_number')
    )['max_stage']
    
    if not max_stage:
        return False
    
    # Check if the final stage is completed
    final_stage = tournament.stages.filter(stage_number=max_stage).first()
    if not final_stage:
        return False
    
    # Check if final stage has any incomplete matches
    from matches.models import Match
    incomplete_matches = Match.objects.filter(
        tournament=tournament,
        round__stage=final_stage
    ).exclude(status="completed")
    
    if incomplete_matches.exists():
        return False
    
    # Check if final stage can generate more matches
    final_stage_matches = Match.objects.filter(
        tournament=tournament,
        round__stage=final_stage,
        status="completed"
    )
    
    # If final stage has only one match and it's completed, tournament is finished
    if final_stage_matches.count() == 1:
        logger.info(f"Multi-stage tournament {tournament.name} finished - final stage completed")
        return True
    
    # If final stage has multiple matches, check if only one winner remains
    winners = [match.winner for match in final_stage_matches if match.winner]
    unique_winners = list(set(winners))
    
    if len(unique_winners) <= 1:
        logger.info(f"Multi-stage tournament {tournament.name} finished - final winner determined")
        return True
    
    return False

def _assign_badges_if_needed(tournament):
    """
    Assign badges to teams if they haven't been assigned yet.
    
    Args:
        tournament: Tournament instance
        
    Returns:
        bool: True if badges were assigned, False if already assigned or error
    """
    # Check if badges have already been assigned
    if _badges_already_assigned(tournament):
        logger.info(f"Badges already assigned for tournament {tournament.name}")
        return True
    
    try:
        # Calculate final standings
        final_standings = get_tournament_final_standings(tournament)
        
        if not final_standings:
            logger.warning(f"Could not determine final standings for tournament {tournament.name}")
            return False
        
        # Assign badges
        badges_assigned = assign_tournament_badges(tournament, final_standings)
        
        # Log the results
        logger.info(f"Badge assignment completed for tournament {tournament.name}")
        for team_name, badges in badges_assigned.items():
            logger.info(f"  {team_name}: {', '.join(badges)}")
        
        # Mark that badges have been assigned
        _mark_badges_assigned(tournament)
        
        return True
        
    except Exception as e:
        logger.exception(f"Error assigning badges for tournament {tournament.name}: {e}")
        return False

def _badges_already_assigned(tournament):
    """
    Check if badges have already been assigned for this tournament.
    
    Args:
        tournament: Tournament instance
        
    Returns:
        bool: True if badges already assigned, False otherwise
    """
    from teams.models import TeamProfile
    
    # Check if any team in this tournament has a badge from this tournament
    tournament_teams = tournament.teams.all()
    
    for team in tournament_teams:
        try:
            team_profile = TeamProfile.objects.get(team=team)
            if team_profile.badges:
                for badge in team_profile.badges:
                    badge_data = badge.get('data', {})
                    if badge_data.get('tournament_id') == tournament.id:
                        return True
        except TeamProfile.DoesNotExist:
            continue
    
    return False

def _mark_badges_assigned(tournament):
    """
    Mark that badges have been assigned for this tournament.
    This could be implemented as a tournament field if needed.
    
    Args:
        tournament: Tournament instance
    """
    # For now, we rely on checking existing badges
    # Could add a tournament field like 'badges_assigned' if needed
    pass

# Import models at the end to avoid circular imports
from django.db import models

