"""
PFC MARKET - Stock Exchange Style Player Leaderboard
Shows all players ranked by rating with trend indicators based on last 2 games
"""
from django.shortcuts import render
from django.db.models import Q
from .models import PlayerProfile
import json


def calculate_player_trend(profile):
    """
    Calculate player's rating trend based on last 2 games.
    Returns: {
        'direction': 'up' | 'down' | 'neutral',
        'change': float (total change in last 2 games),
        'percentage': float (percentage change)
    }
    """
    if not profile.rating_history:
        return {
            'direction': 'neutral',
            'change': 0.0,
            'percentage': 0.0,
            'games_analyzed': 0
        }
    
    history = profile.rating_history
    if len(history) < 1:
        return {
            'direction': 'neutral',
            'change': 0.0,
            'percentage': 0.0,
            'games_analyzed': 0
        }
    
    # Get last 2 games (or fewer if player hasn't played 2 games yet)
    recent_games = history[-2:] if len(history) >= 2 else history[-1:]
    
    # Calculate total change from these games
    total_change = sum(game.get('change', 0) for game in recent_games)
    
    # Get the rating before these games for percentage calculation
    if len(history) >= 2:
        base_rating = history[-2].get('old_value', 100.0)
    else:
        base_rating = history[0].get('old_value', 100.0)
    
    # Calculate percentage change
    percentage_change = (total_change / base_rating * 100) if base_rating > 0 else 0.0
    
    # Determine direction
    if total_change > 0:
        direction = 'up'
    elif total_change < 0:
        direction = 'down'
    else:
        direction = 'neutral'
    
    return {
        'direction': direction,
        'change': round(total_change, 2),
        'percentage': round(percentage_change, 2),
        'games_analyzed': len(recent_games)
    }


def pfc_market(request):
    """
    Display the PFC MARKET leaderboard - stock exchange style ranking
    of all players by rating with trend indicators.
    """
    # Get all player profiles with ratings
    profiles = PlayerProfile.objects.select_related('player__team').order_by('-value')
    
    # Calculate trend for each player
    market_data = []
    for profile in profiles:
        trend = calculate_player_trend(profile)
        
        market_data.append({
            'player': profile.player,
            'rating': profile.value,
            'trend_direction': trend['direction'],
            'trend_change': trend['change'],
            'trend_percentage': trend['percentage'],
            'games_analyzed': trend['games_analyzed'],
            'team': profile.player.team.name if profile.player.team else 'No Team',
            'rank': 0  # Will be set after sorting
        })
    
    # Get sorting parameter from request
    sort_by = request.GET.get('sort', 'rating')  # 'rating' or 'trend'
    
    if sort_by == 'trend':
        # Sort by trend change (biggest gainers first, biggest losers last)
        market_data.sort(key=lambda x: x['trend_change'], reverse=True)
    else:
        # Default: sort by rating (already sorted from query)
        pass
    
    # Assign ranks
    for index, data in enumerate(market_data, start=1):
        data['rank'] = index
    
    # Calculate market statistics
    total_players = len(market_data)
    gainers = sum(1 for d in market_data if d['trend_direction'] == 'up')
    losers = sum(1 for d in market_data if d['trend_direction'] == 'down')
    neutral = sum(1 for d in market_data if d['trend_direction'] == 'neutral')
    
    # Calculate average rating
    avg_rating = sum(d['rating'] for d in market_data) / total_players if total_players > 0 else 0
    
    # Find top gainer and top loser
    top_gainer = max(market_data, key=lambda x: x['trend_change']) if market_data else None
    top_loser = min(market_data, key=lambda x: x['trend_change']) if market_data else None
    
    context = {
        'market_data': market_data,
        'sort_by': sort_by,
        'stats': {
            'total_players': total_players,
            'gainers': gainers,
            'losers': losers,
            'neutral': neutral,
            'avg_rating': round(avg_rating, 2),
            'top_gainer': top_gainer,
            'top_loser': top_loser,
        }
    }
    
    return render(request, 'teams/pfc_market.html', context)
