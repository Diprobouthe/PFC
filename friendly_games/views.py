from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from .views_submit_score_list import submit_score_list
from django.http import JsonResponse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.db import transaction
from django.db.models import Q
from django.views.decorators.http import require_GET, require_POST
from django.urls import reverse
from datetime import timedelta
import json
import logging
import random
from teams.models import Player, Team
from .models import FriendlyGame, FriendlyGamePlayer, PlayerCodename, FriendlyGameStatistics
from pfc_core.session_utils import CodenameSessionManager
from .court_utils import resolve_court_assignment, get_court_context_for_form, courts_for_complex_json
from .presence_utils import register_friendly_game_players_at_court, deactivate_friendly_game_presence
from courts.timezone_utils import get_court_local_now
from pfc_events.signals import notify_game_state_changed

logger = logging.getLogger(__name__)

MAX_FRIENDLY_TEAM_SIZE = 3


def _session_creator_player(request, game):
    """Return the authenticated creator for this game, otherwise None."""
    session_codename = CodenameSessionManager.get_logged_in_codename(request)
    if not session_codename or not game.creator_player_id:
        return None
    try:
        if game.creator_player.codename_profile.codename == session_codename.upper():
            return game.creator_player
    except PlayerCodename.DoesNotExist:
        return None
    return None


def _verified_friendly_qr_player_ids(request):
    """Return the server-side QR-resolved player ids for the current setup session."""
    raw_ids = request.session.get('friendly_qr_scanned_player_ids', [])
    if not isinstance(raw_ids, list):
        return set()
    verified_ids = set()
    for raw_id in raw_ids:
        try:
            verified_ids.add(int(raw_id))
        except (TypeError, ValueError):
            continue
    return verified_ids


def _eligible_friendly_court_players(court_complex):
    """Return players who explicitly opted into Friendly setup at this complex.

    Consent is taken only from current manual AT_COURTS presence.  It is never
    inferred from a team roster, game-generated presence, or a prior preference.
    Players actively involved in another Friendly or tournament Match are removed.
    """
    if not court_complex:
        return []
    from billboard.models import BillboardEntry
    from billboard.presence_prefs import UserPresencePrefs
    from matches.models_participant import TeamMatchParticipant

    local_cutoff = get_court_local_now(court_complex) - timedelta(hours=2)
    entries = BillboardEntry.objects.filter(
        action_type='AT_COURTS',
        court_complex=court_complex,
        presence_source=BillboardEntry.PRESENCE_SOURCE_MANUAL,
        is_active=True,
        created_at__gte=local_cutoff,
    ).order_by('-created_at')
    # A player can have historical/manual re-check-ins.  The newest valid
    # presence entry is authoritative for the current session at this complex.
    codenames = []
    seen_codenames = set()
    for entry in entries:
        codename = (entry.codename or '').upper()
        if codename and codename not in seen_codenames:
            seen_codenames.add(codename)
            codenames.append(codename)
    if not codenames:
        return []
    opted_in_codenames = set(UserPresencePrefs.objects.filter(
        codename__in=codenames,
        available_for_friendly=True,
    ).values_list('codename', flat=True))
    if not opted_in_codenames:
        return []

    players = list(Player.objects.filter(
        codename_profile__codename__in=opted_in_codenames,
    ).select_related('profile', 'codename_profile'))
    player_ids = [player.id for player in players]
    active_friendly_ids = set(FriendlyGamePlayer.objects.filter(
        player_id__in=player_ids,
        game__status__in={'ACTIVE', 'PENDING_VALIDATION'},
    ).values_list('player_id', flat=True))
    active_match_ids = set(TeamMatchParticipant.objects.filter(
        player_id__in=player_ids,
        played=True,
        match__status__in={'active', 'pending_verification', 'waiting_validation'},
    ).values_list('player_id', flat=True))
    blocked_ids = active_friendly_ids | active_match_ids
    return sorted(
        (player for player in players if player.id not in blocked_ids),
        key=lambda player: (player.name or '').casefold(),
    )


@require_GET
def available_court_players_api(request):
    """Return current, opted-in, non-active players for Friendly creator setup."""
    if not CodenameSessionManager.get_logged_in_codename(request):
        return JsonResponse({'ok': False, 'error': 'Sign in before viewing players at courts.'}, status=401)
    try:
        court_complex_id = int(request.GET.get('court_complex_id', ''))
    except (TypeError, ValueError):
        return JsonResponse({'ok': False, 'error': 'Select a Court Complex first.'}, status=400)
    from courts.models import CourtComplex
    court_complex = CourtComplex.objects.filter(pk=court_complex_id).first()
    if not court_complex:
        return JsonResponse({'ok': False, 'error': 'Court Complex not found.'}, status=404)
    players = _eligible_friendly_court_players(court_complex)
    return JsonResponse({
        'ok': True,
        'court_complex': {'id': court_complex.id, 'name': court_complex.name},
        'players': [
            {
                'id': player.id,
                'name': player.name,
                'position': _friendly_position_for_player(player),
                'rating': _friendly_rating_for_player(player),
            }
            for player in players
        ],
    })


def _friendly_position_for_player(player):
    """Map an existing preferred profile position to the Friendly Game choices."""
    try:
        preferred = (player.profile.preferred_position or '').lower()
    except Exception:
        preferred = ''
    return {
        'pointer': 'POINTEUR',
        'tirer': 'TIRER',
        'milieu': 'MILIEU',
        'flex': 'MILIEU',
    }.get(preferred, 'MILIEU')


def _friendly_rating_for_player(player):
    """Use the existing PlayerProfile rating, with its existing default as fallback."""
    try:
        return float(player.profile.value)
    except Exception:
        return 100.0


def _balanced_friendly_assignments(players, existing_black, existing_white):
    """Return QR-verified players assigned by rating first, then position balance.

    The function keeps side sizes as even as possible and never exceeds the existing
    three-player Friendly Game capacity. It only decides pre-start setup placement.
    """
    black = list(existing_black)
    white = list(existing_white)
    ordered = sorted(players, key=lambda player: (-_friendly_rating_for_player(player), player.id))

    for player in ordered:
        candidates = []
        for team_name, team_players, other_players in (
            ('BLACK', black, white),
            ('WHITE', white, black),
        ):
            if len(team_players) >= MAX_FRIENDLY_TEAM_SIZE:
                continue
            # Do not create a count imbalance greater than one while either side has room.
            if len(team_players) + 1 > len(other_players) + 1:
                continue
            player_rating = _friendly_rating_for_player(player)
            rating_gap = abs((sum(_friendly_rating_for_player(p) for p in team_players) + player_rating) - sum(_friendly_rating_for_player(p) for p in other_players))
            position = _friendly_position_for_player(player)
            position_gap = abs(sum(_friendly_position_for_player(p) == position for p in team_players) + 1 - sum(_friendly_position_for_player(p) == position for p in other_players))
            candidates.append((rating_gap, position_gap, len(team_players), team_name))
        if not candidates:
            raise ValueError('No places remain for the scanned players.')
        chosen_team = min(candidates)[3]
        (black if chosen_team == 'BLACK' else white).append(player)
    return black, white


def _random_friendly_assignments(players, existing_black, existing_white):
    """Distribute scanned players at random while keeping sides as even as possible."""
    black = list(existing_black)
    white = list(existing_white)
    shuffled = list(players)
    random.shuffle(shuffled)
    for player in shuffled:
        available = []
        if len(black) < MAX_FRIENDLY_TEAM_SIZE:
            available.append(('BLACK', black))
        if len(white) < MAX_FRIENDLY_TEAM_SIZE:
            available.append(('WHITE', white))
        if not available:
            raise ValueError('No places remain for the scanned players.')
        smallest_size = min(len(team_players) for _, team_players in available)
        eligible = [(team_name, team_players) for team_name, team_players in available if len(team_players) == smallest_size]
        team_name, team_players = random.choice(eligible)
        team_players.append(player)
    return black, white


