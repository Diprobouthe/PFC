"""
Smart Router — Decision-State Routing Engine
=============================================

Replaces the old "relevant page" routing with "decision-state page" routing.

Design Principle:
    Skip all intermediary pages that only confirm information the system
    already knows. Route directly to the furthest deterministic page that
    can be reached safely.

Priority Order (CRITICAL — score actions always beat friendly games):
    1.  Score validation (tournament)              → validate_result page
    2a. Tournament active, pregame running          → match_detail (countdown)
    2b. Tournament active, scoreboard exists        → scoreboard_detail (live score)
    2c. Tournament active, no scoreboard            → match_detail (submit from there)
    2d. Score submission (opponent submitted first) → submit_result page
    3.  Friendly game needing YOUR validation       → validate_result page
    4.  Tournament: pending_verification            → activate page (pick players)
    5.  Tournament: pending                         → activate page (pick players)
    6.  Active/live friendly game (player in it)    → game_detail / scoreboard
    7.  Location-aware joinable friendly game       → join page (prefilled/preview)
    8.  Waiting for opponent validation (friendly)  → game_detail page
    9.  Waiting for players / pre-start (friendly)  → game_detail page
    10. Waiting for opponent (tournament, info only) → match_detail page

Freshness:
    Friendly games carry a freshness_score (0-100). Only games with
    freshness_score > 0 (i.e. < 24h old) are considered by the
    location-aware shortcut. Stale games are excluded.

For cases 1-5 the router jumps PAST the intermediary list/detail pages
directly to the decision URL. For cases 6-8 there is no decision to make,
so the info page is the correct destination.
"""

from django.shortcuts import redirect, render
from django.urls import reverse
from django.db.models import Q

from matches.models import Match, MatchActivation, MatchResult, LiveScoreboard
from django.utils import timezone as _tz
from friendly_games.models import (
    PlayerCodename, FriendlyGame, FriendlyGamePlayer, FriendlyGameResult
)
from friendly_games.court_utils import SESSION_PREF_COMPLEX_KEY
from billboard.models import BillboardEntry


# ---------------------------------------------------------------------------
# Priority constants (lower number = higher priority)
# SCORE ACTIONS are always highest priority.
# ---------------------------------------------------------------------------
PRIORITY_TOURNAMENT_WAITING_VALIDATE   = 10   # Score validation (tournament)
PRIORITY_TOURNAMENT_ACTIVE_SUBMIT      = 20   # Score submission (active match)
PRIORITY_FRIENDLY_NEEDS_VALIDATION     = 30   # Friendly game score validation
PRIORITY_TOURNAMENT_NEEDS_ACTIVATION   = 40   # Opponent activated, you haven't
PRIORITY_TOURNAMENT_PENDING            = 50   # Nobody activated yet
PRIORITY_FRIENDLY_ACTIVE               = 55   # Active/live friendly game (player in it)
PRIORITY_FRIENDLY_NEARBY_JOIN          = 62   # Location-aware joinable game
PRIORITY_FRIENDLY_WAITING              = 70   # Waiting for opponent validation
PRIORITY_FRIENDLY_SETUP                = 75   # Waiting for players / pre-start
PRIORITY_TOURNAMENT_WAITING_OPPONENT   = 80   # Waiting for opponent (info only)


