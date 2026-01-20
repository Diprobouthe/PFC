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
            
            # Get team players with profiles (only those who actually participated)
            winner_players = get_players_with_profiles(match.winner, match)
            loser_players = get_players_with_profiles(match.loser, match)
            
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
            
            # ===== UPDATE TEAM VALUES =====
            # Update team values based on new player ratings
            team_updates = []
            
            # Update winner team value
            try:
                winner_profile = getattr(match.winner, 'profile', None)
                if winner_profile:
                    old_team_value = winner_profile.team_value
                    if winner_profile.update_team_value():
                        new_team_value = winner_profile.team_value
                        team_updates.append({
                            "team": match.winner.name,
                            "old_value": old_team_value,
                            "new_value": new_team_value,
                            "change": new_team_value - old_team_value
                        })
                        logger.info(f"Updated winner team {match.winner.name}: {old_team_value:.1f} → {new_team_value:.1f}")
            except Exception as e:
                logger.error(f"Failed to update team value for winner {match.winner.name}: {e}")
            
            # Update loser team value
            try:
                loser_profile = getattr(match.loser, 'profile', None)
                if loser_profile:
                    old_team_value = loser_profile.team_value
                    if loser_profile.update_team_value():
                        new_team_value = loser_profile.team_value
                        team_updates.append({
                            "team": match.loser.name,
                            "old_value": old_team_value,
                            "new_value": new_team_value,
                            "change": new_team_value - old_team_value
                        })
                        logger.info(f"Updated loser team {match.loser.name}: {old_team_value:.1f} → {new_team_value:.1f}")
            except Exception as e:
                logger.error(f"Failed to update team value for loser {match.loser.name}: {e}")
            
            logger.info(f"Tournament match {match.id} rating updates completed: {len(updates)} players updated, {len(team_updates)} teams updated")
            return {
                "success": True,
                "updates": updates,
                "team_updates": team_updates,
                "total_players": len(updates)
            }
            
    except Exception as e:
        logger.error(f"Failed to update ratings for tournament match {match.id}: {e}")
        return {"success": False, "reason": str(e)}


def get_players_with_profiles(team, match=None):
    """Get players with profiles who actually participated in the match.
    
    Uses MatchPlayer records to identify only the players who were selected/participated.
    This applies to ALL tournaments (mêlée and non-mêlée).
    
    Args:
        team: The team object
        match: The match object (required to identify selected players)
    
    Returns:
        list: PlayerProfile objects for participating players only
    """
    if not team:
        return []
    
    players_with_profiles = []
    
    # Get only the players who actually participated in this match
    if match:
        participating_players = get_match_participants(match, team)
        if not participating_players:
            logger.warning(f"No MatchPlayer records found for team {team.name} in match {match.id}")
            # Fallback to all team players if MatchPlayer data not found
            logger.warning(f"Falling back to all team players for match {match.id}")
            participating_players = team.players.all()
    else:
        # If no match provided, use all team players (backward compatibility)
        logger.warning(f"No match provided to get_players_with_profiles, using all team players")
        participating_players = team.players.all()
    
    for player in participating_players:
        try:
            profile = player.profile
            players_with_profiles.append(profile)
        except PlayerProfile.DoesNotExist:
            logger.debug(f"Player {player.name} has no profile, skipping rating update")
            continue
    
    return players_with_profiles


def get_match_participants(match, team):
    """Get the specific players who participated in a match for a given team.
    
    Uses MatchPlayer records to identify exactly which players were selected.
    This works for ALL tournament types (mêlée and non-mêlée).
    
    Args:
        match: The Match object
        team: The team to get participants for
    
    Returns:
        list: Player objects who actually participated
    """
    from matches.models import MatchPlayer
    
    # Query MatchPlayer records for this match and team
    match_players = MatchPlayer.objects.filter(
        match=match,
        team=team
    ).select_related('player')
    
    if not match_players.exists():
        logger.warning(f"No MatchPlayer records found for match {match.id}, team {team.name}")
        return []
    
    # Extract the Player objects
    participants = [mp.player for mp in match_players]
    
    logger.info(f"Match {match.id}: Found {len(participants)} participants for team {team.name}: {[p.name for p in participants]}")
    
    return participants