def game_preview_api(request):
    """
    API endpoint to preview game details by match number.
    Returns game information and team composition for the join UI.
    """
    if request.method != 'GET':
        return JsonResponse({'error': 'Only GET requests allowed'}, status=405)
    
    match_number = request.GET.get('match_number', '').strip()
    
    if not match_number:
        return JsonResponse({'error': 'Match number is required'}, status=400)
    
    try:
        # Find the game by match number
        game = FriendlyGame.objects.get(match_number=match_number)
        
        # Check if game is expired
        if game.is_expired():
            game.status = 'EXPIRED'
            game.save()
            deactivate_friendly_game_presence(game)
            return JsonResponse({
                'error': 'expired',
                'message': f'Match #{match_number} has expired.'
            }, status=400)
        
        # Check if game is still accepting players
        if game.status not in ['WAITING_FOR_PLAYERS', 'DRAFT']:
            return JsonResponse({
                'error': 'not_accepting',
                'message': f'Match #{match_number} is no longer accepting players.'
            }, status=400)
        
        # Get team composition
        players = game.players.all().select_related('player', 'player__team')
        
        black_team = []
        white_team = []
        
        for game_player in players:
            player_info = {
                'name': game_player.player.name,
                'position': game_player.position,
                'team_name': game_player.player.team.name if game_player.player.team else 'No Team',
                'codename_verified': game_player.codename_verified
            }
            
            if game_player.team == 'BLACK':
                black_team.append(player_info)
            else:
                white_team.append(player_info)
        
        # Calculate availability
        black_available = 3 - len(black_team)
        white_available = 3 - len(white_team)
        
        return JsonResponse({
            'success': True,
            'game': {
                'id': game.id,
                'name': game.name,
                'match_number': game.match_number,
                'status': game.get_status_display(),
                'target_score': game.target_score,
                'created_at': game.created_at.strftime('%b %d, %Y %H:%M'),
            },
            'teams': {
                'black': {
                    'players': black_team,
                    'available_slots': black_available,
                    'is_full': black_available == 0
                },
                'white': {
                    'players': white_team,
                    'available_slots': white_available,
                    'is_full': white_available == 0
                }
            }
        })
        
    except FriendlyGame.DoesNotExist:
        return JsonResponse({
            'error': 'not_found',
            'message': f'No game found with match number #{match_number}'
        }, status=404)
    except Exception as e:
        logger.error(f"Error in game_preview_api: {e}")
        return JsonResponse({
            'error': 'server_error',
            'message': 'An error occurred while fetching game details'
        }, status=500)


