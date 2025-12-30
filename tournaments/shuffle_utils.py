"""
Utilities for shuffling players between mêlée teams
"""

import random
import logging
from django.db import transaction
from teams.models import Player
from pfc_core.session_refresh import refresh_player_team_session

logger = logging.getLogger('tournaments')


def shuffle_melee_players(tournament, shuffle_type='manual', shuffled_by=None, round_number=None):
    """
    Shuffle players between existing mêlée teams in a tournament.
    
    This creates a more dynamic and social experience by mixing up teammates
    after each round, while keeping the same team structure.
    
    Args:
        tournament: Tournament object
        shuffle_type: 'manual' or 'automatic'
        shuffled_by: User object (for manual shuffles)
        round_number: Optional round number to use (defaults to tournament.current_round_number)
        
    Returns:
        dict: {
            'success': bool,
            'players_shuffled': int,
            'teams_affected': int,
            'message': str
        }
    """
    from tournaments.models import TournamentTeam
    from tournaments.partnership_models import MeleePartnership, MeleeShuffleHistory
    
    if not tournament.is_melee:
        return {
            'success': False,
            'players_shuffled': 0,
            'teams_affected': 0,
            'message': 'Tournament is not in Mêlée mode'
        }
    
    if not tournament.melee_teams_generated:
        return {
            'success': False,
            'players_shuffled': 0,
            'teams_affected': 0,
            'message': 'Mêlée teams have not been generated yet'
        }
    
    try:
        with transaction.atomic():
            # Get all mêlée teams for this tournament
            tournament_teams = TournamentTeam.objects.filter(
                tournament=tournament,
                team__name__startswith="Mêlée Team"
            ).select_related('team').order_by('team__name')
            
            if not tournament_teams.exists():
                return {
                    'success': False,
                    'players_shuffled': 0,
                    'teams_affected': 0,
                    'message': 'No mêlée teams found'
                }
            
            # Collect all players from all mêlée teams
            all_players = []
            teams = []
            
            for tt in tournament_teams:
                team = tt.team
                teams.append(team)
                players_in_team = list(team.players.all())
                all_players.extend(players_in_team)
            
            if not all_players:
                return {
                    'success': False,
                    'players_shuffled': 0,
                    'teams_affected': 0,
                    'message': 'No players found in mêlée teams'
                }
            
            # Use provided round_number (the completed round) or fall back to tournament.current_round_number
            completed_round = round_number if round_number is not None else (tournament.current_round_number or 1)
            next_round = completed_round + 1
            
            # Partnerships for the completed round should already be recorded when teams were generated
            # or from the previous shuffle. We don't need to record them again here.
            logger.info(f"Shuffling players after round {completed_round} completion, preparing for round {next_round}")
            
            # Shuffle players randomly
            random.shuffle(all_players)
            
            # Determine team size
            team_size = len(all_players) // len(teams)
            
            # Redistribute players to teams
            player_index = 0
            teams_affected = 0
            
            # Import MeleePlayer to update assigned_team
            from tournaments.models import MeleePlayer
            
            for team in teams:
                # Assign new players to team
                team_players = []
                for _ in range(team_size):
                    if player_index < len(all_players):
                        player = all_players[player_index]
                        
                        # Update Player.team
                        player.team = team
                        player.save()
                        
                        # Also update MeleePlayer.assigned_team so partnerships are recorded correctly
                        try:
                            melee_player = MeleePlayer.objects.get(tournament=tournament, player=player)
                            melee_player.assigned_team = team
                            melee_player.save()
                        except MeleePlayer.DoesNotExist:
                            logger.warning(f"MeleePlayer not found for {player.name} in tournament {tournament.name}")
                        
                        team_players.append(player.name)
                        
                        # Refresh player's session so they don't need to logout/login
                        refresh_player_team_session(player)
                        
                        player_index += 1
                
                teams_affected += 1
                logger.info(f"Shuffled players into {team.name}: {team_players}")
            
            # Handle any remaining players (edge case)
            while player_index < len(all_players):
                # Distribute remaining players to teams
                for team in teams:
                    if player_index < len(all_players):
                        player = all_players[player_index]
                        player.team = team
                        player.save()
                        
                        # Also update MeleePlayer.assigned_team
                        try:
                            melee_player = MeleePlayer.objects.get(tournament=tournament, player=player)
                            melee_player.assigned_team = team
                            melee_player.save()
                        except MeleePlayer.DoesNotExist:
                            pass
                        
                        refresh_player_team_session(player)
                        player_index += 1
            
            # Record NEW partnerships for the NEXT round (after shuffle)
            # This is the source of truth for who is on which team for the next round
            partnerships_created = MeleePartnership.record_partnerships_for_round(tournament, next_round)
            logger.info(f"Recorded {partnerships_created} partnerships for round {next_round}")
            
            # Record shuffle history (record it as the completed round since that's when shuffle happened)
            shuffle_record = MeleeShuffleHistory.objects.create(
                tournament=tournament,
                round_number=completed_round,
                shuffle_type=shuffle_type,
                shuffled_by=shuffled_by,
                players_shuffled=len(all_players),
                notes=f"Shuffled {len(all_players)} players across {teams_affected} teams after round {completed_round}, ready for round {next_round}"
            )
            
            logger.info(
                f"Successfully shuffled {len(all_players)} players across {teams_affected} teams "
                f"in tournament '{tournament.name}' (after Round {completed_round}, {shuffle_type})"
            )
            
            return {
                'success': True,
                'players_shuffled': len(all_players),
                'teams_affected': teams_affected,
                'message': f'Successfully shuffled {len(all_players)} players across {teams_affected} teams',
                'shuffle_record_id': shuffle_record.id
            }
            
    except Exception as e:
        logger.error(f"Error shuffling mêlée players for tournament {tournament.id}: {e}")
        return {
            'success': False,
            'players_shuffled': 0,
            'teams_affected': 0,
            'message': f'Error: {str(e)}'
        }