def resolve_decision_url(request):
    """
    Main entry point. Determines the single best URL the player should
    be sent to right now, based on all available context.

    Returns:
        - An HttpResponseRedirect to the decision-state page, OR
        - A rendered "no matches" / "not logged in" template.
    """
    # ---- Step 1: Resolve player identity from session ----
    codename = request.session.get('player_codename')
    if not codename:
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

    # ---- Step 2: Resolve team ----
    player_team = player.team
    if not player_team:
        return render(request, 'pfc_core/my_matches.html', {
            'matches': [],
            'no_teams': True,
            'codename': codename,
        })

    # ---- Step 3: Collect ALL candidate items with decision URLs ----
    # Score responsibilities are collected first, but everything goes
    # into the same list so priority ordering is the single authority.
    candidates = []

    # 3a. Tournament matches (includes score validation & submission)
    candidates.extend(_resolve_tournament_matches(player_team))

    # 3b. Friendly games the player is already IN
    candidates.extend(_resolve_friendly_games(player, player_team))

    # 3c. Location-aware friendly game join (only if no score actions exist)
    #     This is the key safety gate: if the player has ANY score-related
    #     responsibility (priority <= 30), we skip the location shortcut
    #     entirely so they handle their responsibilities first.
    has_score_responsibility = any(
        c['priority'] <= PRIORITY_FRIENDLY_NEEDS_VALIDATION
        for c in candidates
    )
    if not has_score_responsibility:
        nearby = _resolve_nearby_friendly_games(request, player)
        if nearby:
            candidates.append(nearby)

    # ---- Step 4: Pick highest priority ----
    if not candidates:
        return render(request, 'pfc_core/my_matches.html', {
            'matches': [],
            'codename': codename,
            'player': player,
            'total_count': 0,
        })

    candidates.sort(key=lambda c: c['priority'])
    best = candidates[0]

    # ---- Step 5: If only one candidate, go straight there ----
    if len(candidates) == 1:
        return redirect(best['url'])

    # ---- Step 6: Multiple candidates — show best + direct links to all others ----
    # Mark the best candidate so the template can highlight it.
    best['is_recommended'] = True
    others = candidates[1:]
    return render(request, 'pfc_core/router_multi.html', {
        'best': best,
        'others': others,
        'total_count': len(candidates),
        'codename': codename,
        'player': player,
    })


# ---------------------------------------------------------------------------
# Court complex context resolution
# ---------------------------------------------------------------------------
def _get_player_court_complex(request, player):
    """
    Determine the player's current court complex from multiple sources.

    Priority order:
        1. Active billboard presence (AT_COURTS) — real-time "I'm here" signal
        2. Session preference — set when player last created a friendly game
        3. Admin default — settings.FRIENDLY_GAME_DEFAULT_COURT_COMPLEX_ID

    Returns:
        - court_complex_id (int) if found
        - None if no context available
    """
    # 1. Check active billboard presence (most reliable — player declared location)
    codename = request.session.get('player_codename')
    if codename:
        billboard_entry = (
            BillboardEntry.objects
            .filter(
                codename=codename,
                action_type='AT_COURTS',
                is_active=True,
            )
            .order_by('-created_at')
            .values_list('court_complex_id', flat=True)
            .first()
        )
        if billboard_entry:
            return billboard_entry

    # 2. Check session preference (set when player created a friendly game)
    pref = request.session.get(SESSION_PREF_COMPLEX_KEY)
    if pref:
        return pref

    # 3. Admin default
    from django.conf import settings
    default = getattr(settings, 'FRIENDLY_GAME_DEFAULT_COURT_COMPLEX_ID', None)
    if default:
        return default

    return None


# ---------------------------------------------------------------------------
# Location-aware friendly game routing (returns a candidate dict, not redirect)
# ---------------------------------------------------------------------------
def _resolve_nearby_friendly_games(request, player):
    """
    Location-aware friendly game routing.

    Determines the player's current court complex from multiple sources
    (in priority order):
        1. Active billboard presence (AT_COURTS) — real-time location
        2. Session preference (preferred_court_complex_id) — last used
        3. Admin default (settings.FRIENDLY_GAME_DEFAULT_COURT_COMPLEX_ID)

    Then looks for joinable FRESH friendly games at that complex that the
    player has NOT yet joined.

    Returns:
        - A candidate dict (with priority + url) if relevant game(s) found
        - None if no nearby joinable fresh games (fall through)

    "Joinable" means:
        - status is WAITING_FOR_PLAYERS or READY
        - the player is NOT already a participant
        - the game is assigned to the player's current court complex
        - the game has freshness_score > 0 (less than 24h old)
    """
    complex_id = _get_player_court_complex(request, player)
    if not complex_id:
        return None

    # Auto-expire unstarted games older than 10 minutes before querying
    # This prevents stale WAITING_FOR_PLAYERS games from polluting routing
    from django.utils import timezone as _tz
    from datetime import timedelta as _td
    _pre_start_cutoff = _tz.now() - _td(minutes=10)
    FriendlyGame.objects.filter(
        status='WAITING_FOR_PLAYERS',
        created_at__lt=_pre_start_cutoff,
    ).update(status='CANCELLED')

    # Find joinable games at this complex
    joinable_games = list(
        FriendlyGame.objects
        .filter(
            court_complex_id=complex_id,
            status__in=['WAITING_FOR_PLAYERS', 'READY'],
        )
        .exclude(
            players__player=player,
        )
        .distinct()
        .order_by('-created_at')
    )

    # Filter to fresh games only (freshness_score > 0 means < 24h old)
    fresh_games = [g for g in joinable_games if g.freshness_score > 0]

    if not fresh_games:
        return None

    # Pick the best game to prefill:
    #   1. Game with the most players already joined (most active / most likely the right one)
    #   2. Tie-break: most recently created
    # This ensures we ALWAYS prefill match_number, even when multiple games exist.
    def _game_sort_key(g):
        player_count = g.players.count()
        return (-player_count, -g.created_at.timestamp())

    best_game = sorted(fresh_games, key=_game_sort_key)[0]
    join_url = reverse('friendly_games:join_game')
    return {
        'priority': PRIORITY_FRIENDLY_NEARBY_JOIN,
        'url': f'{join_url}?match_number={best_game.match_number}',
        'label': f'Join Friendly Game #{best_game.match_number}',
        'match_type': 'friendly_nearby',
    }