def create_game(request):
    """
    Create a new friendly game with player selection and codename verification.
    STRICT REQUIREMENT: Creator must provide a valid codename
    """
    # Get logged-in user's codename from session
    session_codename = CodenameSessionManager.get_logged_in_codename(request)
    
    if request.method == 'POST':
        # Handle game creation logic here
        game_name = request.POST.get('game_name', 'Friendly Game')
        creator_codename = request.POST.get('creator_codename', '').strip()
        creator_position = request.POST.get('creator_position', '').strip()
        black_team_players = request.POST.get('black_team_players', '[]')
        white_team_players = request.POST.get('white_team_players', '[]')
        
        # STRICT REQUIREMENT: Creator must provide a valid codename
        if not creator_codename:
            messages.error(request, 'You must provide your codename to create a game.')
            return render(request, 'friendly_games/create_game.html', {
                'session_codename': session_codename,
                'teams': Team.objects.filter(
                    is_archived=False, is_tournament_temp=False,
                    parent_team__isnull=True,
                ).prefetch_related('players'),
            })
        
        # Validate creator codename
        try:
            creator_player_codename = PlayerCodename.objects.get(codename=creator_codename.upper())
            creator_player = creator_player_codename.player
        except PlayerCodename.DoesNotExist:
            messages.error(request, f'Invalid codename "{creator_codename}". Please provide a correct codename to create a game.')
            return render(request, 'friendly_games/create_game.html', {
                'session_codename': session_codename,
                'teams': Team.objects.filter(
                    is_archived=False, is_tournament_temp=False,
                    parent_team__isnull=True,
                ).prefetch_related('players'),
            })
        
        try:
            setup_mode = request.POST.get('setup_mode', 'manual').strip().lower()
            if setup_mode not in {'manual', 'random', 'balanced'}:
                raise ValueError('Invalid Friendly Game setup mode.')

            # QR identity is authoritative server-side. Client-side selections can
            # only choose among players scanned in this browser session.
            verified_qr_ids = _verified_friendly_qr_player_ids(request)
            manual_assignments = json.loads(request.POST.get('manual_assignments', '[]'))
            scanned_ids = json.loads(request.POST.get('scanned_player_ids', '[]'))
            court_player_ids = json.loads(request.POST.get('court_player_ids', '[]'))

            # Resolve the selected Court Complex before validating court-player consent.
            complex_id = request.POST.get('court_complex_id') or None
            court_id = request.POST.get('court_id') or None
            try:
                complex_id = int(complex_id) if complex_id else None
            except (ValueError, TypeError):
                complex_id = None
            try:
                court_id = int(court_id) if court_id else None
            except (ValueError, TypeError):
                court_id = None
            assigned_complex, assigned_court = resolve_court_assignment(
                request, complex_id=complex_id, court_id=court_id
            )

            if not isinstance(court_player_ids, list):
                raise ValueError('Invalid Players at Courts selection data.')
            selected_court_ids = []
            for raw_id in court_player_ids:
                try:
                    player_id = int(raw_id)
                except (TypeError, ValueError):
                    raise ValueError('Invalid player selected from courts.')
                if player_id not in selected_court_ids:
                    selected_court_ids.append(player_id)
            if selected_court_ids and not assigned_complex:
                raise ValueError('Select a Court Complex before adding players at courts.')
            eligible_court_ids = {
                player.id for player in _eligible_friendly_court_players(assigned_complex)
            } if assigned_complex else set()
            if any(player_id not in eligible_court_ids for player_id in selected_court_ids):
                raise ValueError('One or more selected court players are no longer available for this Friendly Game.')

            # The existing creator-included behavior remains the default.  The
            # explicit court-player setup may choose to exclude the creator.
            include_creator = request.POST.get('include_creator', '1') != '0'
            if not selected_court_ids:
                include_creator = True
            authorized_sources = {player_id: 'COURT' for player_id in selected_court_ids}
            black_player_ids = ([{'id': creator_player.id, 'source': 'CREATOR'}] if include_creator else [])
            white_player_ids = []
            seen_ids = {creator_player.id} if include_creator else set()

            if setup_mode == 'manual':
                if not isinstance(manual_assignments, list):
                    raise ValueError('Invalid manual QR assignment data.')
                for assignment in manual_assignments:
                    if not isinstance(assignment, dict):
                        raise ValueError('Invalid manual QR assignment data.')
                    try:
                        player_id = int(assignment.get('id'))
                    except (TypeError, ValueError):
                        raise ValueError('Invalid scanned player.')
                    team = assignment.get('team')
                    if team not in {'BLACK', 'WHITE'} or player_id == creator_player.id or player_id in seen_ids:
                        continue
                    source = authorized_sources.get(player_id)
                    if player_id in verified_qr_ids:
                        source = 'QR'
                    if source not in {'QR', 'COURT'}:
                        raise ValueError('Every creator-assigned player must be scanned by QR or selected from current court availability.')
                    destination = black_player_ids if team == 'BLACK' else white_player_ids
                    if len(destination) >= MAX_FRIENDLY_TEAM_SIZE:
                        raise ValueError(f'{team.title()} team is full.')
                    destination.append({'id': player_id, 'source': source})
                    seen_ids.add(player_id)
            else:
                if not isinstance(scanned_ids, list):
                    raise ValueError('Invalid scanned participant data.')
                # For Random and Balanced, this submitted list is the one and
                # only participant source. The UI inserts the creator as a normal
                # protected You entry when checked and removes that entry when
                # unchecked; no creator flag augments the list here.
                participant_ids = []
                for raw_id in list(scanned_ids) + selected_court_ids:
                    try:
                        player_id = int(raw_id)
                    except (TypeError, ValueError):
                        raise ValueError('Invalid selected player.')
                    if player_id in participant_ids:
                        continue
                    if player_id == creator_player.id:
                        participant_ids.append(player_id)
                        continue
                    source = authorized_sources.get(player_id)
                    if player_id in verified_qr_ids:
                        source = 'QR'
                    if source not in {'QR', 'COURT'}:
                        raise ValueError('Every participant must be scanned by QR or selected from current court availability.')
                    authorized_sources[player_id] = source
                    participant_ids.append(player_id)
                if len(participant_ids) > MAX_FRIENDLY_TEAM_SIZE * 2:
                    raise ValueError('A Friendly Game can contain at most six players.')

                players_by_id = {
                    player.id: player
                    for player in Player.objects.filter(id__in=participant_ids).select_related('profile')
                }
                if len(players_by_id) != len(participant_ids):
                    raise ValueError('One or more selected players could not be found.')
                allocation_players = [players_by_id[player_id] for player_id in participant_ids]
                if setup_mode == 'random':
                    black_players, white_players = _random_friendly_assignments(allocation_players, [], [])
                else:
                    black_players, white_players = _balanced_friendly_assignments(allocation_players, [], [])
                black_player_ids = [
                    {'id': player.id, 'source': ('CREATOR' if player.id == creator_player.id else authorized_sources[player.id])}
                    for player in black_players
                ]
                white_player_ids = [
                    {'id': player.id, 'source': ('CREATOR' if player.id == creator_player.id else authorized_sources[player.id])}
                    for player in white_players
                ]
            
            # ── Timed game ───────────────────────────────────────────────────
            is_timed = request.POST.get('is_timed') == '1'
            time_limit_minutes = None
            if is_timed:
                try:
                    time_limit_minutes = int(request.POST.get('time_limit_minutes', 0))
                    if time_limit_minutes <= 0:
                        is_timed = False
                        time_limit_minutes = None
                except (ValueError, TypeError):
                    is_timed = False

            # Create the game
            game = FriendlyGame.objects.create(
                name=game_name,
                court_complex=assigned_complex,
                court=assigned_court,
                is_timed=is_timed,
                time_limit_minutes=time_limit_minutes,
                creator_player=creator_player,  # track who created the game
            )
            
            def _parse_player_entry(entry):
                if not isinstance(entry, dict):
                    raise ValueError('Invalid QR player assignment.')
                try:
                    return int(entry.get('id')), str(entry.get('source', ''))
                except (TypeError, ValueError):
                    raise ValueError('Invalid participant assignment.')

            for team, entries in (('BLACK', black_player_ids), ('WHITE', white_player_ids)):
                for entry in entries:
                    player_id, source = _parse_player_entry(entry)
                    try:
                        player = Player.objects.select_related('profile').get(id=player_id)
                    except Player.DoesNotExist:
                        raise ValueError('A selected player could not be found.')

                    if player.id == creator_player.id and source == 'CREATOR':
                        position = creator_position.upper() if creator_position else 'MILIEU'
                        codename_verified = True
                        provided_codename = creator_codename.upper()
                    elif source in {'QR', 'COURT'}:
                        position = _friendly_position_for_player(player)
                        # Both existing QR resolution and current court-presence
                        # consent resolve the player server-side before creation.
                        codename_verified = True
                        provided_codename = source
                    else:
                        raise ValueError('Creator player assignment requires QR or current court-presence authorization.')

                    FriendlyGamePlayer.objects.create(
                        game=game,
                        player=player,
                        team=team,
                        position=position,
                        provided_codename=provided_codename,
                        codename_verified=codename_verified,
                    )
            
            # Update game validation status
            game.update_validation_status()
            
            # Create success message with creator validation info
            total_players = len(black_player_ids) + len(white_player_ids)
            success_msg = _('Friendly game "%(game_name)s" created successfully with %(total_players)s players!') % {
                'game_name': game.name,
                'total_players': total_players,
            }
            
            if creator_player:
                success_msg += ' ' + _('Creator validated as %(player_name)s.') % {
                    'player_name': creator_player.name,
                }
            elif creator_codename:
                success_msg += ' ' + _('Creator codename "%(codename)s" not found - no validation.') % {
                    'codename': creator_codename,
                }
            
            success_msg += ' ' + _('Match Number: %(match_number)s') % {
                'match_number': game.match_number,
            }
            
            messages.success(request, success_msg)
            return redirect('friendly_games:game_detail', game_id=game.id)
            
        except json.JSONDecodeError:
            messages.error(request, 'Invalid player selection data')
        except Exception as e:
            messages.error(request, f'Error creating game: {str(e)}')
    
    # Get selectable teams for the player-selection UI.
    # Include all non-archived, non-temp, top-level teams regardless of profile type.
    teams = Team.objects.filter(
        is_archived=False,
        is_tournament_temp=False,
        parent_team__isnull=True,
    ).prefetch_related('players')
    
    # Auto-detect logged-in player and add to black team
    auto_selected_player = None
    if session_codename:
        try:
            # Find player by codename
            player_codename = PlayerCodename.objects.get(codename=session_codename)
            auto_selected_player = player_codename.player
        except PlayerCodename.DoesNotExist:
            # If no exact codename match, try to find by name similarity
            try:
                auto_selected_player = Player.objects.get(name__iexact=session_codename)
            except Player.DoesNotExist:
                pass
    
    court_context = get_court_context_for_form(request)

    context = {
        'teams': teams,
        'team_name': request.session.get('team_name', 'Guest'),
        'auto_selected_player': auto_selected_player,
        'session_codename': session_codename,
    }
    context.update(court_context)

    return render(request, 'friendly_games/create_game.html', context)


def game_detail(request, game_id):
    """Display details of a friendly game"""
    from pfc_core.qr_action_auth import get_qr_action_player, get_qr_action_token
    game = get_object_or_404(FriendlyGame, id=game_id)
    players = game.players.all().select_related('player', 'player__team')
    _qr_action_player = get_qr_action_player(request)

    # Auto-redirect the opposing team to validation when a result is pending.
    if hasattr(game, 'result') and game.result.is_pending_validation():
        from pfc_core.session_utils import CodenameSessionManager
        session_codename = ''
        if _qr_action_player:
            try:
                session_codename = _qr_action_player.codename_profile.codename
            except Exception:
                session_codename = ''
        if not session_codename:
            session_codename = CodenameSessionManager.get_logged_in_codename(request)
        if session_codename:
            session_player_team = None
            for gp in players:
                try:
                    if gp.player.codename_profile.codename == session_codename:
                        session_player_team = gp.team
                        break
                except Exception:
                    pass
            # Session player is on the opposing (validating) team
            if session_player_team and session_player_team != game.result.submitted_by_team:
                return redirect('friendly_games:validate_result', game_id=game.id)

    # Detect session player's team for the polling JS
    # Also compute is_creator and is_joined for the pre-start button logic
    session_team = None
    is_creator = False
    is_joined = False
    from pfc_core.session_utils import CodenameSessionManager
    _sc = ''
    if _qr_action_player:
        try:
            _sc = _qr_action_player.codename_profile.codename
        except Exception:
            _sc = ''
    if not _sc:
        _sc = CodenameSessionManager.get_logged_in_codename(request)
    if _sc:
        _sc_upper = _sc.upper()
        for gp in players:
            try:
                if gp.player.codename_profile.codename == _sc_upper:
                    session_team = gp.team  # 'BLACK' or 'WHITE'
                    is_joined = True
                    # Check if this player is the creator
                    if game.creator_player and game.creator_player.id == gp.player.id:
                        is_creator = True
                    break
            except Exception:
                pass
        # If no match via codename_profile, check creator by codename directly
        if not is_joined and game.creator_player:
            try:
                if game.creator_player.codename_profile.codename == _sc_upper:
                    is_creator = True
            except Exception:
                pass

    context = {
        'game': game,
        'players': players,
        'session_team': session_team or '',
        'is_creator': is_creator,
        'is_joined': is_joined,
        'qr_action_token': get_qr_action_token(request),
    }

    return render(request, 'friendly_games/game_detail.html', context)


