"""
Swiss Tournament Pairing Algorithms

This module contains both regular Swiss and Smart Swiss pairing algorithms.
Smart Swiss includes advanced constraint handling for parent-child team relationships.
"""

import logging
import random
from typing import List, Tuple, Optional, Set
from django.db import transaction
from .models import Tournament, TournamentTeam, Round, Stage
from matches.models import Match
from teams.models import Team

logger = logging.getLogger("tournaments")


def has_parent_child_relationship(team1: Team, team2: Team) -> bool:
    """
    Check if two teams have a parent-child relationship.
    
    Args:
        team1: First team
        team2: Second team
        
    Returns:
        True if teams have parent-child relationship, False otherwise
    """
    try:
        # Check if team1 is parent of team2
        if hasattr(team1, 'children') and team2 in team1.children.all():
            return True
        # Check if team2 is parent of team1
        if hasattr(team2, 'children') and team1 in team2.children.all():
            return True
        # Check if team1 has team2 as parent
        if hasattr(team1, 'parent_team') and team1.parent_team == team2:
            return True
        # Check if team2 has team1 as parent
        if hasattr(team2, 'parent_team') and team2.parent_team == team1:
            return True
    except Exception as e:
        logger.debug(f"Error checking parent-child relationship: {e}")
    
    return False


def can_teams_play(team1_tt: TournamentTeam, team2_tt: TournamentTeam, allow_rematches: bool = False, avoid_parent_child: bool = False) -> bool:
    """
    Check if two teams can play against each other based on constraints.
    
    Args:
        team1_tt: First tournament team
        team2_tt: Second tournament team
        allow_rematches: Whether to allow teams that have already played
        avoid_parent_child: Whether to avoid parent-child team pairings
        
    Returns:
        True if teams can play, False otherwise
    """
    # Check if they have played before
    if not allow_rematches and team2_tt.team in team1_tt.opponents_played.all():
        return False
    
    # Check parent-child relationship if avoiding them
    if avoid_parent_child and has_parent_child_relationship(team1_tt.team, team2_tt.team):
        return False
    
    return True


def find_best_pairing(unpaired_teams: List[TournamentTeam], avoid_parent_child: bool = False) -> Optional[List[Tuple[int, int]]]:
    """
    Find the best possible pairing for all unpaired teams using backtracking.
    
    Args:
        unpaired_teams: List of unpaired tournament teams
        avoid_parent_child: Whether to avoid parent-child pairings
        
    Returns:
        List of tuples (i, j) representing team indices to pair, or None if no valid pairing exists
    """
    n = len(unpaired_teams)
    if n < 2:
        return []
    
    if n % 2 != 0:
        # Handle odd number of teams - this should be handled by bye logic before calling this function
        logger.warning(f"Odd number of teams ({n}) passed to find_best_pairing")
        n -= 1  # Exclude the last team
    
    def backtrack(paired_indices: Set[int], current_pairings: List[Tuple[int, int]]) -> Optional[List[Tuple[int, int]]]:
        """Recursive backtracking function to find valid pairings."""
        if len(paired_indices) == n:
            return current_pairings.copy()
        
        # Find the first unpaired team
        first_unpaired = None
        for i in range(n):
            if i not in paired_indices:
                first_unpaired = i
                break
        
        if first_unpaired is None:
            return current_pairings.copy()
        
        # Try pairing with all other unpaired teams
        for j in range(first_unpaired + 1, n):
            if j in paired_indices:
                continue
            
            team1_tt = unpaired_teams[first_unpaired]
            team2_tt = unpaired_teams[j]
            
            if can_teams_play(team1_tt, team2_tt, allow_rematches=False, avoid_parent_child=avoid_parent_child):
                # Try this pairing
                new_paired = paired_indices.copy()
                new_paired.add(first_unpaired)
                new_paired.add(j)
                new_pairings = current_pairings + [(first_unpaired, j)]
                
                result = backtrack(new_paired, new_pairings)
                if result is not None:
                    return result
        
        return None
    
    return backtrack(set(), [])