# ---------------------------------------------------------------------------
# Friendly game resolution (games the player is already IN)
# ---------------------------------------------------------------------------
def _resolve_friendly_games(player, player_team):
    """Resolve friendly games to their decision-state URLs."""
    candidates = []

    games = FriendlyGame.objects.filter(
        players__player=player
    ).exclude(
        status__in=['COMPLETED', 'CANCELLED', 'EXPIRED']
    ).distinct()

    for game in games:
        # Check if game needs validation from THIS player
        if game.status == 'PENDING_VALIDATION' and hasattr(game, 'result'):
            try:
                participation = FriendlyGamePlayer.objects.get(
                    game=game, player=player
                )
                result = game.result
                if result.submitted_by_team != participation.team:
                    # Other team submitted → player must validate
                    candidates.append({
                        'priority': PRIORITY_FRIENDLY_NEEDS_VALIDATION,
                        'url': reverse('friendly_games:validate_result',
                                       kwargs={'game_id': game.id}),
                        'label': 'Validate Friendly Game Result',
                        'match_type': 'friendly',
                    })
                    continue
            except FriendlyGamePlayer.DoesNotExist:
                pass

        if game.status == 'ACTIVE':
            # Route to live scoreboard if available, so player enters live score mode
            try:
                scoreboard = game.live_scoreboard
                active_url = reverse('scoreboard_detail',
                                     kwargs={'scoreboard_id': scoreboard.id})
            except Exception:
                active_url = reverse('friendly_games:game_detail',
                                     kwargs={'game_id': game.id})
            candidates.append({
                'priority': PRIORITY_FRIENDLY_ACTIVE,
                'url': active_url,
                'label': 'Active Friendly Game — Live Score',
                'match_type': 'friendly',
            })
        elif game.status == 'PENDING_VALIDATION':
            # Player's team already submitted — just info
            candidates.append({
                'priority': PRIORITY_FRIENDLY_WAITING,
                'url': reverse('friendly_games:game_detail',
                               kwargs={'game_id': game.id}),
                'label': 'Waiting for Opponent Validation',
                'match_type': 'friendly',
            })
        elif game.status in ['READY', 'WAITING_FOR_PLAYERS']:
            candidates.append({
                'priority': PRIORITY_FRIENDLY_SETUP,
                'url': reverse('friendly_games:game_detail',
                               kwargs={'game_id': game.id}),
                'label': 'Friendly Game — Waiting for Players',
                'match_type': 'friendly',
            })

    return candidates