@require_POST
def creator_assign_players(request, game_id):
    """Add QR-scanned existing players during the Friendly pre-start setup.

    This is intentionally separate from normal joining: it never removes or moves a
    player who already joined their own side, and it only works for the game creator
    while the game still accepts players.
    """
    game = get_object_or_404(FriendlyGame, id=game_id)
    if game.status not in {'WAITING_FOR_PLAYERS', 'DRAFT'}:
        return JsonResponse({'ok': False, 'error': 'This Friendly Game is no longer accepting players.'}, status=409)
    if not _session_creator_player(request, game):
        return JsonResponse({'ok': False, 'error': 'Only the game creator can assign scanned players.'}, status=403)

    try:
        payload = json.loads(request.body or '{}')
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'ok': False, 'error': 'Invalid setup request.'}, status=400)

    mode = str(payload.get('mode', 'manual')).lower()
    if mode not in {'manual', 'random', 'balanced'}:
        return JsonResponse({'ok': False, 'error': 'Invalid setup mode.'}, status=400)

    verified_ids = _verified_friendly_qr_player_ids(request)
    existing = list(game.players.select_related('player').all())
    existing_ids = {entry.player_id for entry in existing}
    black_existing = [entry.player for entry in existing if entry.team == 'BLACK']
    white_existing = [entry.player for entry in existing if entry.team == 'WHITE']
    assigned_ids = set()

    def scanned_player(raw_id):
        try:
            player_id = int(raw_id)
        except (TypeError, ValueError):
            raise ValueError('Invalid scanned player.')
        if player_id not in verified_ids:
            raise ValueError('Every creator-assigned player must be scanned by QR first.')
        if player_id in existing_ids:
            return None
        try:
            return Player.objects.select_related('profile').get(id=player_id)
        except Player.DoesNotExist:
            raise ValueError('A scanned player could not be found.')

    try:
        with transaction.atomic():
            created = []
            if mode == 'manual':
                assignments = payload.get('assignments', [])
                if not isinstance(assignments, list):
                    raise ValueError('Invalid manual assignment data.')
                for assignment in assignments:
                    if not isinstance(assignment, dict) or assignment.get('team') not in {'BLACK', 'WHITE'}:
                        raise ValueError('Choose Black or White for each scanned player.')
                    player = scanned_player(assignment.get('id'))
                    if not player or player.id in assigned_ids:
                        continue
                    team = assignment['team']
                    current_count = game.players.filter(team=team).count()
                    if current_count >= MAX_FRIENDLY_TEAM_SIZE:
                        raise ValueError(f'{team.title()} team is full.')
                    created.append(FriendlyGamePlayer.objects.create(
                        game=game,
                        player=player,
                        team=team,
                        position=_friendly_position_for_player(player),
                        provided_codename='QR',
                        codename_verified=True,
                    ))
                    assigned_ids.add(player.id)
            else:
                raw_ids = payload.get('player_ids', [])
                if not isinstance(raw_ids, list):
                    raise ValueError('Invalid scanned participant data.')
                scanned_players = []
                for raw_id in raw_ids:
                    player = scanned_player(raw_id)
                    if player and player.id not in assigned_ids:
                        scanned_players.append(player)
                        assigned_ids.add(player.id)
                if len(scanned_players) + len(existing) > MAX_FRIENDLY_TEAM_SIZE * 2:
                    raise ValueError('A Friendly Game can contain at most six players.')
                if mode == 'random':
                    black_after, white_after = _random_friendly_assignments(scanned_players, black_existing, white_existing)
                else:
                    black_after, white_after = _balanced_friendly_assignments(scanned_players, black_existing, white_existing)
                black_existing_ids = {player.id for player in black_existing}
                white_existing_ids = {player.id for player in white_existing}
                for team, players_after, known_ids in (
                    ('BLACK', black_after, black_existing_ids),
                    ('WHITE', white_after, white_existing_ids),
                ):
                    for player in players_after:
                        if player.id in known_ids:
                            continue
                        created.append(FriendlyGamePlayer.objects.create(
                            game=game,
                            player=player,
                            team=team,
                            position=_friendly_position_for_player(player),
                            provided_codename='QR',
                            codename_verified=True,
                        ))

            game.update_validation_status()

            scanned_ids = request.session.get('friendly_qr_scanned_player_ids', [])
            if isinstance(scanned_ids, list) and assigned_ids:
                request.session['friendly_qr_scanned_player_ids'] = [player_id for player_id in scanned_ids if player_id not in assigned_ids]
                request.session.modified = True
    except ValueError as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)

    notify_game_state_changed(game.id, game.status, game=game)
    return JsonResponse({
        'ok': True,
        'created_count': len(created),
        'message': 'Scanned players were added to the Friendly Game.',
        'redirect_url': reverse('friendly_games:game_detail', kwargs={'game_id': game.id}),
    })


def activate_game(request, game_id):
    """Activate a friendly game to start playing"""
    game = get_object_or_404(FriendlyGame, id=game_id)
    
    if game.status == 'READY':
        game.status = 'ACTIVE'
        game.save()
        notify_game_state_changed(game.id, game.status)
        messages.success(request, f'Game "{game.name}" is now active!')
    
    return redirect('friendly_games:game_detail', game_id=game.id)