def get_melee_match_participants(match, team):
    """DEPRECATED: Use get_match_participants() instead.
    
    This function is kept for backward compatibility but now delegates to get_match_participants().
    
    Args:
        match: The Match object
        team: The team to get participants for
    
    Returns:
        list: Player objects who actually participated
    """
    logger.warning(f"get_melee_match_participants() is deprecated, use get_match_participants() instead")
    return get_match_participants(match, team)


def _get_melee_match_participants_legacy(match, team):
    """Legacy implementation using MeleePartnership (kept for reference).
    
    This is the old mêlée-specific implementation. The new implementation uses
    MatchPlayer which works for all tournament types.
    
    Args:
        match: The Match object
        team: The team to get participants for
    
    Returns:
        list: Player objects who actually participated
    """
    import re
    from tournaments.partnership_models import MeleePartnership
    
    tournament = match.tournament
    
    # Extract round number from match.round
    round_number = None
    if match.round:
        round_match = re.search(r'Round (\d+)', str(match.round))
        if round_match:
            round_number = int(round_match.group(1))
    
    if not round_number:
        logger.warning(f"Could not extract round number from match {match.id}")
        return []
    
    # Get partnership record for this team in this round
    partnership = MeleePartnership.objects.filter(
        tournament=tournament,
        round_number=round_number,
        team_name=team.name
    ).first()
    
    if not partnership:
        logger.warning(f"No partnership found for team {team.name} in round {round_number}")
        return []
    
    # Get the specific players from the partnership
    participants = [partnership.player1, partnership.player2]
    if hasattr(partnership, 'player3') and partnership.player3:
        participants.append(partnership.player3)
    
    # Filter out None values
    participants = [p for p in participants if p is not None]
    
    logger.info(f"Match {match.id}: Found {len(participants)} participants for team {team.name}: {[p.name for p in participants]}")
    
    return participants


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
            
            # ===== UPDATE TEAM VALUES FOR FRIENDLY GAMES =====
            # Update team values for all teams that had players participate
            team_updates = []
            teams_to_update = set()
            
            # Collect all teams that had players in this game
            for player_profile in black_players + white_players:
                teams_to_update.add(player_profile.player.team)
            
            # Update each team's value
            for team in teams_to_update:
                try:
                    team_profile = getattr(team, 'profile', None)
                    if team_profile:
                        old_team_value = team_profile.team_value
                        if team_profile.update_team_value():
                            new_team_value = team_profile.team_value
                            team_updates.append({
                                "team": team.name,
                                "old_value": old_team_value,
                                "new_value": new_team_value,
                                "change": new_team_value - old_team_value
                            })
                            logger.info(f"Updated team {team.name}: {old_team_value:.1f} → {new_team_value:.1f}")
                except Exception as e:
                    logger.error(f"Failed to update team value for {team.name}: {e}")
            
            logger.info(f"Friendly game {friendly_game.id} rating updates completed: {len(updates)} players updated, {len(team_updates)} teams updated")
            return {
                "success": True,
                "updates": updates,
                "team_updates": team_updates,
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




def update_all_team_values():
    """
    Utility function to update all team values based on current player ratings.
    Useful for fixing existing teams or after system changes.
    
    Returns:
        dict: Summary of team value updates performed
    """
    try:
        from teams.models import TeamProfile
        
        team_profiles = TeamProfile.objects.all()
        updates = []
        
        for team_profile in team_profiles:
            try:
                old_value = team_profile.team_value
                if team_profile.update_team_value():
                    new_value = team_profile.team_value
                    updates.append({
                        "team": team_profile.team.name,
                        "old_value": old_value,
                        "new_value": new_value,
                        "change": new_value - old_value
                    })
                    logger.info(f"Updated team {team_profile.team.name}: {old_value:.1f} → {new_value:.1f}")
            except Exception as e:
                logger.error(f"Failed to update team value for {team_profile.team.name}: {e}")
        
        logger.info(f"Bulk team value update completed: {len(updates)} teams updated")
        return {
            "success": True,
            "updates": updates,
            "total_teams": len(updates)
        }
        
    except Exception as e:
        logger.error(f"Failed to update all team values: {e}")
        return {"success": False, "reason": str(e)}

