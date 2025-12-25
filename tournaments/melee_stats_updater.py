"""
Mêlée Player Statistics Updater
Handles initialization and updating of player statistics for mêlée tournaments
"""
from django.db import transaction
from tournaments.partnership_models import MeleePlayerStats
from teams.models import PlayerProfile


def initialize_melee_player_stats(tournament, use_current_time=True):
    """
    Initialize MeleePlayerStats for all registered players in a mêlée tournament.
    Should be called when tournament starts or teams are generated.
    
    Args:
        tournament: Tournament object (must be is_melee=True)
        use_current_time: If True, use current rating. If False, try to use rating at team generation time.
    """
    if not tournament.is_melee:
        return 0
    
    initialized_count = 0
    
    # Determine what time to use for ratings
    rating_time = None
    if not use_current_time:
        # Try to find when teams were generated
        from tournaments.models import TournamentTeam
        first_team = TournamentTeam.objects.filter(
            tournament=tournament,
            team__name__startswith="Mêlée Team"
        ).order_by('created_at').first()
        if first_team and hasattr(first_team, 'created_at'):
            rating_time = first_team.created_at
    
    with transaction.atomic():
        for melee_player in tournament.melee_players.all():
            # Get the actual Player object from MeleePlayer
            player = melee_player.player
            
            # Get player's rating at the appropriate time
            if rating_time:
                from tournaments.rating_history_utils import get_player_rating_at_time
                starting_rating = get_player_rating_at_time(player, rating_time)
            else:
                # Use current rating
                try:
                    profile = PlayerProfile.objects.get(player=player)
                    starting_rating = profile.value
                except PlayerProfile.DoesNotExist:
                    # Default rating if no profile exists
                    starting_rating = 1000.0
            
            # Create or update player stats
            stats, created = MeleePlayerStats.objects.get_or_create(
                tournament=tournament,
                player=player,
                defaults={
                    'starting_rating': starting_rating,
                    # current_rating is now a property, not a field
                    'wins': 0,
                    'losses': 0,
                    'points_scored': 0,
                    'points_against': 0,
                    'matches_played': 0,
                    'current_streak': 0,
                    'best_performance': 0,
                }
            )
            
            if created:
                initialized_count += 1
    
    return initialized_count


def update_melee_player_stats_from_match(match):
    """
    Update MeleePlayerStats for all players in a completed match.
    Should be called when a match status changes to 'completed'.
    
    Args:
        match: Match object (must belong to a mêlée tournament)
    """
    from tournaments.partnership_models import MeleePartnership
    import re
    
    tournament = match.tournament
    
    if not tournament or not tournament.is_melee:
        return
    
    # Get match result
    team1 = match.team1
    team2 = match.team2
    
    if not team1 or not team2:
        return
    
    # Extract round number from match.round
    round_number = None
    if match.round:
        round_match = re.search(r'Round (\d+)', str(match.round))
        if round_match:
            round_number = int(round_match.group(1))
    
    if not round_number:
        print(f"Warning: Could not extract round number from match {match.id}")
        return
    
    # Determine winner
    if match.team1_score > match.team2_score:
        winning_team = team1
        losing_team = team2
        winning_score = match.team1_score
        losing_score = match.team2_score
    elif match.team2_score > match.team1_score:
        winning_team = team2
        losing_team = team1
        winning_score = match.team2_score
        losing_score = match.team1_score
    else:
        # Draw - treat as no winner
        winning_team = None
        losing_team = None
        winning_score = match.team1_score
        losing_score = match.team2_score
    
    # Get players from MeleePartnership
    team1_partnership = MeleePartnership.objects.filter(
        tournament=tournament,
        round_number=round_number,
        team_name=team1.name
    ).first()
    
    team2_partnership = MeleePartnership.objects.filter(
        tournament=tournament,
        round_number=round_number,
        team_name=team2.name
    ).first()
    
    if not team1_partnership or not team2_partnership:
        print(f"Warning: Could not find partnerships for match {match.id} round {round_number}")
        return
    
    # Get players from partnerships
    team1_players = [team1_partnership.player1, team1_partnership.player2]
    if hasattr(team1_partnership, 'player3') and team1_partnership.player3:
        team1_players.append(team1_partnership.player3)
    
    team2_players = [team2_partnership.player1, team2_partnership.player2]
    if hasattr(team2_partnership, 'player3') and team2_partnership.player3:
        team2_players.append(team2_partnership.player3)
    
    with transaction.atomic():
        # Update stats for team1 players
        for player in team1_players:
            stats, created = MeleePlayerStats.objects.get_or_create(
                tournament=tournament,
                player=player,
                defaults={
                    'starting_rating': _get_player_rating(player),
                }
            )
            
            # Update match count
            stats.matches_played += 1
            
            # Update points
            stats.points_scored += match.team1_score
            stats.points_against += match.team2_score
            
            # Update wins/losses and streak
            if winning_team == team1:
                stats.wins += 1
                stats.current_streak = max(0, stats.current_streak) + 1
                stats.best_performance = max(stats.best_performance, stats.current_streak)
            elif losing_team == team1:
                stats.losses += 1
                stats.current_streak = min(0, stats.current_streak) - 1
            
            # Note: current_rating is a property that pulls live from PlayerProfile
            
            stats.save()
        
        # Update stats for team2 players
        for player in team2_players:
            stats, created = MeleePlayerStats.objects.get_or_create(
                tournament=tournament,
                player=player,
                defaults={
                    'starting_rating': _get_player_rating(player),
                }
            )
            
            # Update match count
            stats.matches_played += 1
            
            # Update points
            stats.points_scored += match.team2_score
            stats.points_against += match.team1_score
            
            # Update wins/losses and streak
            if winning_team == team2:
                stats.wins += 1
                stats.current_streak = max(0, stats.current_streak) + 1
                stats.best_performance = max(stats.best_performance, stats.current_streak)
            elif losing_team == team2:
                stats.losses += 1
                stats.current_streak = min(0, stats.current_streak) - 1
            
            # Note: current_rating is a property that pulls live from PlayerProfile
            
            stats.save()


def _get_player_rating(player):
    """
    Get player's current PFC rating from their profile.
    Returns default 1000.0 if profile doesn't exist.
    """
    try:
        profile = PlayerProfile.objects.get(player=player)
        return profile.value
    except PlayerProfile.DoesNotExist:
        return 1000.0


def recalculate_all_melee_stats(tournament):
    """
    Recalculate all player statistics for a mêlée tournament from scratch.
    Useful for fixing inconsistencies or after data changes.
    
    Args:
        tournament: Tournament object (must be is_melee=True)
    """
    if not tournament.is_melee:
        return 0
    
    # Clear existing stats
    MeleePlayerStats.objects.filter(tournament=tournament).delete()
    
    # Initialize fresh stats using ratings at tournament creation time
    initialize_melee_player_stats(tournament, use_current_time=False)
    
    # Reprocess all completed matches
    from matches.models import Match
    completed_matches = Match.objects.filter(
        tournament=tournament,
        status='completed'
    ).order_by('created_at')
    
    for match in completed_matches:
        update_melee_player_stats_from_match(match)
    
    return completed_matches.count()