def submit_score(request, game_id):
    """Submit scores for a friendly game - First step of two-team validation
    STRICT REQUIREMENT: Submitter must provide a valid codename"""
    from pfc_core.qr_action_auth import get_qr_action_player, get_qr_action_token
    game = get_object_or_404(FriendlyGame, id=game_id)
    
    # Check if result already exists (someone already submitted)
    if hasattr(game, 'result'):
        messages.info(request, 'Scores have already been submitted for this game. Please validate the result.')
        return redirect('friendly_games:validate_result', game_id=game.id)
    
    if request.method == 'POST':
        black_score = int(request.POST.get('black_score', 0))
        white_score = int(request.POST.get('white_score', 0))
        submitter_codename = request.POST.get('submitter_codename', '').strip().upper()
        _qr_action_player = get_qr_action_player(request)
        if _qr_action_player:
            try:
                submitter_codename = _qr_action_player.codename_profile.codename
            except Exception:
                submitter_codename = ''
        submitted_by_team = request.POST.get('submitting_team', '').upper()
        
        # STRICT REQUIREMENT: Submitter must provide a valid codename
        if not submitter_codename:
            messages.error(request, 'You must provide your codename to submit scores.')
            return redirect('friendly_games:submit_score', game_id=game.id)
        
        # Validate submitted_by_team
        if submitted_by_team not in ['BLACK', 'WHITE']:
            messages.error(request, 'Please select which team is submitting the scores.')
            return redirect('friendly_games:submit_score', game_id=game.id)
        
        # Verify submitter codename belongs to a player from the submitting team
        valid_submitter = False
        submitting_players = game.players.filter(team=submitted_by_team)
        for game_player in submitting_players:
            try:
                from .models import PlayerCodename
                player_codename = game_player.player.codename_profile
                if player_codename.codename == submitter_codename:
                    valid_submitter = True
                    break
            except PlayerCodename.DoesNotExist:
                continue
        
        if not valid_submitter:
            messages.error(request, f'Invalid codename "{submitter_codename}". Please provide a correct codename from the {submitted_by_team.lower()} team.')
            return redirect('friendly_games:submit_score', game_id=game.id)
        
        # Validate scores
        if black_score < 0 or white_score < 0:
            messages.error(request, 'Scores cannot be negative.')
            return redirect('friendly_games:submit_score', game_id=game.id)
        
        # Add maximum score validation (like tournament matches)
        if black_score > 13 or white_score > 13:
            messages.error(request, 'Scores cannot exceed 13 points.')
            return redirect('friendly_games:submit_score', game_id=game.id)
        
        if black_score == white_score:
            messages.error(request, 'Scores cannot be tied. One team must win.')
            return redirect('friendly_games:submit_score', game_id=game.id)
        
        # Update game scores but don't complete yet
        game.black_team_score = black_score
        game.white_team_score = white_score
        game.status = 'PENDING_VALIDATION'  # New status for pending validation
        game.save()
        notify_game_state_changed(game.id, game.status)
        # Create FriendlyGameResult for validation process
        from .models import FriendlyGameResult
        result = FriendlyGameResult.objects.create(
            game=game,
            submitted_by_team=submitted_by_team,
            submitter_codename=submitter_codename,
            submitter_verified=True  # Already verified above
        )
        # The non-submitting side now has the existing validation action.
        from pfc_events.push_notifications import notify_match_action_required
        other_team = 'WHITE' if submitted_by_team == 'BLACK' else 'BLACK'
        notify_match_action_required(
            list(game.players.filter(team=other_team).values_list('player', flat=True)),
            "result_validation",
            "game",
            game.id,
        )
        
        # Mark the submitting game player as verified
        for game_player in submitting_players:
            try:
                from .models import PlayerCodename
                player_codename = game_player.player.codename_profile
                if player_codename.codename == submitter_codename:
                    game_player.codename_verified = True
                    game_player.provided_codename = submitter_codename
                    game_player.save()
                    break
            except PlayerCodename.DoesNotExist:
                continue
                pass
        
        result.save()
        
        # Update validation status (will be PARTIALLY_VALIDATED if codename provided)
        game.validation_status = 'PARTIALLY_VALIDATED' if result.submitter_verified else 'NOT_VALIDATED'
        game.save()
        
        # Submitting team returns to game_detail (waiting state)
        # The opposing team navigates to validation themselves
        return redirect('friendly_games:game_detail', game_id=game.id)
    
    # Get session context for template
    from pfc_core.session_utils import SessionManager
    session_context = SessionManager.get_session_context(request)

    # Get team players for display
    black_players = game.players.filter(team='BLACK')
    white_players = game.players.filter(team='WHITE')

    # Auto-detect which team the logged-in player belongs to
    session_codename = ''
    _qr_action_player = get_qr_action_player(request)
    if _qr_action_player:
        try:
            session_codename = _qr_action_player.codename_profile.codename
        except Exception:
            session_codename = ''
    if not session_codename:
        session_codename = CodenameSessionManager.get_logged_in_codename(request)
    auto_team = None
    if session_codename:
        for gp in game.players.all():
            try:
                if gp.player.codename_profile.codename == session_codename:
                    auto_team = gp.team  # 'BLACK' or 'WHITE'
                    break
            except Exception:
                pass

    # Pre-fill scores from live scoreboard if available.
    # Use the latest scoreboard values as source of truth even if is_active=False
    # (e.g. game reached 13 and scoreboard stopped, but last values are still correct).
    # Only skip if no scoreboard exists at all or both scores are None.
    prefill_black_score = 0
    prefill_white_score = 0
    try:
        scoreboard = game.live_scoreboard
        if scoreboard is not None:
            s1 = scoreboard.team1_score
            s2 = scoreboard.team2_score
            if s1 is not None or s2 is not None:
                prefill_black_score = s1 or 0
                prefill_white_score = s2 or 0
    except Exception:
        pass

    context = {
        'game': game,
        'black_players': black_players,
        'white_players': white_players,
        'session_codename': session_codename,
        'auto_team': auto_team,
        'prefill_black_score': prefill_black_score,
        'prefill_white_score': prefill_white_score,
        'qr_action_token': get_qr_action_token(request),
    }

    # Add session context
    context.update(session_context)

    return render(request, 'friendly_games/submit_score.html', context)


def game_list(request):
    """List all friendly games"""
    games = FriendlyGame.objects.all().order_by('-created_at')
    
    context = {
        'games': games,
    }
    
    return render(request, 'friendly_games/game_list.html', context)



