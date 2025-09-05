from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import JsonResponse
from django.utils import timezone
from django.db.models import Q
import json
import logging
from teams.models import Player, Team
from .models import FriendlyGame, FriendlyGamePlayer, PlayerCodename, FriendlyGameStatistics
from pfc_core.session_utils import CodenameSessionManager

logger = logging.getLogger(__name__)


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
                'teams': Team.objects.all().prefetch_related('players'),
            })
        
        # Validate creator codename
        try:
            creator_player_codename = PlayerCodename.objects.get(codename=creator_codename.upper())
            creator_player = creator_player_codename.player
        except PlayerCodename.DoesNotExist:
            messages.error(request, f'Invalid codename "{creator_codename}". Please provide a correct codename to create a game.')
            return render(request, 'friendly_games/create_game.html', {
                'session_codename': session_codename,
                'teams': Team.objects.all().prefetch_related('players'),
            })
        
        try:
            # Parse player IDs from JSON
            black_player_ids = json.loads(black_team_players) if black_team_players else []
            white_player_ids = json.loads(white_team_players) if white_team_players else []
            
            # Create the game
            game = FriendlyGame.objects.create(name=game_name)
            
            # Add black team players
            for player_id in black_player_ids:
                try:
                    player = Player.objects.get(id=player_id)
                    # Check if this player is the creator and validate them
                    codename_verified = False
                    provided_codename = ''
                    position = 'MILIEU'  # Default position
                    
                    # Check if this is the creator player
                    if player.id == creator_player.id:
                        # Use creator's specified position if provided
                        if creator_position:
                            position = creator_position.upper()
                        
                        # Creator is automatically verified
                        codename_verified = True
                        provided_codename = creator_codename.upper()
                    
                    FriendlyGamePlayer.objects.create(
                        game=game,
                        player=player,
                        team='BLACK',
                        position=position,
                        provided_codename=provided_codename,
                        codename_verified=codename_verified
                    )
                except Player.DoesNotExist:
                    messages.warning(request, f'Player with ID {player_id} not found')
            
            # Add white team players
            for player_id in white_player_ids:
                try:
                    player = Player.objects.get(id=player_id)
                    # Check if this player is the creator and validate them
                    codename_verified = False
                    provided_codename = ''
                    position = 'MILIEU'  # Default position
                    
                    # Check if this is the creator player
                    if player.id == creator_player.id:
                        # Use creator's specified position if provided
                        if creator_position:
                            position = creator_position.upper()
                        
                        # Creator is automatically verified
                        codename_verified = True
                        provided_codename = creator_codename.upper()
                    
                    FriendlyGamePlayer.objects.create(
                        game=game,
                        player=player,
                        team='WHITE',
                        position=position,
                        provided_codename=provided_codename,
                        codename_verified=codename_verified
                    )
                except Player.DoesNotExist:
                    messages.warning(request, f'Player with ID {player_id} not found')
            
            # Update game validation status
            game.update_validation_status()
            
            # Create success message with creator validation info
            total_players = len(black_player_ids) + len(white_player_ids)
            success_msg = f'Friendly game "{game.name}" created successfully with {total_players} players!'
            
            if creator_player:
                success_msg += f' Creator validated as {creator_player.name}.'
            elif creator_codename:
                success_msg += f' Creator codename "{creator_codename}" not found - no validation.'
            
            success_msg += f' Match Number: {game.match_number}'
            
            messages.success(request, success_msg)
            return redirect('friendly_games:game_detail', game_id=game.id)
            
        except json.JSONDecodeError:
            messages.error(request, 'Invalid player selection data')
        except Exception as e:
            messages.error(request, f'Error creating game: {str(e)}')
    
    # Get all teams with their players for selection
    teams = Team.objects.all().prefetch_related('players')
    
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
    
    context = {
        'teams': teams,
        'team_name': request.session.get('team_name', 'Guest'),
        'auto_selected_player': auto_selected_player,
        'session_codename': session_codename,
    }
    
    return render(request, 'friendly_games/create_game.html', context)


def game_detail(request, game_id):
    """Display details of a friendly game"""
    game = get_object_or_404(FriendlyGame, id=game_id)
    players = game.players.all().select_related('player', 'player__team')
    
    context = {
        'game': game,
        'players': players,
    }
    
    return render(request, 'friendly_games/game_detail.html', context)


def activate_game(request, game_id):
    """Activate a friendly game to start playing"""
    game = get_object_or_404(FriendlyGame, id=game_id)
    
    if game.status == 'READY':
        game.status = 'ACTIVE'
        game.save()
        messages.success(request, f'Game "{game.name}" is now active!')
    
    return redirect('friendly_games:game_detail', game_id=game.id)