# ---------------------------------------------------------------------------
# Tournament match resolution
# ---------------------------------------------------------------------------
def _resolve_tournament_matches(player_team):
    """Resolve tournament matches to their decision-state URLs."""
    candidates = []

    matches = Match.objects.filter(
        Q(team1=player_team) | Q(team2=player_team)
    ).exclude(
        status__iexact='completed'
    ).exclude(
        status__iexact='cancelled'
    ).select_related(
        'team1', 'team2', 'tournament', 'court'
    ).prefetch_related('activations')

    for match in matches:
        status = match.status.lower()
        team_id = player_team.id

        if status == 'active':
            # Check if this team already submitted a result
            try:
                result = match.result
                if result.submitted_by_id == team_id:
                    # We submitted, waiting for opponent to validate
                    candidates.append({
                        'priority': PRIORITY_TOURNAMENT_WAITING_OPPONENT,
                        'url': reverse('match_detail',
                                       kwargs={'match_id': match.id}),
                        'label': 'Waiting for Score Validation',
                        'match_type': 'tournament',
                    })
                else:
                    # Opponent submitted, we haven't — route to submit
                    candidates.append({
                        'priority': PRIORITY_TOURNAMENT_ACTIVE_SUBMIT,
                        'url': reverse('match_submit_result',
                                       kwargs={'match_id': match.id,
                                               'team_id': team_id}),
                        'label': 'Submit Match Score',
                        'match_type': 'tournament',
                    })
            except MatchResult.DoesNotExist:
                # No result yet — follow the same flow as friendly games:
                #   1. Pre-game countdown still running → match_detail (countdown page)
                #   2. Countdown over, live scoreboard exists → scoreboard_detail
                #   3. Countdown over, no scoreboard → match_detail (submit from there)
                pregame_over = True
                if match.start_time and match.tournament:
                    pregame_secs = (match.tournament.pregame_countdown_minutes or 3) * 60
                    elapsed = (_tz.now() - match.start_time).total_seconds()
                    if elapsed < pregame_secs:
                        pregame_over = False

                if not pregame_over:
                    # Still in pre-game window — show countdown on match_detail
                    candidates.append({
                        'priority': PRIORITY_TOURNAMENT_ACTIVE_SUBMIT,
                        'url': reverse('match_detail',
                                       kwargs={'match_id': match.id}),
                        'label': 'Match Starting — Find Your Court',
                        'match_type': 'tournament',
                    })
                else:
                    # Pre-game over — route to live scoreboard if one exists,
                    # otherwise fall back to match_detail (not submit directly)
                    try:
                        scoreboard = match.live_scoreboard
                        if scoreboard.is_active:
                            candidates.append({
                                'priority': PRIORITY_TOURNAMENT_ACTIVE_SUBMIT,
                                'url': reverse('scoreboard_detail',
                                               kwargs={'scoreboard_id': scoreboard.id}),
                                'label': 'Active Match — Live Score',
                                'match_type': 'tournament',
                            })
                        else:
                            # Scoreboard exists but inactive — go to match_detail
                            # so player can navigate to submit from there
                            candidates.append({
                                'priority': PRIORITY_TOURNAMENT_ACTIVE_SUBMIT,
                                'url': reverse('match_detail',
                                               kwargs={'match_id': match.id}),
                                'label': 'Active Match — Submit Score',
                                'match_type': 'tournament',
                            })
                    except LiveScoreboard.DoesNotExist:
                        # No live scoreboard — go to match_detail so player
                        # sees the active state and can submit from there
                        candidates.append({
                            'priority': PRIORITY_TOURNAMENT_ACTIVE_SUBMIT,
                            'url': reverse('match_detail',
                                           kwargs={'match_id': match.id}),
                            'label': 'Active Match — Submit Score',
                            'match_type': 'tournament',
                        })

        elif status == 'waiting_validation':
            # Check who submitted the result
            try:
                result = match.result
                if result.submitted_by_id == team_id:
                    # We submitted — waiting for opponent → info only
                    candidates.append({
                        'priority': PRIORITY_TOURNAMENT_WAITING_OPPONENT,
                        'url': reverse('match_detail',
                                       kwargs={'match_id': match.id}),
                        'label': 'Waiting for Opponent to Validate',
                        'match_type': 'tournament',
                    })
                else:
                    # Opponent submitted — we need to validate
                    candidates.append({
                        'priority': PRIORITY_TOURNAMENT_WAITING_VALIDATE,
                        'url': reverse('match_validate_result',
                                       kwargs={'match_id': match.id,
                                               'team_id': team_id}),
                        'label': 'Validate Match Score',
                        'match_type': 'tournament',
                    })
            except MatchResult.DoesNotExist:
                # Status says waiting_validation but no result — edge case
                candidates.append({
                    'priority': PRIORITY_TOURNAMENT_WAITING_VALIDATE,
                    'url': reverse('match_detail',
                                   kwargs={'match_id': match.id}),
                    'label': 'Match Waiting Validation',
                    'match_type': 'tournament',
                })

        elif status in ('pending_verification', 'pending verification'):
            # Check if OUR team already activated
            our_activation = match.activations.filter(team_id=team_id).exists()
            if our_activation:
                candidates.append({
                    'priority': PRIORITY_TOURNAMENT_WAITING_OPPONENT,
                    'url': reverse('match_detail',
                                   kwargs={'match_id': match.id}),
                    'label': 'Waiting for Opponent Activation',
                    'match_type': 'tournament',
                })
            else:
                candidates.append({
                    'priority': PRIORITY_TOURNAMENT_NEEDS_ACTIVATION,
                    'url': reverse('match_activate',
                                   kwargs={'match_id': match.id,
                                           'team_id': team_id}),
                    'label': 'Select Players & Activate Match',
                    'match_type': 'tournament',
                })

        elif status == 'pending':
            candidates.append({
                'priority': PRIORITY_TOURNAMENT_PENDING,
                'url': reverse('match_activate',
                               kwargs={'match_id': match.id,
                                       'team_id': team_id}),
                'label': 'Select Players & Start Match',
                'match_type': 'tournament',
            })

    return candidates