def join_game(request):
    """
    Join a friendly game using match number.
    Players can select team, position, and optionally provide codename for stats.
    """
    if request.method == 'POST':
        match_number = request.POST.get('match_number', '').strip()
        team = request.POST.get('team')
        position = request.POST.get('position', 'MILIEU')
        player_name = request.POST.get('player_name', '').strip()
        codename = request.POST.get('codename', '').strip()
        # If no codename in POST, check for QR-resolved codename in session (server-side only)
        if not codename:
            _qr_codename_session = request.session.pop('qr_resolved_codename', None)
            if _qr_codename_session:
                codename = _qr_codename_session.upper()

        # Validate required fields
        if not match_number or not team or not player_name:
            messages.error(request, 'Match number, team, and player name are required.')
            return render(request, 'friendly_games/join_game.html')
        
        try:
            # Find the game by match number
            game = FriendlyGame.objects.get(match_number=match_number)
            
            # Check if game is expired
            if game.is_expired():
                game.status = 'EXPIRED'
                game.save()
                deactivate_friendly_game_presence(game)
                messages.error(request, f'Match #{match_number} has expired.')
                return render(request, 'friendly_games/join_game.html')
            
            # Check if game is still accepting players
            if game.status not in ['WAITING_FOR_PLAYERS', 'DRAFT']:
                messages.error(request, f'Match #{match_number} is no longer accepting players.')
                return render(request, 'friendly_games/join_game.html')
            
            # Check team capacity (max 3 players per team)
            team_count = game.players.filter(team=team).count()
            if team_count >= 3:
                messages.error(request, f'{team.title()} team is full (3 players maximum).')
                return render(request, 'friendly_games/join_game.html')
            
            # Find or create a special team for friendly games
            friendly_team, created = Team.objects.get_or_create(
                name="Friendly Games",
                defaults={'pin': '000000'}  # Special PIN for friendly games team
            )
            
            # Find player by codename instead of creating duplicates
            player = None
            if codename:
                try:
                    # Look up player by codename first
                    player_codename = PlayerCodename.objects.get(codename=codename.upper())
                    player = player_codename.player
                    
                    # Auto-transfer player to friendly games team if they're not already there
                    if player.team != friendly_team:
                        old_team = player.team
                        player.team = friendly_team
                        player.save()
                        logger.info(f"Auto-transferred player {player.name} from {old_team.name} to {friendly_team.name}")
                        
                except PlayerCodename.DoesNotExist:
                    # If codename doesn't exist, create new player with codename
                    player = Player.objects.create(name=player_name, team=friendly_team)
                    PlayerCodename.objects.create(player=player, codename=codename.upper())
                    logger.info(f"Created new player {player_name} with codename {codename}")
            else:
                # If no codename provided, try to find existing player by name or create new one
                try:
                    player = Player.objects.get(name=player_name, team=friendly_team)
                except Player.DoesNotExist:
                    # Check if player exists in other teams
                    existing_players = Player.objects.filter(name=player_name)
                    if existing_players.exists():
                        # Use the first existing player and transfer them
                        player = existing_players.first()
                        old_team = player.team
                        player.team = friendly_team
                        player.save()
                        logger.info(f"Auto-transferred existing player {player.name} from {old_team.name} to {friendly_team.name}")
                    else:
                        # Create new player without codename
                        player = Player.objects.create(name=player_name, team=friendly_team)
                        logger.info(f"Created new player {player_name} without codename")
                except Player.MultipleObjectsReturned:
                    # Handle duplicate players - use the first one and log the issue
                    player = Player.objects.filter(name=player_name, team=friendly_team).first()
                    logger.warning(f"Multiple players found with name {player_name} in {friendly_team.name}, using first one")
            
            # Check if player is already in this game
            if game.players.filter(player=player).exists():
                messages.warning(request, f'{player_name} is already in this game.')
                return redirect('friendly_games:game_detail', game_id=game.id)
            
            # Verify codename (already verified if we found player by codename)
            codename_verified = False
            if codename:
                try:
                    player_codename = PlayerCodename.objects.get(player=player)
                    codename_verified = (codename.upper() == player_codename.codename)
                except PlayerCodename.DoesNotExist:
                    codename_verified = False
            
            # Add player to game
            FriendlyGamePlayer.objects.create(
                game=game,
                player=player,
                team=team,
                position=position,
                provided_codename=codename,
                codename_verified=codename_verified
            )
            
            # Update game validation status
            game.update_validation_status()
            
            # Success message
            verification_msg = " (Stats will be recorded)" if codename_verified else " (No stats - codename not verified)" if codename else ""
            messages.success(request, f'{player_name} joined {team.title()} team as {position}{verification_msg}')
            
            return redirect('friendly_games:game_detail', game_id=game.id)
            
        except FriendlyGame.DoesNotExist:
            messages.error(request, f'No game found with match number #{match_number}')
        except Exception as e:
            messages.error(request, f'Error joining game: {str(e)}')
    
    # GET request - show join form
    # Get logged-in user's codename from session
    session_codename = CodenameSessionManager.get_logged_in_codename(request)
    
    # Auto-detect logged-in player for dual binding (like Create Game)
    auto_selected_player = None
    if session_codename:
        try:
            # Find player by codename
            player_codename = PlayerCodename.objects.get(codename=session_codename)
            auto_selected_player = player_codename.player
        except PlayerCodename.DoesNotExist:
            # If no exact codename match, try to find by name similarity
            try:
                auto_selected_player = Player.objects.get(name__iexact=session_codename)
            except Player.DoesNotExist:
                pass
    
    # Get all players for search functionality
    all_players = Player.objects.all().select_related('team')
    players_json = json.dumps([{
        'name': player.name,
        'team': player.team.name if player.team else 'No Team'
    } for player in all_players])
    
    # Read match_number from URL query string so template can prefill deterministically
    prefill_match_number = request.GET.get('match_number', '').strip()
    if not (prefill_match_number.isdigit() and len(prefill_match_number) == 4):
        prefill_match_number = ''

    # Server-side game preload — renders preview directly in HTML, no JS needed
    prefill_game = None
    prefill_black_players = []
    prefill_white_players = []
    prefill_black_slots = 0
    prefill_white_slots = 0
    prefill_black_full = False
    prefill_white_full = False
    prefill_black_slot_range = []
    prefill_white_slot_range = []
    MAX_TEAM_SIZE = 3

    if prefill_match_number:
        try:
            g = FriendlyGame.objects.get(match_number=prefill_match_number)
            if not g.is_expired() and g.status in ['WAITING_FOR_PLAYERS', 'DRAFT']:
                prefill_game = g
                black_ps = list(g.players.filter(team='BLACK').select_related('player'))
                white_ps = list(g.players.filter(team='WHITE').select_related('player'))
                prefill_black_players = [p.player.name for p in black_ps]
                prefill_white_players = [p.player.name for p in white_ps]
                prefill_black_slots = max(0, MAX_TEAM_SIZE - len(prefill_black_players))
                prefill_white_slots = max(0, MAX_TEAM_SIZE - len(prefill_white_players))
                prefill_black_full = (prefill_black_slots == 0)
                prefill_white_full = (prefill_white_slots == 0)
                # Pre-built ranges for template iteration (Django templates can't do range())
                prefill_black_slot_range = list(range(prefill_black_slots))
                prefill_white_slot_range = list(range(prefill_white_slots))
        except FriendlyGame.DoesNotExist:
            pass

    context = {
        'team_name': request.session.get('team_name', 'Guest'),
        'players_json': players_json,
        'session_codename': session_codename,
        'auto_selected_player': auto_selected_player,
        'prefill_match_number': prefill_match_number,
        # Server-side preloaded game preview
        'prefill_game': prefill_game,
        'prefill_black_players': prefill_black_players,
        'prefill_white_players': prefill_white_players,
        'prefill_black_slots': prefill_black_slots,
        'prefill_white_slots': prefill_white_slots,
        'prefill_black_full': prefill_black_full,
        'prefill_white_full': prefill_white_full,
        'prefill_black_slot_range': prefill_black_slot_range,
        'prefill_white_slot_range': prefill_white_slot_range,
        'max_team_size': MAX_TEAM_SIZE,
    }
    
    return render(request, 'friendly_games/join_game.html', context)



def start_match(request, game_id):
    """
    Start a friendly game match - transition from WAITING_FOR_PLAYERS to ACTIVE.
    Only the creator/host can start the game.
    """
    game = get_object_or_404(FriendlyGame, id=game_id)

    # ── Auto-expire if unstarted for more than 10 minutes ────────────────────
    if game.is_pre_start_expired():
        game.status = 'CANCELLED'
        game.save()
        deactivate_friendly_game_presence(game)  # clear any presence if game never started
        messages.error(request, 'This game has expired (not started within 10 minutes) and has been cancelled.')
        return redirect('friendly_games:game_detail', game_id=game.id)

    # ── Creator-only check ────────────────────────────────────────────────────
    # A short-lived QR proof may act only as that exact creator for this URL.
    if game.creator_player:
        from pfc_core.qr_action_auth import get_qr_action_player
        _qr_action_player = get_qr_action_player(request)
        session_codename = ''
        if _qr_action_player:
            try:
                session_codename = _qr_action_player.codename_profile.codename
            except Exception:
                session_codename = ''
        if not session_codename:
            session_codename = CodenameSessionManager.get_logged_in_codename(request)
        is_creator = False
        if session_codename:
            try:
                cp = game.creator_player.codename_profile
                is_creator = (cp.codename == session_codename.upper())
            except Exception:
                is_creator = False
        if not is_creator:
            messages.error(request, 'Only the game creator can start this game.')
            return redirect('friendly_games:game_detail', game_id=game.id)

    # ── Check if game can be started ─────────────────────────────────────────
    if game.status != 'WAITING_FOR_PLAYERS':
        messages.error(request, f'Game cannot be started. Current status: {game.get_status_display()}')
        return redirect('friendly_games:game_detail', game_id=game.id)

    # Use the basic validation check from the model
    can_start, reason = game.can_start()

    if not can_start:
        messages.error(request, f'Cannot start game: {reason}')
        return redirect('friendly_games:game_detail', game_id=game.id)
    
    # Select the opening side once at activation. This is only a setup prompt;
    # score state, validation, and the existing Live Score system remain unchanged.
    game.starting_team = random.choice(['BLACK', 'WHITE'])
    starting_side_players = list(game.players.filter(team=game.starting_team).values_list('player_id', flat=True))

    # Start the game
    game.status = 'ACTIVE'
    # Use court-local time so started_at reflects the venue's local clock
    _game_complex = game.court_complex
    _game_now = get_court_local_now(_game_complex) if _game_complex else timezone.now()
    game.started_at = _game_now
    # Start timer if timed game
    if game.is_timed and game.time_limit_minutes:
        game.timer_started_at = _game_now
    game.save()
    notify_game_state_changed(game.id, game.status, game=game)
    try:
        from pfc_events.push_notifications import notify_match_action_required
        notify_match_action_required(starting_side_players, 'friendly_starts', 'friendly_game', game.id)
    except Exception as exc:
        # Optional alert delivery must never prevent a valid Friendly Game start.
        logger.warning('Friendly starting-side notification failed for game %s: %s', game.id, exc)

    # Register players at court (presence tracking)
    register_friendly_game_players_at_court(game)

    # Check validation status for informational message
    if game.is_fully_validated():
        messages.success(request, f'Game "{game.name}" has been started! All teams have verified players for result validation. Good luck!')
    else:
        messages.warning(request, f'Game "{game.name}" has been started! Note: Only players with verified codenames can validate results. Good luck!')

    # Route to live scoreboard so all participants enter live score mode
    try:
        scoreboard = game.live_scoreboard
        return redirect('scoreboard_detail', scoreboard_id=scoreboard.id)
    except Exception:
        # Fallback if scoreboard doesn't exist for some reason
        return redirect('friendly_games:game_detail', game_id=game.id)