def submit_score(request, game_id):
    """Submit scores for a friendly game - First step of two-team validation
    STRICT REQUIREMENT: Submitter must provide a valid codename"""
    game = get_object_or_404(FriendlyGame, id=game_id)
    
    # Check if result already exists (someone already submitted)
    if hasattr(game, 'result'):
        messages.info(request, 'Scores have already been submitted for this game. Please validate the result.')
        return redirect('friendly_games:validate_result', game_id=game.id)
    
    if request.method == 'POST':
        black_score = int(request.POST.get('black_score', 0))
        white_score = int(request.POST.get('white_score', 0))
        submitter_codename = request.POST.get('submitter_codename', '').strip().upper()
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
        
        # Create FriendlyGameResult for validation process
        from .models import FriendlyGameResult
        result = FriendlyGameResult.objects.create(
            game=game,
            submitted_by_team=submitted_by_team,
            submitter_codename=submitter_codename,
            submitter_verified=True  # Already verified above
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
        
        other_team = 'White' if submitted_by_team == 'BLACK' else 'Black'
        messages.success(request, f'Scores submitted by {submitted_by_team.title()} team! Black: {black_score}, White: {white_score}. Waiting for {other_team} team validation.')
        return redirect('friendly_games:game_detail', game_id=game.id)
    
    # Get session context for template
    from pfc_core.session_utils import SessionManager
    session_context = SessionManager.get_session_context(request)
    
    # Get team players for display
    black_players = game.players.filter(team='BLACK')
    white_players = game.players.filter(team='WHITE')
    
    context = {
        'game': game,
        'black_players': black_players,
        'white_players': white_players,
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
    
    context = {
        'team_name': request.session.get('team_name', 'Guest'),
        'players_json': players_json,
        'session_codename': session_codename,
        'auto_selected_player': auto_selected_player,
    }
    
    return render(request, 'friendly_games/join_game.html', context)



def start_match(request, game_id):
    """
    Start a friendly game match - transition from WAITING_FOR_PLAYERS to ACTIVE
    Players can participate without codenames, but validation requires verified players
    """
    game = get_object_or_404(FriendlyGame, id=game_id)
    
    # Check if game can be started
    if game.status != 'WAITING_FOR_PLAYERS':
        messages.error(request, f'Game cannot be started. Current status: {game.get_status_display()}')
        return redirect('friendly_games:game_detail', game_id=game.id)
    
    # Use the basic validation check from the model
    can_start, reason = game.can_start()
    
    if not can_start:
        messages.error(request, f'Cannot start game: {reason}')
        return redirect('friendly_games:game_detail', game_id=game.id)
    
    # Start the game
    game.status = 'ACTIVE'
    game.save()
    
    # Check validation status for informational message
    if game.is_fully_validated():
        messages.success(request, f'Game "{game.name}" has been started! All teams have verified players for result validation. Good luck!')
    else:
        messages.warning(request, f'Game "{game.name}" has been started! Note: Only players with verified codenames can validate results. Good luck!')
    
    return redirect('friendly_games:game_detail', game_id=game.id)


def validate_result(request, game_id):
    """
    Second step of two-team validation - opposing team validates the submitted result
    STRICT REQUIREMENT: Only players with verified codenames can validate results
    """
    game = get_object_or_404(FriendlyGame, id=game_id)
    
    # Check if there's a result to validate
    if not hasattr(game, 'result'):
        messages.error(request, 'No result has been submitted for this game yet.')
        return redirect('friendly_games:game_detail', game_id=game.id)
    
    result = game.result
    
    # Check if already validated
    if not result.is_pending_validation():
        messages.info(request, 'This result has already been validated.')
        return redirect('friendly_games:game_detail', game_id=game.id)
    
    # STRICT VALIDATION: Check if result can be validated (requires verified players)
    can_validate, validation_reason = game.can_validate_result()
    if not can_validate:
        messages.error(request, f'Cannot validate result: {validation_reason}')
        return redirect('friendly_games:game_detail', game_id=game.id)
    
    # Determine which team should validate
    validating_team = result.get_other_team()
    validating_players = game.players.filter(team=validating_team)
    
    if request.method == 'POST':
        validation_action = request.POST.get('validation_action')
        validator_codename = request.POST.get('validator_codename', '').strip().upper()
        
        if validation_action not in ['agree', 'disagree']:
            messages.error(request, 'Please select whether you agree or disagree with the result.')
            return redirect('friendly_games:validate_result', game_id=game.id)
        
        # STRICT REQUIREMENT: Validator must provide a valid codename
        if not validator_codename:
            messages.error(request, 'You must provide your codename to validate the result.')
            return redirect('friendly_games:validate_result', game_id=game.id)
        
        # Verify the codename belongs to a player from the validating team
        valid_validator = False
        for game_player in validating_players:
            try:
                player_codename = game_player.player.codename_profile
                if player_codename.codename == validator_codename:
                    valid_validator = True
                    break
            except:
                continue
        
        if not valid_validator:
            messages.error(request, f'Invalid codename "{validator_codename}". Please provide a correct codename from the {validating_team.lower()} team.')
            return redirect('friendly_games:validate_result', game_id=game.id)
        
        # Use the FriendlyGameResult's validate_result method
        result.validate_result(
            validating_team=validating_team,
            action=validation_action,
            validator_codename=validator_codename
        )
        
        if validation_action == 'agree':
            messages.success(request, f'Result validated! Game completed with final score: Black {game.black_team_score} - {game.white_team_score} White')
        else:
            messages.info(request, 'Result disagreement recorded. Game has been reset to active status for new score submission.')
        
        return redirect('friendly_games:game_detail', game_id=game.id)
    
    # Get session context for template
    from pfc_core.session_utils import SessionManager
    session_context = SessionManager.get_session_context(request)
    
    # Get all teams with their players for autocomplete
    teams = Team.objects.all().prefetch_related('players')
    
    context = {
        'game': game,
        'result': result,
        'validating_team': validating_team.lower(),
        'validating_players': validating_players,
        'teams': teams,
    }
    
    # Add session context
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

