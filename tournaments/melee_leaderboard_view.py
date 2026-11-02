"""
Mêlée Tournament Player Leaderboard
Shows individual player rankings for mêlée tournaments where teams shuffle.
"""
from django.shortcuts import render, get_object_or_404
from .models import Tournament
from .partnership_models import MeleePlayerStats
from teams.models import PlayerProfile


def calculate_melee_badges(stats_list, rating_changes=None):
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
    rating_changes = rating_changes or {}

    def event_change(stats):
        player_id = getattr(stats, 'player_id', None) or stats.player.id
        if player_id in rating_changes:
            return rating_changes[player_id]
        return stats.current_rating - stats.starting_rating

    # Find tournament winner (biggest rating improvement)
    max_change = max(event_change(s) for s in stats_list)
    
    # Find longest win streak
    max_streak = max(s.best_performance for s in stats_list) if stats_list else 0
    
    # Find most points scored
    max_points = max(s.points_scored for s in stats_list) if stats_list else 0
    
    # Find best win rate (with minimum 3 games played)
    qualified_stats = [s for s in stats_list if s.matches_played >= 3]
    max_win_rate = max(((s.wins / s.matches_played * 100) for s in qualified_stats), default=0) if qualified_stats else 0
    
    for stats in stats_list:
        player_badges = []
        
        # 🏆 Tournament Leader (biggest rating improvement)
        player_change = event_change(stats)
        if player_change == max_change and stats.matches_played > 0 and max_change > 0:
            player_badges.append({
                'emoji': '🏆',
                'title': f'Most Improved: +{round(max_change, 1)}',
                'type': 'winner'
            })
        
        # 🔥 Longest Win Streak (tied for longest, minimum 3)
        if stats.best_performance >= 3 and stats.best_performance == max_streak:
            player_badges.append({
                'emoji': '🔥',
                'title': f'Win Streak: {stats.best_performance}',
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
    
    # Fully frozen individual standings come from permanent tournament history;
    # never read subsequent Friendly/Game rating changes to rank past events.
    from .models import PlayerTournamentAchievement, PlayerTournamentHistory

    frozen = {
        entry.player_id: entry
        for entry in PlayerTournamentHistory.objects.filter(
            tournament=tournament, melee_final_rank__isnull=False
        )
    }
    is_frozen = bool(stats_list) and len(frozen) == len(stats_list) and all(
        stats.player_id in frozen for stats in stats_list
    )
    if is_frozen:
        stats_list.sort(key=lambda stats: frozen[stats.player_id].melee_final_rank)
        badges_map = {stats.player_id: [] for stats in stats_list}
        badge_types = {
            "most_improved": "winner",
            "win_streak": "streak",
            "top_scorer": "points",
            "best_win_rate": "winrate",
        }
        for award in PlayerTournamentAchievement.objects.filter(
            tournament=tournament, player_id__in=frozen,
        ):
            badge_type = badge_types.get(award.award_type)
            if badge_type:
                badges_map[award.player_id].append({
                    "emoji": award.display_symbol,
                    "title": award.display_title,
                    "type": badge_type,
                })
    else:
        stats_list.sort(
            key=lambda stats: (
                -(stats.current_rating - stats.starting_rating),
                -stats.wins,
                stats.player_id,
            )
        )
        badges_map = calculate_melee_badges(stats_list)
    
    # Prepare leaderboard data
    leaderboard_data = []
    for rank, stats in enumerate(stats_list, start=1):
        snapshot = frozen[stats.player_id] if is_frozen else None
        event_change = (
            float(snapshot.rating_change)
            if snapshot else stats.current_rating - stats.starting_rating
        )
        event_rating = (
            float(snapshot.melee_final_rating)
            if snapshot else stats.current_rating
        )
        # Get player profile for additional info
        profile = None
        if hasattr(stats.player, 'profile'):
            profile = stats.player.profile
        
        leaderboard_data.append({
            'rank': rank,
            'player': stats.player,
            'profile': profile,
            'starting_rating': round(stats.starting_rating, 1),
            'current_rating': round(event_rating, 1),
            'rating_change': round(event_change, 1),
            'wins': snapshot.wins if snapshot else stats.wins,
            'losses': snapshot.losses if snapshot else stats.losses,
            'matches_played': snapshot.matches_played if snapshot else stats.matches_played,
            'win_rate': round(
                100 * (snapshot.wins if snapshot else stats.wins)
                / (snapshot.matches_played if snapshot else stats.matches_played), 1
            ) if (snapshot.matches_played if snapshot else stats.matches_played) else 0,
            'points_scored': snapshot.points_scored if snapshot else stats.points_scored,
            'points_against': snapshot.points_against if snapshot else stats.points_against,
            'point_differential': (
                snapshot.points_scored - snapshot.points_against
                if snapshot and snapshot.points_scored is not None and snapshot.points_against is not None
                else stats.points_scored - stats.points_against
            ),
            'current_streak': stats.current_streak,
            'badges': badges_map.get(stats.player.id, []),
        })
    
    # Summary is computed from the same frozen or provisional rows as rankings.
    total_players = len(leaderboard_data)
    gainers = sum(row["rating_change"] > 0 for row in leaderboard_data)
    losers = sum(row["rating_change"] < 0 for row in leaderboard_data)
    avg_rating = (
        sum(row["current_rating"] for row in leaderboard_data) / total_players
        if total_players else 0
    )
    top_gainer = None
    if leaderboard_data and leaderboard_data[0]["rating_change"] > 0:
        top_gainer = {
            "player": leaderboard_data[0]["player"],
            "change": leaderboard_data[0]["rating_change"],
        }
    
    context = {
        'tournament': tournament,
        'leaderboard_data': leaderboard_data,
        'total_players': total_players,
        'gainers': gainers,
        'losers': losers,
        'avg_rating': round(avg_rating, 2),
        'top_gainer': top_gainer,
        'is_frozen': is_frozen,
    }
    
    return render(request, 'tournaments/melee_leaderboard.html', context)