def check_if_specific_round_complete(tournament, round_obj):
    """
    Check if all matches in a specific round are complete.
    
    Args:
        tournament: Tournament object
        round_obj: Round object to check
        
    Returns:
        bool: True if all matches in the specified round are complete
    """
    from matches.models import Match
    
    try:
        # Get all matches in this specific round
        matches = Match.objects.filter(round=round_obj)
        
        if not matches.exists():
            return False
        
        # Check if all matches are completed
        for match in matches:
            if match.status not in ['completed', 'cancelled']:
                return False
        
        return True
        
    except Exception as e:
        logger.error(f"Error checking if round {round_obj.number} complete: {e}")
        return False


def check_if_round_complete(tournament):
    """
    Check if all matches in the current round are complete.
    
    Args:
        tournament: Tournament object
        
    Returns:
        bool: True if all matches in current round are complete
    """
    from matches.models import Match
    from tournaments.models import Round
    
    if not tournament.current_round_number:
        return False
    
    try:
        # Get the current round
        current_round = Round.objects.filter(
            stage__tournament=tournament,
            number=tournament.current_round_number
        ).first()
        
        if not current_round:
            return False
        
        # Get all matches in this round
        matches = Match.objects.filter(round=current_round)
        
        if not matches.exists():
            return False
        
        # Check if all matches are completed
        for match in matches:
            if match.status not in ['completed', 'cancelled']:
                return False
        
        return True
        
    except Exception as e:
        logger.error(f"Error checking if round complete for tournament {tournament.id}: {e}")
        return False


def auto_shuffle_if_round_complete(tournament):
    """
    Automatically shuffle players if the current round is complete
    and auto-shuffle is enabled.
    
    Args:
        tournament: Tournament object
        
    Returns:
        dict: Shuffle result or None if no shuffle occurred
    """
    if not tournament.shuffle_players_after_round:
        return None
    
    if not check_if_round_complete(tournament):
        return None
    
    # Check if we've already shuffled for this round
    from tournaments.partnership_models import MeleeShuffleHistory
    
    already_shuffled = MeleeShuffleHistory.objects.filter(
        tournament=tournament,
        round_number=tournament.current_round_number
    ).exists()
    
    if already_shuffled:
        logger.debug(f"Already shuffled for round {tournament.current_round_number} in tournament {tournament.id}")
        return None
    
    # Perform automatic shuffle
    logger.info(f"Auto-shuffling players for tournament {tournament.name} after round {tournament.current_round_number}")
    result = shuffle_melee_players(tournament, shuffle_type='automatic', shuffled_by=None)
    
    return result
