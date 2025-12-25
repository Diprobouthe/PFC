"""
View for showing player's active matches with priority ordering.
Accessed via the "PFC" button in the top navigation bar.
"""
from django.shortcuts import render, redirect
from django.db.models import Q
from matches.models import Match
from friendly_games.models import PlayerCodename, FriendlyGame, FriendlyGamePlayer, FriendlyGameResult


def my_active_matches(request):
    """
    Show all non-completed matches for the logged-in player,
    ordered by priority:
    1. Active tournament match
    2. Partially activated tournament match  
    3. Waiting validation tournament match
    4. Active friendly match
    5. Pending validation friendly match
    
    Never includes completed matches.
    """
    # Get player codename from session
    codename = request.session.get('player_codename')
    
    if not codename:
        # No player logged in - redirect to login or show empty state
        return render(request, 'pfc_core/my_matches.html', {
            'matches': [],
            'no_login': True,
        })
    
    try:
        player_codename = PlayerCodename.objects.get(codename=codename)
        player = player_codename.player
    except PlayerCodename.DoesNotExist:
        return render(request, 'pfc_core/my_matches.html', {
            'matches': [],
            'no_login': True,
        })
    
    # Get player's team (Player has one team via ForeignKey)
    player_team = player.team
    if not player_team:
        # No team assigned
        return render(request, 'pfc_core/my_matches.html', {
            'matches': [],
            'no_teams': True,
            'codename': codename
        })
    
    # Build query for tournament matches involving player's team
    # Exclude completed matches (handle both lowercase and title case)
    matches_query = Match.objects.filter(
        Q(team1=player_team) | Q(team2=player_team)
    ).exclude(
        Q(status__iexact='completed')  # Case-insensitive comparison
    ).select_related(
        'team1', 'team2', 'tournament', 'court'
    ).distinct()
    
    # Also get friendly games for this player
    friendly_games_query = FriendlyGame.objects.filter(
        players__player=player
    ).exclude(
        status__in=['COMPLETED', 'CANCELLED', 'EXPIRED']
    ).distinct()
    
    # Separate matches by category and priority
    # NEW: Result validation for friendly games (HIGHEST PRIORITY)
    friendly_games_need_validation = []  # Games where player needs to validate opponent's result
    
    active_tournament = []
    partially_activated_tournament = []
    waiting_validation_tournament = []
    active_friendly_matches = []  # For Match objects with no tournament
    active_friendly_games = []  # For FriendlyGame objects
    pending_validation_friendly = []
    
    # Process tournament matches
    for match in matches_query:
        is_tournament = match.tournament is not None
        status_lower = match.status.lower()  # Normalize to lowercase for comparison
        
        if status_lower == 'active':
            if is_tournament:
                active_tournament.append(match)
            else:
                active_friendly_matches.append(match)
        elif status_lower == 'partially activated' or status_lower == 'partially_activated':
            if is_tournament:
                partially_activated_tournament.append(match)
        elif status_lower in ['pending', 'pending verification', 'pending_verification', 'waiting_validation']:
            # Check if this is actually a partially activated match
            # (one team activated, but not the player's team)
            is_partially_activated = False
            if is_tournament:
                from matches.models import MatchActivation
                activations = MatchActivation.objects.filter(match=match)
                if activations.count() == 1:
                    # Only one team activated - check if it's the OTHER team
                    activated_team = activations.first().team
                    if activated_team.id != player_team.id:
                        # Other team activated, player's team hasn't
                        is_partially_activated = True
                        partially_activated_tournament.append(match)
                
                # Only add to waiting_validation if not partially activated
                if not is_partially_activated:
                    waiting_validation_tournament.append(match)
            else:
                pending_validation_friendly.append(match)
    
    # Process friendly games
    for game in friendly_games_query:
        # Check if this game needs validation from the player
        needs_validation = False
        if game.status == 'PENDING_VALIDATION' and hasattr(game, 'result'):
            result = game.result
            # Find which team the player is on
            try:
                player_participation = FriendlyGamePlayer.objects.get(game=game, player=player)
                player_team = player_participation.team
                
                # If the OTHER team submitted the result, this player needs to validate
                if result.submitted_by_team != player_team:
                    needs_validation = True
                    friendly_games_need_validation.append(game)
            except FriendlyGamePlayer.DoesNotExist:
                pass
        
        # Only add to other categories if not already in validation list
        if not needs_validation:
            if game.status == 'ACTIVE':
                active_friendly_games.append(game)
            elif game.status == 'PENDING_VALIDATION':
                # Player's team submitted, waiting for opponent to validate
                pending_validation_friendly.append(game)
            elif game.status in ['READY', 'WAITING_FOR_PLAYERS']:
                # These are lower priority but still active
                active_friendly_games.append(game)
    
    # Combine in priority order
    # NEW PRIORITY: Result validation comes FIRST (close loose ends!)
    ordered_matches = (
        friendly_games_need_validation +  # HIGHEST PRIORITY!
        active_tournament +
        partially_activated_tournament +
        waiting_validation_tournament +
        active_friendly_games +
        active_friendly_matches +
        pending_validation_friendly
    )
    
    # Add priority labels for display
    for item in ordered_matches:
        if item in friendly_games_need_validation:
            item.priority_label = "⚠️ Result Needs Your Validation"
            item.priority_class = "danger"  # Red/urgent - HIGHEST PRIORITY!
            item.is_friendly_game = True
            item.needs_validation = True  # Flag for special handling
        elif item in active_tournament:
            item.priority_label = "Active Tournament Match"
            item.priority_class = "danger"  # Red/urgent
            item.is_friendly_game = False
        elif item in partially_activated_tournament:
            item.priority_label = "Partially Activated Tournament"
            item.priority_class = "warning"  # Yellow
            item.is_friendly_game = False
        elif item in waiting_validation_tournament:
            item.priority_label = "Waiting Validation Tournament"
            item.priority_class = "info"  # Blue
            item.is_friendly_game = False
        elif item in active_friendly_games:
            item.priority_label = "Active Friendly Game"
            item.priority_class = "success"  # Green
            item.is_friendly_game = True
        elif item in active_friendly_matches:
            item.priority_label = "Active Friendly Match"
            item.priority_class = "success"  # Green
            item.is_friendly_game = False
        elif item in pending_validation_friendly:
            if isinstance(item, FriendlyGame):
                item.priority_label = "Pending Validation Friendly Game"
                item.is_friendly_game = True
            else:
                item.priority_label = "Pending Validation Friendly"
                item.is_friendly_game = False
            item.priority_class = "secondary"  # Gray
    
    # Determine which match is the "recommended" one (highest priority)
    recommended_match = ordered_matches[0] if ordered_matches else None
    
    # If there's only one match/game and it's a friendly game, redirect directly to it
    if len(ordered_matches) == 1 and isinstance(recommended_match, FriendlyGame):
        from django.urls import reverse
        # Check if it needs validation - redirect to validation page
        if hasattr(recommended_match, 'needs_validation') and recommended_match.needs_validation:
            return redirect('friendly_games:validate_result', game_id=recommended_match.id)
        else:
            return redirect('friendly_games:game_detail', game_id=recommended_match.id)
    
    # If the top priority is a friendly game, we should redirect there
    # (This implements the "guess what user wants" behavior)
    if recommended_match and isinstance(recommended_match, FriendlyGame):
        from django.urls import reverse
        # Check if it needs validation - redirect to validation page
        if hasattr(recommended_match, 'needs_validation') and recommended_match.needs_validation:
            return redirect('friendly_games:validate_result', game_id=recommended_match.id)
        else:
            return redirect('friendly_games:game_detail', game_id=recommended_match.id)
    
    return render(request, 'pfc_core/my_matches.html', {
        'matches': ordered_matches,
        'recommended_match': recommended_match,
        'player': player,
        'codename': codename,
        'total_count': len(ordered_matches),
    })