def generate_standard_swiss_round(tournament: Tournament, stage: Optional[Stage] = None) -> int:
    """
    Generate next round using Standard Swiss system pairing.
    
    Standard Swiss Features:
    - Teams ranked by Swiss points (wins), then tiebreakers
    - Pair teams with similar scores when possible
    - Avoid rematches (teams that have already played)
    - No parent-child constraints (pure Swiss system)
    - Proper bye handling for odd number of teams
    
    Args:
        tournament: Tournament object
        stage: Optional stage for multi-stage tournaments
        
    Returns:
        Number of matches created
    """
    logger.info(f"Generating Standard Swiss round for tournament {tournament.id}")
    
    try:
        with transaction.atomic():
            current_round = tournament.current_round_number or 0
            next_round_num = current_round + 1
            logger.info(f"Current round: {current_round}, generating for round: {next_round_num}")

            # Update Swiss Points
            active_teams_tt = list(TournamentTeam.objects.filter(tournament=tournament, is_active=True).select_related("team"))
            for tt in active_teams_tt:
                tt.update_swiss_stats()
            
            # Get teams for pairing, sorted by Swiss points (descending), then tiebreakers
            if stage:
                teams_to_pair = list(TournamentTeam.objects.filter(
                    tournament=tournament, 
                    is_active=True,
                    current_stage_number=stage.stage_number
                ).order_by("-swiss_points", "-buchholz_score", "id"))
            else:
                teams_to_pair = list(TournamentTeam.objects.filter(
                    tournament=tournament, 
                    is_active=True
                ).order_by("-swiss_points", "-buchholz_score", "id"))
            
            num_teams = len(teams_to_pair)
            logger.info(f"Teams to pair ({num_teams}): {[(t.team.name, t.swiss_points) for t in teams_to_pair]}")

            if num_teams < 2:
                logger.warning(f"Not enough active teams ({num_teams}) to generate next round")
                tournament.automation_status = "completed"
                tournament.save()
                return 0

            # Handle Bye for odd number of teams
            bye_team_tt = None
            if num_teams % 2 != 0:
                # Give bye to lowest-ranked team that hasn't received one yet
                for i in range(num_teams - 1, -1, -1):
                    candidate = teams_to_pair[i]
                    if candidate.received_bye_in_round is None:
                        bye_team_tt = teams_to_pair.pop(i)
                        break
                
                if bye_team_tt:
                    logger.info(f"Assigning bye to {bye_team_tt.team.name} in Standard Swiss Round {next_round_num}")
                    bye_team_tt.received_bye_in_round = next_round_num
                    bye_team_tt.swiss_points += 3  # Standard bye points
                    bye_team_tt.save()
                else:
                    # All teams have received byes, give to lowest ranked
                    bye_team_tt = teams_to_pair.pop()
                    logger.info(f"All teams had byes, giving another bye to {bye_team_tt.team.name}")
                    bye_team_tt.swiss_points += 3
                    bye_team_tt.save()

            # Standard Swiss Pairing Algorithm
            matches_created = []
            num_teams = len(teams_to_pair)
            
            if num_teams >= 2:
                # Create or get the Round object
                round_obj, created = Round.objects.get_or_create(
                    tournament=tournament,
                    stage=stage,
                    number=next_round_num,
                    defaults={'is_complete': False}
                )
                
                # Group teams by Swiss points for proper pairing
                score_groups = {}
                for team_tt in teams_to_pair:
                    score = team_tt.swiss_points
                    if score not in score_groups:
                        score_groups[score] = []
                    score_groups[score].append(team_tt)
                
                logger.debug(f"Score groups: {[(score, len(teams)) for score, teams in score_groups.items()]}")
                
                # Pair teams using standard Swiss method
                unpaired_teams = teams_to_pair.copy()
                
                while len(unpaired_teams) >= 2:
                    team1_tt = unpaired_teams[0]
                    paired = False
                    
                    # Try to pair with teams of same score first, then nearby scores
                    for team2_tt in unpaired_teams[1:]:
                        # Check if they haven't played before
                        if team2_tt.team not in team1_tt.opponents_played.all():
                            # Valid pairing found
                            logger.info(f"Standard Swiss pairing: {team1_tt.team.name} ({team1_tt.swiss_points} pts) vs {team2_tt.team.name} ({team2_tt.swiss_points} pts)")
                            
                            match = Match.objects.create(
                                tournament=tournament,
                                round=round_obj,
                                stage=stage,
                                team1=team1_tt.team,
                                team2=team2_tt.team,
                                status="pending"
                            )
                            matches_created.append(match)
                            
                            # Update opponents played
                            team1_tt.opponents_played.add(team2_tt.team)
                            team2_tt.opponents_played.add(team1_tt.team)
                            
                            # Remove both teams from unpaired list
                            unpaired_teams.remove(team1_tt)
                            unpaired_teams.remove(team2_tt)
                            paired = True
                            break
                    
                    if not paired:
                        # No valid opponent found without rematch, allow rematch as fallback
                        if len(unpaired_teams) >= 2:
                            team2_tt = unpaired_teams[1]
                            logger.warning(f"Standard Swiss fallback (rematch): {team1_tt.team.name} vs {team2_tt.team.name}")
                            
                            match = Match.objects.create(
                                tournament=tournament,
                                round=round_obj,
                                stage=stage,
                                team1=team1_tt.team,
                                team2=team2_tt.team,
                                status="pending"
                            )
                            matches_created.append(match)
                            
                            # Update opponents played
                            team1_tt.opponents_played.add(team2_tt.team)
                            team2_tt.opponents_played.add(team1_tt.team)
                            
                            # Remove both teams from unpaired list
                            unpaired_teams.remove(team1_tt)
                            unpaired_teams.remove(team2_tt)
                        else:
                            # Only one team left, shouldn't happen with proper bye handling
                            logger.error(f"Single unpaired team remaining: {team1_tt.team.name}")
                            break

            # Finalize Round
            if len(matches_created) > 0 or bye_team_tt:
                tournament.current_round_number = next_round_num
                tournament.automation_status = "idle"
                tournament.save()
                logger.info(f"Successfully generated {len(matches_created)} matches for Standard Swiss round {next_round_num}")
            
            return len(matches_created)

    except Exception as e:
        logger.exception(f"Error generating Standard Swiss round: {e}")
        tournament.automation_status = "error"
        tournament.save()
        raise