# ---------------------------------------------------------------------------
# List view (fallback — accessible via separate URL)
# ---------------------------------------------------------------------------
def my_matches_list(request):
    """
    Full list view of all active matches. This is the NON-smart version
    that shows everything. Accessible if the user explicitly wants to
    browse all their matches rather than being routed to the top one.
    """
    codename = request.session.get('player_codename')
    if not codename:
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

    player_team = player.team
    if not player_team:
        return render(request, 'pfc_core/my_matches.html', {
            'matches': [],
            'no_teams': True,
            'codename': codename,
        })

    # Collect all candidates with their resolved URLs
    candidates = []
    candidates.extend(_resolve_tournament_matches(player_team))
    candidates.extend(_resolve_friendly_games(player, player_team))
    candidates.sort(key=lambda c: c['priority'])

    return render(request, 'pfc_core/my_matches_list.html', {
        'candidates': candidates,
        'codename': codename,
        'player': player,
        'total_count': len(candidates),
    })


# ---------------------------------------------------------------------------
# JSON endpoint — session-aware "where should I be?" for the universal poller
# ---------------------------------------------------------------------------
from django.http import JsonResponse as _JsonResponse

def resolve_next_url(request):
    """
    Pure URL resolver — same logic as resolve_decision_url() but returns
    a JSON response instead of an HttpResponseRedirect/render.

    Used by the universal match-page poller so every participant
    automatically moves to their correct next state whenever the match
    status changes, without duplicating routing rules in page JS.

    Response shape:
        {
            "authenticated": true/false,
            "next_url": "/matches/validate-result/3/12/" | null,
            "label": "Validate Match Score" | null,
            "priority": 10 | null
        }

    The poller compares next_url to window.location.pathname.
    If they differ (and next_url is not null), it navigates there.
    """
    codename = request.session.get('player_codename')
    if not codename:
        return _JsonResponse({'authenticated': False, 'next_url': None, 'label': None, 'priority': None})

    try:
        player_codename = PlayerCodename.objects.get(codename=codename)
        player = player_codename.player
    except PlayerCodename.DoesNotExist:
        return _JsonResponse({'authenticated': False, 'next_url': None, 'label': None, 'priority': None})

    player_team = player.team
    if not player_team:
        return _JsonResponse({'authenticated': True, 'next_url': None, 'label': 'No team', 'priority': None})

    candidates = []
    candidates.extend(_resolve_tournament_matches(player_team))
    candidates.extend(_resolve_friendly_games(player, player_team))

    has_score_responsibility = any(
        c['priority'] <= PRIORITY_FRIENDLY_NEEDS_VALIDATION
        for c in candidates
    )
    if not has_score_responsibility:
        nearby = _resolve_nearby_friendly_games(request, player)
        if nearby:
            candidates.append(nearby)

    if not candidates:
        return _JsonResponse({'authenticated': True, 'next_url': None, 'label': 'No active matches', 'priority': None})

    candidates.sort(key=lambda c: c['priority'])
    best = candidates[0]
    return _JsonResponse({
        'authenticated': True,
        'next_url': best['url'],
        'label': best.get('label', ''),
        'priority': best['priority'],
    })
