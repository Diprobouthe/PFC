"""
Utility functions for retrieving historical player ratings
"""
from datetime import datetime
from teams.models import PlayerProfile


def get_player_rating_at_time(player, target_datetime):
    """
    Get a player's PFC rating at a specific point in time using rating history.
    
    Args:
        player: Player object
        target_datetime: datetime object for when to get the rating
        
    Returns:
        float: Player's rating at that time, or current rating if no history available
    """
    try:
        profile = PlayerProfile.objects.get(player=player)
    except PlayerProfile.DoesNotExist:
        return 1000.0  # Default rating
    
    # If no rating history, return current value
    if not profile.rating_history:
        return profile.value
    
    # Convert target_datetime to timezone-aware if needed
    if target_datetime.tzinfo is None:
        from django.utils import timezone
        target_datetime = timezone.make_aware(target_datetime)
    
    # Find the rating at the target time
    # Rating history is ordered chronologically
    last_rating_before_target = None
    
    for entry in profile.rating_history:
        entry_time = datetime.fromisoformat(entry['timestamp'])
        
        # If this entry is after our target time, we've gone too far
        if entry_time > target_datetime:
            break
        
        # This entry is before or at our target time
        last_rating_before_target = entry['new_value']
    
    # If we found a rating before the target time, use it
    if last_rating_before_target is not None:
        return last_rating_before_target
    
    # If target time is before all history entries, use the first old_value
    if profile.rating_history:
        return profile.rating_history[0]['old_value']
    
    # Fallback to current value
    return profile.value


def update_starting_ratings_for_tournament(tournament):
    """
    Update starting ratings for all players in a tournament based on when teams were generated.
    
    Args:
        tournament: Tournament object
        
    Returns:
        int: Number of player stats updated
    """
    from tournaments.models import TournamentTeam
    from tournaments.partnership_models import MeleePlayerStats
    
    if not tournament.is_melee:
        return 0
    
    # Find when teams were generated (use first TournamentTeam creation time)
    first_team = TournamentTeam.objects.filter(
        tournament=tournament,
        team__name__startswith="Mêlée Team"
    ).order_by('created_at').first()
    
    if not first_team or not hasattr(first_team, 'created_at'):
        print(f"Warning: Could not determine when teams were generated for {tournament.name}")
        return 0
    
    team_generation_time = first_team.created_at
    print(f"Teams generated at: {team_generation_time}")
    
    # Update all player stats
    updated_count = 0
    player_stats = MeleePlayerStats.objects.filter(tournament=tournament)
    
    for stats in player_stats:
        # Get the player's rating at team generation time
        historical_rating = get_player_rating_at_time(stats.player, team_generation_time)
        
        # Only update if different
        if abs(stats.starting_rating - historical_rating) > 0.01:
            old_rating = stats.starting_rating
            stats.starting_rating = historical_rating
            stats.save()
            updated_count += 1
            print(f"  {stats.player.name}: {old_rating:.2f} → {historical_rating:.2f}")
    
    return updated_count