def validate_result(request, game_id):
    """
    Second step of two-team validation - opposing team validates the submitted result.
    Session-bound: codename is read from session, never from form input.
    """
    from pfc_core.qr_action_auth import get_qr_action_player, get_qr_action_token
    game = get_object_or_404(FriendlyGame, id=game_id)
    _qr_action_player = get_qr_action_player(request)

    # Check if there's a result to validate
    if not hasattr(game, 'result'):
        return redirect('friendly_games:game_detail', game_id=game.id)

    result = game.result

    # Already validated — redirect silently
    if not result.is_pending_validation():
        return redirect('friendly_games:game_detail', game_id=game.id)

    # Determine which team should validate
    validating_team = result.get_other_team()   # 'BLACK' or 'WHITE'
    submitting_team = result.submitted_by_team  # the team that must NOT validate
    validating_players = game.players.filter(team=validating_team)

    # ── Detect session player's team in this game ──────────────────────────
    from pfc_core.session_utils import CodenameSessionManager
    session_codename = ''
    if _qr_action_player:
        try:
            session_codename = _qr_action_player.codename_profile.codename
        except Exception:
            session_codename = ''
    if not session_codename:
        session_codename = CodenameSessionManager.get_logged_in_codename(request)
    session_player_team = None  # 'BLACK', 'WHITE', or None
    if session_codename:
        for gp in game.players.all():
            try:
                if gp.player.codename_profile.codename == session_codename:
                    session_player_team = gp.team
                    break
            except Exception:
                pass

    # ── Self-validation guard ──────────────────────────────────────────────
    # If the session player is on the submitting team, block silently via template flag.
    is_own_team = (session_player_team is not None and
                   session_player_team == submitting_team)

    if request.method == 'POST':
        validation_action = request.POST.get('validation_action')
        if validation_action not in ['agree', 'disagree']:
            return redirect('friendly_games:validate_result', game_id=game.id)

        # ── Determine validator identity ───────────────────────────────────────
        # The QR resolve endpoint stores the opponent's codename server-side in
        # session['qr_resolved_codename'].  It is NEVER sent from the browser.
        # The active session (Player A) is NEVER replaced or modified.
        #
        # Priority:
        #   1. QR-resolved opponent codename (if present) — used as the validator
        #      identity regardless of who is currently logged in.  This is the
        #      "submitter scans opponent QR" path.
        #   2. Session codename (logged-in player) — used when no QR scan occurred.
        #      This is the normal path where the opponent opens the page themselves.
        _qr_codename_session = request.session.pop('qr_resolved_codename', None)
        if _qr_action_player:
            try:
                _qr_codename_session = _qr_action_player.codename_profile.codename
            except Exception:
                _qr_codename_session = None
        if _qr_codename_session:
            # QR path: use the scanned opponent's codename as the validator.
            # Do NOT replace session_codename — Player A stays logged in as Player A.
            validator_codename = _qr_codename_session.upper()
        else:
            # Normal path: the person holding the phone is the validator.
            # Hard block: reject POST from submitting team without any message.
            if is_own_team:
                return redirect('friendly_games:validate_result', game_id=game.id)
            validator_codename = session_codename or ''

        # Verify the session codename belongs to a player from the validating team
        valid_validator = False
        for game_player in validating_players:
            try:
                if game_player.player.codename_profile.codename == validator_codename:
                    valid_validator = True
                    break
            except Exception:
                continue

        if not valid_validator:
            # Session player not on validating team — redirect silently
            return redirect('friendly_games:validate_result', game_id=game.id)

        # Perform validation
        result.validate_result(
            validating_team=validating_team,
            action=validation_action,
            validator_codename=validator_codename
        )
        # Notify all connected clients that game state changed
        game.refresh_from_db()
        notify_game_state_changed(game.id, game.status)
        if validation_action == 'disagree' and game.status == 'ACTIVE':
            from pfc_events.push_notifications import notify_match_action_required
            notify_match_action_required(
                list(game.players.select_related('player').values_list('player', flat=True)),
                "reopened",
                "game",
                game.id,
            )
        # Deactivate presence if game is now COMPLETED
        if game.status == 'COMPLETED':
            deactivate_friendly_game_presence(game)
        # Redirect silently — UI state communicates the outcome
        return redirect('friendly_games:game_detail', game_id=game.id)

    # ── GET: build context ─────────────────────────────────────────────────
    from pfc_core.session_utils import SessionManager
    session_context = SessionManager.get_session_context(request)

    context = {
        'game': game,
        'result': result,
        'validating_team': validating_team.lower(),
        'submitting_team': submitting_team.lower(),
        'validating_players': validating_players,
        'is_own_team': is_own_team,
        'qr_action_token': get_qr_action_token(request),
    }
    context.update(session_context)

    return render(request, 'friendly_games/validate_result.html', context)



import json
from django.http import JsonResponse

