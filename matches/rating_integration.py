"""
Rating system integration for tournament matches.

This module provides safe rating update functionality that can be called
after match completion without affecting the existing match workflow.
"""

import logging
from django.db import transaction
from django.utils import timezone
from teams.models import PlayerProfile

logger = logging.getLogger(__name__)


def update_tournament_match_ratings(match):
    """
    Update player ratings after a tournament match completes.
    
    This function is designed to be called AFTER match completion
    and will not affect the match completion workflow if it fails.
    
    Args:
        match: The completed Match object
        
    Returns:
        dict: Summary of rating updates performed
    """
    if not match or match.status != "completed":
        logger.warning(f"Cannot update ratings: match {match.id if match else 'None'} is not completed")
        return {"success": False, "reason": "Match not completed"}
    
    if not match.winner or not match.loser:
        logger.info(f"Match {match.id} was a draw, no rating updates needed")
        return {"success": True, "reason": "Draw match, no rating changes"}
    
    try:
        with transaction.atomic():
            updates = []
            
            # Get team players with profiles
            winner_players = get_players_with_profiles(match.winner)
            loser_players = get_players_with_profiles(match.loser)
            
            if not winner_players and not loser_players:
                logger.info(f"Match {match.id}: No players have profiles, skipping rating updates")
                return {"success": True, "reason": "No players with profiles"}
            
            # Calculate team average ratings
            winner_avg_rating = calculate_team_average_rating(winner_players)
            loser_avg_rating = calculate_team_average_rating(loser_players)
            
            # Update winner ratings
            for player_profile in winner_players:
                try:
                    old_rating = player_profile.value
                    player_profile.update_rating(
                        opponent_value=loser_avg_rating,
                        own_score=match.team1_score if match.winner == match.team1 else match.team2_score,
                        opponent_score=match.team2_score if match.winner == match.team1 else match.team1_score,
                        match_id=match.id
                    )
                    new_rating = player_profile.value
                    updates.append({
                        "player": player_profile.player.name,
                        "old_rating": old_rating,
                        "new_rating": new_rating,
                        "change": new_rating - old_rating,
                        "result": "win"
                    })
                    logger.info(f"Updated winner {player_profile.player.name}: {old_rating:.1f} → {new_rating:.1f}")
                except Exception as e:
                    logger.error(f"Failed to update rating for winner {player_profile.player.name}: {e}")
            
            # Update loser ratings
            for player_profile in loser_players:
                try:
                    old_rating = player_profile.value
                    player_profile.update_rating(
                        opponent_value=winner_avg_rating,
                        own_score=match.team2_score if match.loser == match.team2 else match.team1_score,
                        opponent_score=match.team1_score if match.loser == match.team2 else match.team2_score,
                        match_id=match.id
                    )
                    new_rating = player_profile.value
                    updates.append({
                        "player": player_profile.player.name,
                        "old_rating": old_rating,
                        "new_rating": new_rating,
                        "change": new_rating - old_rating,
                        "result": "loss"
                    })
                    logger.info(f"Updated loser {player_profile.player.name}: {old_rating:.1f} → {new_rating:.1f}")
                except Exception as e:
                    logger.error(f"Failed to update rating for loser {player_profile.player.name}: {e}")
            
            logger.info(f"Tournament match {match.id} rating updates completed: {len(updates)} players updated")
            return {
                "success": True,
                "updates": updates,
                "total_players": len(updates)
            }
            
    except Exception as e:
        logger.error(f"Failed to update ratings for tournament match {match.id}: {e}")
        return {"success": False, "reason": str(e)}


def get_players_with_profiles(team):
    """Get all players in a team that have PlayerProfile objects."""
    if not team:
        return []
    
    players_with_profiles = []
    for player in team.players.all():
        try:
            profile = player.profile  # Fixed: use 'profile' instead of 'playerprofile'
            players_with_profiles.append(profile)
        except PlayerProfile.DoesNotExist:
            logger.debug(f"Player {player.name} has no profile, skipping rating update")
            continue
    
    return players_with_profiles


def calculate_team_average_rating(player_profiles):
    """Calculate the average rating of a team's players with profiles."""
    if not player_profiles:
        return 100.0  # Default rating for teams with no profiles
    
    total_rating = sum(profile.value for profile in player_profiles)
    return total_rating / len(player_profiles)


