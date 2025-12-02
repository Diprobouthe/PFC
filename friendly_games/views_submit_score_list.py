"""
Friendly Games Score Submission List View
Shows all active games that the logged-in player is participating in
"""
from django.shortcuts import render, redirect
from django.contrib import messages
from .models import FriendlyGame, FriendlyGamePlayer, PlayerCodename
import logging

logger = logging.getLogger(__name__)


def submit_score_list(request):
    """
    Display a list of active friendly games that the player is participating in
    and needs to submit scores for.
    
    Similar to tournament score submission, but for friendly games.
    """
    # Get the logged-in player's codename from session
    player_codename = request.session.get('player_codename')
    
    print(f"\n=== SUBMIT SCORE LIST DEBUG ===")
    print(f"Session player_codename: {player_codename}")
    print(f"All session keys: {list(request.session.keys())}")
    
    logger.info(f"Submit score list accessed. Session player_codename: {player_codename}")
    
    if not player_codename:
        messages.warning(request, 'Please log in with your player codename to submit scores.')
        return redirect('home')
    
    # Find the player from the codename
    try:
        codename_obj = PlayerCodename.objects.get(codename=player_codename.upper())
        player = codename_obj.player
        logger.info(f"Found player: {player.name} (ID: {player.id})")
    except PlayerCodename.DoesNotExist:
        logger.error(f"PlayerCodename not found for: {player_codename}")
        messages.error(request, 'Player not found. Please log in again.')
        return redirect('home')
    
    # Get all active games (IN_PROGRESS) where this player is participating
    # and scores haven't been submitted yet
    active_games = FriendlyGame.objects.filter(
        status='IN_PROGRESS',
        players__player=player
    ).select_related().prefetch_related('players__player').distinct().order_by('-created_at')
    
    logger.info(f"Found {active_games.count()} active games for player {player.name}")
    
    # Filter out games that already have results submitted
    games_needing_scores = []
    for game in active_games:
        # Check if result already exists
        has_result = hasattr(game, 'result')
        logger.info(f"Game #{game.match_number}: has_result={has_result}")
        if not has_result:
            # Get player's team in this game
            player_game_record = game.players.filter(player=player).first()
            if player_game_record:
                game.player_team = player_game_record.team  # Add team info for display
                games_needing_scores.append(game)
                logger.info(f"Added game #{game.match_number} to needing_scores list")
    
    # Also get games waiting for validation (where result exists but not validated)
    games_waiting_validation = FriendlyGame.objects.filter(
        status='IN_PROGRESS',
        players__player=player,
        result__isnull=False  # Has result
    ).select_related('result').prefetch_related('players__player').distinct().order_by('-created_at')
    
    # Add team info for validation games
    for game in games_waiting_validation:
        player_game_record = game.players.filter(player=player).first()
        if player_game_record:
            game.player_team = player_game_record.team
    
    context = {
        'player': player,
        'games_needing_scores': games_needing_scores,
        'games_waiting_validation': games_waiting_validation,
        'has_games': len(games_needing_scores) > 0 or len(games_waiting_validation) > 0,
    }
    
    return render(request, 'friendly_games/submit_score_list.html', context)
