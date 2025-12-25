"""
Utility to synchronize team player assignments with MeleePartnership records.

This ensures that Player.team assignments match the partnerships recorded
in the MeleePartnership model, preventing mismatches that can occur during
shuffling or team generation.
"""

import logging
from collections import defaultdict
from django.db import transaction

logger = logging.getLogger('tournaments')


def sync_team_assignments_with_partnerships(tournament, round_number):
    """
    Synchronize team player assignments with MeleePartnership records for a specific round.
    
    This function ensures that each team has exactly the players that are recorded
    in the MeleePartnership model for the given round. This is the source of truth
    for which players should be on which teams.
    
    Args:
        tournament: Tournament object
        round_number: The round number to sync
        
    Returns:
        dict: {
            'success': bool,
            'players_moved': int,
            'teams_fixed': int,
            'message': str
        }
    """
    from tournaments.partnership_models import MeleePartnership
    from teams.models import Team
    from pfc_core.session_refresh import refresh_player_team_session
    
    if not tournament.is_melee:
        return {
            'success': False,
            'players_moved': 0,
            'teams_fixed': 0,
            'message': 'Tournament is not in Mêlée mode'
        }
    
    try:
        with transaction.atomic():
            # Get all partnerships for this round
            partnerships = MeleePartnership.objects.filter(
                tournament=tournament,
                round_number=round_number
            )
            
            if not partnerships.exists():
                return {
                    'success': False,
                    'players_moved': 0,
                    'teams_fixed': 0,
                    'message': f'No partnerships found for round {round_number}'
                }
            
            # Group partnerships by team
            team_players_map = defaultdict(set)
            
            for partnership in partnerships:
                team_name = partnership.team_name
                team_players_map[team_name].add(partnership.player1)
                team_players_map[team_name].add(partnership.player2)
            
            # Now fix each team's player assignments
            players_moved = 0
            teams_fixed = 0
            
            for team_name, correct_players in team_players_map.items():
                team = Team.objects.filter(name=team_name).first()
                
                if not team:
                    logger.warning(f"Team '{team_name}' not found in database")
                    continue
                
                current_players = set(team.players.all())
                
                # Check if team needs fixing
                if current_players != correct_players:
                    teams_fixed += 1
                    logger.info(f"Fixing {team_name}:")
                    logger.info(f"  Should have: {[p.name for p in correct_players]}")
                    logger.info(f"  Currently has: {[p.name for p in current_players]}")
                    
                    # Move players to correct team
                    for player in correct_players:
                        if player not in current_players:
                            old_team = player.team
                            player.team = team
                            player.save()
                            players_moved += 1
                            
                            logger.info(f"  ✓ Moved {player.name} from {old_team.name if old_team else 'No Team'} to {team_name}")
                            
                            # Refresh player's session
                            refresh_player_team_session(player)
            
            message = f"Synced {players_moved} players across {teams_fixed} teams for round {round_number}"
            logger.info(f"✅ {message}")
            
            return {
                'success': True,
                'players_moved': players_moved,
                'teams_fixed': teams_fixed,
                'message': message
            }
            
    except Exception as e:
        logger.error(f"Error syncing team assignments: {str(e)}")
        return {
            'success': False,
            'players_moved': 0,
            'teams_fixed': 0,
            'message': f'Error: {str(e)}'
        }


def sync_all_rounds(tournament):
    """
    Synchronize team assignments for all rounds in a tournament.
    
    Args:
        tournament: Tournament object
        
    Returns:
        dict: Summary of sync results
    """
    from tournaments.partnership_models import MeleePartnership
    
    # Get all unique round numbers with partnerships
    round_numbers = MeleePartnership.objects.filter(
        tournament=tournament
    ).values_list('round_number', flat=True).distinct().order_by('round_number')
    
    total_players_moved = 0
    total_teams_fixed = 0
    rounds_synced = 0
    
    for round_number in round_numbers:
        result = sync_team_assignments_with_partnerships(tournament, round_number)
        if result['success']:
            total_players_moved += result['players_moved']
            total_teams_fixed += result['teams_fixed']
            rounds_synced += 1
    
    return {
        'success': True,
        'rounds_synced': rounds_synced,
        'players_moved': total_players_moved,
        'teams_fixed': total_teams_fixed,
        'message': f"Synced {rounds_synced} rounds, moved {total_players_moved} players, fixed {total_teams_fixed} teams"
    }