def update_friendly_game_ratings(friendly_game):
    """
    Update player ratings after a friendly game completes.
    
    Only updates ratings for FULLY_VALIDATED games and players with codename_verified=True.
    
    Args:
        friendly_game: The completed FriendlyGame object
        
    Returns:
        dict: Summary of rating updates performed
    """
    if not friendly_game or friendly_game.status != "COMPLETED":
        logger.warning(f"Cannot update ratings: friendly game {friendly_game.id if friendly_game else 'None'} is not completed")
        return {"success": False, "reason": "Game not completed"}
    
    if friendly_game.validation_status != "FULLY_VALIDATED":
        logger.info(f"Friendly game {friendly_game.id} is not fully validated, skipping rating updates")
        return {"success": True, "reason": "Game not fully validated"}
    
    try:
        with transaction.atomic():
            updates = []
            
            # Get verified players with profiles from both teams
            black_players = get_verified_friendly_players_with_profiles(friendly_game, "BLACK")
            white_players = get_verified_friendly_players_with_profiles(friendly_game, "WHITE")
            
            if not black_players and not white_players:
                logger.info(f"Friendly game {friendly_game.id}: No verified players have profiles, skipping rating updates")
                return {"success": True, "reason": "No verified players with profiles"}
            
            # Calculate team average ratings
            black_avg_rating = calculate_team_average_rating(black_players)
            white_avg_rating = calculate_team_average_rating(white_players)
            
            # Determine winner/loser based on game result
            # Scores are stored in the FriendlyGame model, not the result
            black_score = friendly_game.black_team_score
            white_score = friendly_game.white_team_score
            
            if black_score == white_score:
                logger.info(f"Friendly game {friendly_game.id} was a draw, no rating updates needed")
                return {"success": True, "reason": "Draw game, no rating changes"}
            
            # Update ratings for verified players
            winner_team = "BLACK" if black_score > white_score else "WHITE"
            
            # Update black team players
            for player_profile in black_players:
                try:
                    old_rating = player_profile.value
                    player_profile.update_rating(
                        opponent_value=white_avg_rating,
                        own_score=black_score,
                        opponent_score=white_score,
                        match_id=f"friendly_{friendly_game.id}"
                    )
                    new_rating = player_profile.value
                    updates.append({
                        "player": player_profile.player.name,
                        "old_rating": old_rating,
                        "new_rating": new_rating,
                        "change": new_rating - old_rating,
                        "result": "win" if winner_team == "BLACK" else "loss"
                    })
                    logger.info(f"Updated black player {player_profile.player.name}: {old_rating:.1f} → {new_rating:.1f}")
                except Exception as e:
                    logger.error(f"Failed to update rating for black player {player_profile.player.name}: {e}")
            
            # Update white team players
            for player_profile in white_players:
                try:
                    old_rating = player_profile.value
                    player_profile.update_rating(
                        opponent_value=black_avg_rating,
                        own_score=white_score,
                        opponent_score=black_score,
                        match_id=f"friendly_{friendly_game.id}"
                    )
                    new_rating = player_profile.value
                    updates.append({
                        "player": player_profile.player.name,
                        "old_rating": old_rating,
                        "new_rating": new_rating,
                        "change": new_rating - old_rating,
                        "result": "win" if winner_team == "WHITE" else "loss"
                    })
                    logger.info(f"Updated white player {player_profile.player.name}: {old_rating:.1f} → {new_rating:.1f}")
                except Exception as e:
                    logger.error(f"Failed to update rating for white player {player_profile.player.name}: {e}")
            
            logger.info(f"Friendly game {friendly_game.id} rating updates completed: {len(updates)} players updated")
            return {
                "success": True,
                "updates": updates,
                "total_players": len(updates)
            }
            
    except Exception as e:
        logger.error(f"Failed to update ratings for friendly game {friendly_game.id}: {e}")
        return {"success": False, "reason": str(e)}


def get_verified_friendly_players_with_profiles(friendly_game, team_color):
    """Get verified players with profiles from a specific team in a friendly game."""
    players_with_profiles = []
    
    game_players = friendly_game.players.filter(team=team_color, codename_verified=True)
    
    for game_player in game_players:
        try:
            # Get the actual Player object directly (FriendlyGamePlayer has direct player relationship)
            player = game_player.player
            if hasattr(player, 'profile'):
                profile = player.profile
                players_with_profiles.append(profile)
        except (AttributeError, Exception) as e:
            logger.debug(f"Player {player.name if 'player' in locals() else 'unknown'} has no profile, skipping rating update: {e}")
            continue
    
    return players_with_profiles