def generate_smart_swiss_round(tournament: Tournament, stage: Optional[Stage] = None) -> int:
    """
    Generate next round using Smart Swiss system with advanced constraint handling.
    
    Features:
    - Avoids parent-child team pairings when possible
    - Uses backtracking to find optimal pairings
    - Falls back to allowing parent-child matches if necessary
    - Maximizes number of matches generated
    
    Args:
        tournament: Tournament object
        stage: Optional stage for multi-stage tournaments
        
    Returns:
        Number of matches created
    """
    logger.info(f"Generating Smart Swiss round for tournament {tournament.id}")
    
    try:
        with transaction.atomic():
            current_round = tournament.current_round_number or 0
            next_round_num = current_round + 1
            logger.info(f"Current round: {current_round}, generating for round: {next_round_num}")

            # Update Swiss Points
            active_teams_tt = list(TournamentTeam.objects.filter(tournament=tournament, is_active=True).select_related("team"))
            for tt in active_teams_tt:
                tt.update_swiss_stats()
            
            # Get teams for pairing
            if stage:
                teams_to_pair = list(TournamentTeam.objects.filter(
                    tournament=tournament, 
                    is_active=True,
                    current_stage_number=stage.stage_number
                ).order_by("-swiss_points", "-buchholz_score", "id"))
            else:
                teams_to_pair = list(TournamentTeam.objects.filter(
                    tournament=tournament, 
                    is_active=True
                ).order_by("-swiss_points", "-buchholz_score", "id"))
            
            num_teams = len(teams_to_pair)
            logger.debug(f"Teams to pair ({num_teams}): {[t.team.name for t in teams_to_pair]}")

            if num_teams < 2:
                logger.warning(f"Not enough active teams ({num_teams}) to generate next round")
                tournament.automation_status = "completed"
                tournament.save()
                return 0

            # Handle Bye
            bye_team_tt = None
            if num_teams % 2 != 0:
                for i in range(num_teams - 1, -1, -1):
                    candidate = teams_to_pair[i]
                    if candidate.received_bye_in_round is None:
                        bye_team_tt = teams_to_pair.pop(i)
                        break
                
                if bye_team_tt:
                    logger.info(f"Assigning Bye to {bye_team_tt.team.name} in Smart Swiss Round {next_round_num}")
                    bye_team_tt.received_bye_in_round = next_round_num
                    bye_team_tt.swiss_points += 3
                    bye_team_tt.save()

            # Smart Pairing Algorithm
            matches_created = []
            num_teams = len(teams_to_pair)
            
            if num_teams >= 2:
                # Create or get the Round object
                round_obj, created = Round.objects.get_or_create(
                    tournament=tournament,
                    stage=stage,
                    number=next_round_num,
                    defaults={'is_complete': False}
                )
                
                # Strategy 1: Try to find optimal pairing avoiding parent-child relationships
                logger.info("Strategy 1: Attempting optimal pairing avoiding parent-child relationships")
                optimal_pairings = find_best_pairing(teams_to_pair, avoid_parent_child=True)
                
                if optimal_pairings and len(optimal_pairings) == num_teams // 2:
                    logger.info(f"Found optimal pairing with {len(optimal_pairings)} matches avoiding parent-child relationships")
                    
                    for i, j in optimal_pairings:
                        team1_tt = teams_to_pair[i]
                        team2_tt = teams_to_pair[j]
                        
                        logger.info(f"Optimal pairing: {team1_tt.team.name} vs {team2_tt.team.name}")
                        match = Match.objects.create(
                            tournament=tournament,
                            round=round_obj,
                            stage=stage,
                            team1=team1_tt.team,
                            team2=team2_tt.team,
                            status="pending"
                        )
                        matches_created.append(match)
                        
                        # Update opponents played
                        team1_tt.opponents_played.add(team2_tt.team)
                        team2_tt.opponents_played.add(team1_tt.team)
                
                else:
                    # Strategy 2: Fallback - allow parent-child relationships if necessary
                    logger.warning("Strategy 1 failed. Strategy 2: Allowing parent-child relationships as fallback")
                    fallback_pairings = find_best_pairing(teams_to_pair, avoid_parent_child=False)
                    
                    if fallback_pairings and len(fallback_pairings) > 0:
                        logger.info(f"Found fallback pairing with {len(fallback_pairings)} matches (may include parent-child)")
                        
                        for i, j in fallback_pairings:
                            team1_tt = teams_to_pair[i]
                            team2_tt = teams_to_pair[j]
                            
                            # Check if this is a parent-child pairing
                            if has_parent_child_relationship(team1_tt.team, team2_tt.team):
                                logger.warning(f"PARENT-CHILD PAIRING (fallback): {team1_tt.team.name} vs {team2_tt.team.name}")
                            else:
                                logger.info(f"Fallback pairing: {team1_tt.team.name} vs {team2_tt.team.name}")
                            
                            match = Match.objects.create(
                                tournament=tournament,
                                round=round_obj,
                                stage=stage,
                                team1=team1_tt.team,
                                team2=team2_tt.team,
                                status="pending"
                            )
                            matches_created.append(match)
                            
                            # Update opponents played
                            team1_tt.opponents_played.add(team2_tt.team)
                            team2_tt.opponents_played.add(team1_tt.team)
                    
                    else:
                        # Strategy 3: Emergency fallback - simple sequential pairing
                        logger.error("Strategy 2 failed. Strategy 3: Emergency sequential pairing")
                        
                        for i in range(0, num_teams - 1, 2):
                            team1_tt = teams_to_pair[i]
                            team2_tt = teams_to_pair[i + 1]
                            
                            logger.warning(f"Emergency pairing: {team1_tt.team.name} vs {team2_tt.team.name}")
                            match = Match.objects.create(
                                tournament=tournament,
                                round=round_obj,
                                stage=stage,
                                team1=team1_tt.team,
                                team2=team2_tt.team,
                                status="pending"
                            )
                            matches_created.append(match)
                            
                            # Update opponents played
                            team1_tt.opponents_played.add(team2_tt.team)
                            team2_tt.opponents_played.add(team1_tt.team)

            # Finalize Round
            if len(matches_created) > 0 or bye_team_tt:
                tournament.current_round_number = next_round_num
                tournament.automation_status = "idle"
                tournament.save()
                logger.info(f"Successfully generated {len(matches_created)} matches for Smart Swiss round {next_round_num}")
            else:
                logger.error(f"No matches were created for Smart Swiss round {next_round_num}")
                tournament.automation_status = "error"
                tournament.save()
            
            return len(matches_created)

    except Exception as e:
        logger.exception(f"Error generating Smart Swiss round: {e}")
        tournament.automation_status = "error"
        tournament.save()
        raise


def generate_next_swiss_round(tournament: Tournament, stage: Optional[Stage] = None) -> int:
    """
    Main entry point for Swiss round generation.
    Dispatches to appropriate algorithm based on tournament format.
    
    Args:
        tournament: Tournament object
        stage: Optional stage for multi-stage tournaments
        
    Returns:
        Number of matches created
    """
    if tournament.format == "smart_swiss":
        return generate_smart_swiss_round(tournament, stage)
    elif tournament.format == "swiss":
        return generate_regular_swiss_round(tournament, stage)
    else:
        raise ValueError(f"Invalid Swiss format: {tournament.format}")