def check_codename(request, game_id):
    """AJAX endpoint to check which team a codename belongs to in a specific game"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Method not allowed'})
    
    try:
        data = json.loads(request.body)
        codename = data.get('codename', '').strip().upper()
        
        if not codename or len(codename) != 6:
            return JsonResponse({'success': False, 'error': 'Invalid codename'})
        
        game = get_object_or_404(FriendlyGame, id=game_id)
        
        # Check if codename exists and belongs to a player in this game
        from .models import PlayerCodename
        try:
            player_codename = PlayerCodename.objects.get(codename=codename)
            
            # Check if this player is in the game
            game_player = game.players.filter(player=player_codename.player).first()
            
            if game_player:
                return JsonResponse({
                    'success': True,
                    'team': game_player.team,
                    'player_name': player_codename.player.name
                })
            else:
                return JsonResponse({'success': False, 'error': 'Player not in this game'})
                
        except PlayerCodename.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Codename not found'})
            
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})



def leave_game(request, game_id):
    """
    Allow a joined player to leave a friendly game before it starts.
    Only works when the game is still WAITING_FOR_PLAYERS.
    The player is identified via their session codename.
    """
    if request.method != 'POST':
        return redirect('friendly_games:game_detail', game_id=game_id)

    game = get_object_or_404(FriendlyGame, id=game_id)

    # Can only leave before the game starts
    if game.status != 'WAITING_FOR_PLAYERS':
        messages.error(request, 'You cannot leave a game that has already started.')
        return redirect('friendly_games:game_detail', game_id=game.id)

    # Identify the requesting player via session codename
    session_codename = CodenameSessionManager.get_logged_in_codename(request)
    if not session_codename:
        messages.error(request, 'You must be logged in with a codename to leave a game.')
        return redirect('friendly_games:game_detail', game_id=game.id)

    # Find the FriendlyGamePlayer record for this session player
    game_player = None
    for gp in game.players.select_related('player').all():
        try:
            if gp.player.codename_profile.codename == session_codename.upper():
                game_player = gp
                break
        except Exception:
            continue

    if not game_player:
        messages.error(request, 'You are not in this game.')
        return redirect('friendly_games:game_detail', game_id=game.id)

    # Prevent the creator from leaving (they should cancel instead)
    if game.creator_player and game.creator_player.id == game_player.player.id:
        messages.error(request, 'The game creator cannot leave. Cancel the game instead.')
        return redirect('friendly_games:game_detail', game_id=game.id)

    player_name = game_player.player.name
    team_name = game_player.team.title()
    game_player.delete()

    # Update validation status after player leaves
    game.update_validation_status()

    messages.success(request, f'{player_name} has left the {team_name} team. You can now join the correct side.')
    return redirect('friendly_games:game_detail', game_id=game.id)


def rematch(request, game_id):
    """
    Create a new friendly game with the same players and configuration as the completed game.
    This allows for quick rematch without re-entering all player details.
    """
    # Only allow POST requests to prevent accidental/automatic rematch creation
    if request.method != 'POST':
        messages.error(request, 'Invalid request method.')
        return redirect('friendly_games:game_detail', game_id=game_id)

    # Get the original game
    original_game = get_object_or_404(FriendlyGame, id=game_id)

    # Resolve the rematch initiator from session — they become the creator/host of the new game.
    # Do NOT carry over ownership from the original game.
    rematch_initiator = None
    session_codename = CodenameSessionManager.get_logged_in_codename(request)
    if session_codename:
        try:
            from friendly_games.models import PlayerCodename
            cn_obj = PlayerCodename.objects.get(codename=session_codename.upper())
            rematch_initiator = cn_obj.player
        except Exception:
            pass

    # Create new game with same configuration; assign ownership to the rematch initiator.
    # Copy time settings (is_timed, time_limit_minutes) from the original game.
    # Copy court_complex and court so presence registration fires correctly on start.
    # Do NOT copy timer_started_at or timer_expired — those are runtime state, not settings.
    new_game = FriendlyGame.objects.create(
        name=f"{original_game.name} - Rematch",
        target_score=original_game.target_score,
        status='WAITING_FOR_PLAYERS',
        creator_player=rematch_initiator,  # rematch initiator is the new host
        is_timed=original_game.is_timed,
        time_limit_minutes=original_game.time_limit_minutes,
        court_complex=original_game.court_complex,  # inherit venue — required for presence registration
        court=original_game.court,                  # inherit specific court if set
    )
    
    # Copy all players with same teams and positions
    original_players = original_game.players.all()
    
    for original_player in original_players:
        FriendlyGamePlayer.objects.create(
            game=new_game,
            player=original_player.player,
            team=original_player.team,
            position=original_player.position,
            provided_codename=original_player.provided_codename,
            codename_verified=original_player.codename_verified
        )
    
    # Update validation status for new game
    new_game.update_validation_status()
    
    messages.success(
        request, 
        f'Rematch created! All players from the previous game have been added. Match #{new_game.match_number}'
    )
    
    # Redirect to the new game detail page
    return redirect('friendly_games:game_detail', game_id=new_game.id)


# ── Polling endpoint ────────────# ── Polling endpoint ────────────────────────────────────────────
from django.http import JsonResponse as _FGJsonResponse
from django.urls import reverse as _fg_reverse

def game_status_api(request, game_id):
    """
    Session-aware polling endpoint for game_detail.html.
    Returns routing information for the current session user so the
    polling JS can redirect the opposing team to validation automatically.
    """
    try:
        game = FriendlyGame.objects.get(id=game_id)
    except FriendlyGame.DoesNotExist:
        return _FGJsonResponse({'error': 'not found'}, status=404)

    payload = {
        'status': game.status,
        'current_user_team': None,
        'submitted_by_team': None,
        'should_redirect_to_validation': False,
        'validation_url': None,
    }

    # Check if a result is pending validation
    pending = False
    submitted_by_team = None
    if hasattr(game, 'result'):
        try:
            result = game.result
            if result.is_pending_validation():
                pending = True
                submitted_by_team = result.submitted_by_team  # 'BLACK' or 'WHITE'
                payload['submitted_by_team'] = submitted_by_team
        except Exception:
            pass

    if not pending:
        return _FGJsonResponse(payload)

    # Resolve current session user's team in this game
    from pfc_core.session_utils import CodenameSessionManager
    session_codename = CodenameSessionManager.get_logged_in_codename(request)
    my_team = None
    if session_codename:
        for gp in game.players.all():
            try:
                if gp.player.codename_profile.codename == session_codename:
                    my_team = gp.team  # 'BLACK' or 'WHITE'
                    break
            except Exception:
                pass

    payload['current_user_team'] = my_team

    if my_team and submitted_by_team and my_team != submitted_by_team:
        payload['should_redirect_to_validation'] = True
        payload['validation_url'] = _fg_reverse('friendly_games:validate_result', args=[game.id])

    return _FGJsonResponse(payload)

# ─────────────────────────────────────────────────────────────────────────────
# QR RESOLVE ENDPOINT — friendly games
# Receives a raw QR token, verifies HMAC, returns player identity.
# Used by the jsQR scanner widget on game pages.
# ─────────────────────────────────────────────────────────────────────────────

def qr_resolve_player(request):
    """
    POST /friendly/api/qr-resolve/

    Body (JSON): { "token": "PFC-QR:<OPAQUE_ID>:<HMAC>" }

    Returns JSON (codename is NEVER returned to the browser):
        Success: { "ok": true, "player_name": "...", "player_id": ..., "team_name": "..." }
        Failure: { "ok": false, "error": "..." }

    The token payload is fully opaque (base64url-encoded player_id + HMAC).
    The resolved codename is stored server-side in the session as
    'qr_resolved_codename' so that validation/join views can read it
    without ever exposing it to the client.

    Scope: game_participation only. Token is HMAC-verified.
    """
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'Method not allowed'}, status=405)

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'ok': False, 'error': 'Invalid JSON'}, status=400)

    token = data.get('token', '').strip()
    if not token:
        return JsonResponse({'ok': False, 'error': 'No token provided'}, status=400)

    from pfc_core.qr_utils import verify_player_token
    # verify_player_token now returns player_id (int) or None — no codename in token
    player_id = verify_player_token(token)
    if not player_id:
        return JsonResponse({'ok': False, 'error': 'Invalid or tampered QR code'}, status=400)

    # Look up the player and their codename by player_id (server-side only)
    try:
        pc = PlayerCodename.objects.select_related('player__team').get(player_id=player_id)
    except PlayerCodename.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'Player not found'}, status=404)

    # Store the resolved codename in the session (server-side only).
    # This allows validation/join views to read it without the codename
    # ever being sent to the browser.
    request.session['qr_resolved_codename'] = pc.codename
    scanned_player_ids = request.session.get('friendly_qr_scanned_player_ids', [])
    if not isinstance(scanned_player_ids, list):
        scanned_player_ids = []
    if pc.player_id not in scanned_player_ids:
        scanned_player_ids.append(pc.player_id)
    # This session-only list authorizes creator setup placement; it is never a
    # persistent delegation and expires with the browser session.
    request.session['friendly_qr_scanned_player_ids'] = scanned_player_ids[-12:]
    request.session.modified = True

    # Return player identity WITHOUT codename — codename is an internal identifier
    # and must not be exposed to the browser/client.
    # Include profile_picture_url so the confirmation modal can show the avatar.
    avatar_url = ''
    try:
        profile = pc.player.profile
        if profile.profile_picture:
            avatar_url = profile.profile_picture.url
    except Exception:
        pass
    return JsonResponse({
        'ok': True,
        'player_name': pc.player.name,
        'player_id': pc.player.id,
        'team_name': pc.player.team.name if pc.player.team else '',
        'profile_picture_url': avatar_url,
    })
