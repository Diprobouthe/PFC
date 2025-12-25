"""
Mêlée Tournament Player Leaderboard
Shows individual player rankings for mêlée tournaments where teams shuffle.
"""
from django.shortcuts import render, get_object_or_404
from .models import Tournament
from .partnership_models import MeleePlayerStats
from teams.models import PlayerProfile


def calculate_melee_badges(stats_list):
    """
    Calculate which players earn which badges based on tournament-wide comparison.
    
    Args:
        stats_list: List of MeleePlayerStats objects
    
    Returns:
        Dict mapping player_id to list of badges
    """
    if not stats_list:
        return {}
    
    badges_map = {}
    
    # Find tournament winner (highest current rating)
    max_rating = max(s.current_rating for s in stats_list)
    
    # Find longest win streak
    max_streak = max(s.current_streak for s in stats_list) if stats_list else 0
    
    # Find most points scored
    max_points = max(s.points_scored for s in stats_list) if stats_list else 0
    
    # Find best win rate (with minimum 3 games played)
    qualified_stats = [s for s in stats_list if s.matches_played >= 3]
    max_win_rate = max(((s.wins / s.matches_played * 100) for s in qualified_stats), default=0) if qualified_stats else 0
    
    for stats in stats_list:
        player_badges = []
        
        # 🏆 Tournament Winner (highest rating)
        if stats.current_rating == max_rating and stats.matches_played > 0:
            player_badges.append({
                'emoji': '🏆',
                'title': 'Tournament Leader',
                'type': 'winner'
            })
        
        # 🔥 Longest Win Streak (tied for longest, minimum 3)
        if stats.current_streak >= 3 and stats.current_streak == max_streak:
            player_badges.append({
                'emoji': '🔥',
                'title': f'Win Streak: {stats.current_streak}',
                'type': 'streak'
            })
        
        # ⭐ Most Points Scored (tied for most)
        if stats.points_scored > 0 and stats.points_scored == max_points:
            player_badges.append({
                'emoji': '⭐',
                'title': f'Top Scorer: {stats.points_scored} pts',
                'type': 'points'
            })
        
        # 🎯 Best Win Rate (tied for best, minimum 3 games)
        if stats.matches_played >= 3:
            # Calculate win rate
            win_rate = round((stats.wins / stats.matches_played) * 100, 1) if stats.matches_played > 0 else 0
            if win_rate == max_win_rate and max_win_rate >= 80:
                player_badges.append({
                    'emoji': '🎯',
                    'title': f'Best Win Rate: {win_rate}%',
                    'type': 'winrate'
                })
        
        badges_map[stats.player.id] = player_badges
    
    return badges_map


def melee_player_leaderboard(request, tournament_id):
    """
    Display player leaderboard for mêlée tournaments.
    Shows individual rankings with PFC ratings, wins/losses, and badges.
    """
    tournament = get_object_or_404(Tournament, id=tournament_id)
    
    # Only show for mêlée tournaments
    if not tournament.is_melee:
        return render(request, 'tournaments/melee_leaderboard.html', {
            'tournament': tournament,
            'error': 'This tournament is not configured for Mêlée mode.'
        })
    
    # Get all player stats for this tournament
    # Note: current_rating is now a property, so we can't order by it in the database
    stats_list = list(
        MeleePlayerStats.objects
        .filter(tournament=tournament)
        .select_related('player')
    )
    
    # Sort by current_rating (property) in Python
    stats_list.sort(key=lambda s: (-s.current_rating, -s.wins))
    
    # Calculate badges
    badges_map = calculate_melee_badges(stats_list)
    
    # Prepare leaderboard data
    leaderboard_data = []
    for rank, stats in enumerate(stats_list, start=1):
        # Get player profile for additional info
        profile = None
        if hasattr(stats.player, 'profile'):
            profile = stats.player.profile
        
        leaderboard_data.append({
            'rank': rank,
            'player': stats.player,
            'profile': profile,
            'starting_rating': round(stats.starting_rating, 1),
            'current_rating': round(stats.current_rating, 1),
            'rating_change': round(stats.current_rating - stats.starting_rating, 1),
            'wins': stats.wins,
            'losses': stats.losses,
            'matches_played': stats.matches_played,
            'win_rate': round((stats.wins / stats.matches_played * 100), 1) if stats.matches_played > 0 else 0,
            'points_scored': stats.points_scored,
            'points_against': stats.points_against,
            'point_differential': stats.points_scored - stats.points_against,
            'current_streak': stats.current_streak,
            'badges': badges_map.get(stats.player.id, []),
        })
    
    # Calculate summary statistics
    total_players = len(stats_list)
    gainers = sum(1 for s in stats_list if (s.current_rating - s.starting_rating) > 0)
    losers = sum(1 for s in stats_list if (s.current_rating - s.starting_rating) < 0)
    avg_rating = sum(s.current_rating for s in stats_list) / total_players if total_players > 0 else 0
    
    # Find top gainer
    top_gainer = None
    if stats_list:
        top_gainer_stats = max(stats_list, key=lambda s: s.current_rating - s.starting_rating)
        rating_change = top_gainer_stats.current_rating - top_gainer_stats.starting_rating
        if rating_change > 0:
            top_gainer = {
                'player': top_gainer_stats.player,
                'change': round(rating_change, 1)
            }
    
    context = {
        'tournament': tournament,
        'leaderboard_data': leaderboard_data,
        'total_players': total_players,
        'gainers': gainers,
        'losers': losers,
        'avg_rating': round(avg_rating, 2),
        'top_gainer': top_gainer,
    }
    
    return render(request, 'tournaments/melee_leaderboard.html', context)
