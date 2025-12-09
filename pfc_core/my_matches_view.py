"""
View for showing player's active matches with priority ordering.
Accessed via the "PFC" button in the top navigation bar.
"""
from django.shortcuts import render
from django.db.models import Q
from matches.models import Match
from friendly_games.models import PlayerCodename


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
    
    # Build query for matches involving player's team
    # Exclude completed matches (handle both lowercase and title case)
    matches_query = Match.objects.filter(
        Q(team1=player_team) | Q(team2=player_team)
    ).exclude(
        Q(status__iexact='completed')  # Case-insensitive comparison
    ).select_related(
        'team1', 'team2', 'tournament', 'court'
    ).distinct()
    
    # Separate matches by category and priority
    active_tournament = []
    partially_activated_tournament = []
    waiting_validation_tournament = []
    active_friendly = []
    pending_validation_friendly = []
    
    for match in matches_query:
        is_tournament = match.tournament is not None
        status_lower = match.status.lower()  # Normalize to lowercase for comparison
        
        if status_lower == 'active':
            if is_tournament:
                active_tournament.append(match)
            else:
                active_friendly.append(match)
        elif status_lower == 'partially activated' or status_lower == 'partially_activated':
            if is_tournament:
                partially_activated_tournament.append(match)
        elif status_lower in ['pending', 'pending verification', 'pending_verification', 'waiting_validation']:
            if is_tournament:
                waiting_validation_tournament.append(match)
            else:
                pending_validation_friendly.append(match)
    
    # Combine in priority order
    ordered_matches = (
        active_tournament +
        partially_activated_tournament +
        waiting_validation_tournament +
        active_friendly +
        pending_validation_friendly
    )
    
    # Add priority labels for display
    for match in ordered_matches:
        if match in active_tournament:
            match.priority_label = "Active Tournament Match"
            match.priority_class = "danger"  # Red/urgent
        elif match in partially_activated_tournament:
            match.priority_label = "Partially Activated Tournament"
            match.priority_class = "warning"  # Yellow
        elif match in waiting_validation_tournament:
            match.priority_label = "Waiting Validation Tournament"
            match.priority_class = "info"  # Blue
        elif match in active_friendly:
            match.priority_label = "Active Friendly Match"
            match.priority_class = "success"  # Green
        elif match in pending_validation_friendly:
            match.priority_label = "Pending Validation Friendly"
            match.priority_class = "secondary"  # Gray
    
    # Determine which match is the "recommended" one (highest priority)
    recommended_match = ordered_matches[0] if ordered_matches else None
    
    return render(request, 'pfc_core/my_matches.html', {
        'matches': ordered_matches,
        'recommended_match': recommended_match,
        'player': player,
        'codename': codename,
        'total_count': len(ordered_matches),
    })
