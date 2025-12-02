from django.shortcuts import render, redirect, get_object_or_404
from .views_market import pfc_market
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q, Count, Prefetch
from django.http import JsonResponse
from .models import Team, Player, TeamAvailability, PlayerProfile, TeamProfile
from .forms import TeamForm, PlayerForm, TeamAvailabilityForm, PublicPlayerForm, EditPlayerProfileForm
from .utils import get_recent_matches_with_participation, get_player_participation_summary
from matches.models import Match, MatchActivation
from pfc_core.session_utils import CodenameSessionManager
from friendly_games.models import PlayerCodename

# Enhanced public team views
def team_list(request):
    """Enhanced team list with profiles, logos, and statistics"""
    # Filter out Mêlée teams and child teams from public view
    teams = Team.objects.filter(
        ~Q(name__icontains='Mêlée Team'),  # Hide Mêlée teams
        parent_team__isnull=True  # Hide child teams (subteams)
    ).order_by('name')
    
    # Prepare teams with profile data
    teams_with_profiles = []
    for team in teams:
        try:
            profile = team.profile
        except:
            # Create profile if it doesn't exist
            profile = TeamProfile.objects.create(team=team)
        
        # Get accurate team statistics (this will sync if needed)
        stats = profile.get_accurate_statistics()
        
        # Get team statistics
        team_data = {
            'team': team,
            'profile': profile,
            'player_count': team.players.count(),
            'badges': profile.get_badge_display()[:3],  # Show first 3 badges
            'total_badges': len(profile.get_badge_display()),
            'matches_played': stats['matches_played'],
            'matches_won': stats['matches_won'],
            'win_rate': stats['win_rate'],
        }
        teams_with_profiles.append(team_data)
    
    return render(request, 'teams/team_list.html', {'teams_with_profiles': teams_with_profiles})

def team_detail(request, team_id):
    """Enhanced team detail with full profile, clickable players, and statistics"""
    team = get_object_or_404(Team, id=team_id)
    
    # Get or create team profile
    try:
        profile = team.profile
    except:
        profile = TeamProfile.objects.create(team=team)
    
    # Get players with their profiles
    players = team.players.select_related('profile').all()
    
    # Prepare player data with profiles
    players_with_profiles = []
    for player in players:
        try:
            player_profile = player.profile
        except:
            # Create basic profile if it doesn't exist
            from .models import PlayerProfile
            player_profile = PlayerProfile.objects.create(
                player=player,
                email='',
                skill_level=1
            )
        
        player_data = {
            'player': player,
            'profile': player_profile,
            'has_picture': bool(player_profile.profile_picture),
        }
        players_with_profiles.append(player_data)
    
    # Get team statistics and badges
    badges = profile.get_badge_display()
    
    context = {
        'team': team,
        'profile': profile,
        'players_with_profiles': players_with_profiles,
        'badges': badges,
        'team_statistics': {
            'matches_played': profile.matches_played,
            'matches_won': profile.matches_won,
            'win_rate': profile.win_rate(),
            'tournaments_participated': profile.tournaments_participated,
        }
    }
    
    return render(request, 'teams/team_detail.html', context)

def team_create(request):
    if request.method == 'POST':
        form = TeamForm(request.POST)
        if form.is_valid():
            team = form.save()
            
            # Check if there's a pending player creation
            pending_player = request.session.get('pending_player')
            if pending_player:
                # Create the player for the new team
                player = Player.objects.create(
                    name=pending_player['name'],  # ✅ Fixed: Use actual name instead of codename
                    team=team
                )
                
                # Create PlayerCodename entry for login system
                PlayerCodename.objects.create(
                    player=player,
                    codename=pending_player['codename']
                )
                
                # Create player profile with profile picture if available
                profile_picture_path = pending_player.get('profile_picture_path')
                if profile_picture_path:
                    # Load the temporary file
                    from django.core.files.storage import default_storage
                    from django.core.files.base import ContentFile
                    import os
                    
                    if default_storage.exists(profile_picture_path):
                        # Read the temporary file content
                        file_content = default_storage.open(profile_picture_path, 'rb').read()
                        file_name = os.path.basename(profile_picture_path)
                        
                        # Create player profile with the image
                        player_profile = PlayerProfile.objects.create(
                            player=player,
                            email='',
                            skill_level=1
                        )
                        
                        # Save the profile picture
                        player_profile.profile_picture.save(
                            file_name,
                            ContentFile(file_content),
                            save=True
                        )
                        
                        # Clean up the temporary file
                        default_storage.delete(profile_picture_path)
                    else:
                        # Create profile without image if temp file doesn't exist
                        PlayerProfile.objects.create(
                            player=player,
                            email='',
                            skill_level=1
                        )
                else:
                    # Create player profile without image
                    PlayerProfile.objects.create(
                        player=player,
                        email='',
                        skill_level=1
                    )
                
                # Set session data for player login
                request.session['player_codename'] = pending_player['codename']
                request.session['player_name'] = pending_player['name']
                request.session['player_id'] = player.id
                request.session['team_id'] = team.id
                request.session['team_name'] = team.name
                
                # Clear pending player data
                del request.session['pending_player']
                
                # Store team creation success info for PIN display
                request.session['team_created'] = {
                    'team_name': team.name,
                    'player_name': pending_player["name"],
                    'player_id': player.id
                }
                
                messages.success(request, f'Team {team.name} created successfully! Welcome {pending_player["name"]}, your player profile has been completed.')
                # Redirect to show PIN instead of player profile
                return redirect('show_team_pin', team_id=team.id)
            else:
                messages.success(request, f'Team {team.name} created successfully!')
                return redirect('team_detail', team_id=team.id)
    else:
        form = TeamForm()
    return render(request, 'teams/team_form.html', {'form': form, 'title': 'Create Team'})

@login_required
def team_update(request, team_id):
    team = get_object_or_404(Team, id=team_id)
    if request.method == 'POST':
        form = TeamForm(request.POST, instance=team)
        if form.is_valid():
            team = form.save()
            messages.success(request, f'Team {team.name} updated successfully!')
            return redirect('team_detail', team_id=team.id)
    else:
        form = TeamForm(instance=team)
    return render(request, 'teams/team_form.html', {'form': form, 'title': 'Update Team'})

@login_required
def player_create(request, team_id):
    team = get_object_or_404(Team, id=team_id)
    if request.method == 'POST':
        form = PlayerForm(request.POST)
        if form.is_valid():
            player = form.save(commit=False)
            player.team = team
            player.save()
            
            # Create a profile for the new player
            PlayerProfile.objects.create(player=player)
            
            messages.success(request, f'Player {player.name} added to {team.name}!')
            return redirect('team_detail', team_id=team.id)
    else:
        form = PlayerForm()
    return render(request, 'teams/player_form.html', {'form': form, 'team': team, 'title': 'Add Player'})

@login_required
def player_update(request, player_id):
    player = get_object_or_404(Player, id=player_id)
    if request.method == 'POST':
        form = PlayerForm(request.POST, instance=player)
        if form.is_valid():
            player = form.save()
            messages.success(request, f'Player {player.name} updated successfully!')
            return redirect('team_detail', team_id=player.team.id)
    else:
        form = PlayerForm(instance=player)
    return render(request, 'teams/player_form.html', {'form': form, 'team': player.team, 'title': 'Update Player'})

@login_required
def player_delete(request, player_id):
    player = get_object_or_404(Player, id=player_id)
    team_id = player.team.id
    player_name = player.name
    player.delete()
    messages.success(request, f'Player {player_name} deleted successfully!')
    return redirect('team_detail', team_id=team_id)

@login_required
def team_availability_create(request, team_id):
    team = get_object_or_404(Team, id=team_id)
    if request.method == 'POST':
        form = TeamAvailabilityForm(request.POST)
        if form.is_valid():
            availability = form.save(commit=False)
            availability.team = team
            availability.save()
            messages.success(request, f'Availability added for {team.name}!')
            return redirect('team_detail', team_id=team.id)
    else:
        form = TeamAvailabilityForm()
    return render(request, 'teams/team_availability_form.html', {'form': form, 'team': team})

def show_team_pin(request, team_id):
    team = get_object_or_404(Team, id=team_id)
    
    # Check if this is from team creation during player registration
    team_created_info = request.session.get('team_created')
    is_team_creation = team_created_info is not None
    
    # If it's from team creation, clear the session data after use
    if is_team_creation:
        del request.session['team_created']
    
    # For regular admin access, require login
    elif not request.user.is_authenticated:
        messages.error(request, 'You need to be logged in to view team PINs.')
        return redirect('admin:login')
    
    context = {
        'team': team,
        'is_team_creation': is_team_creation,
        'team_created_info': team_created_info
    }
    
    return render(request, 'teams/show_team_pin.html', context)

def team_login(request):
    """Enhanced team login with profile management interface"""
    # Check if team is already logged in
    session_team_id = request.session.get('team_id')
    current_team = None
    
    if session_team_id:
        try:
            current_team = Team.objects.get(id=session_team_id)
            # Get or create team profile
            try:
                profile = current_team.profile
            except:
                from .models import TeamProfile
                profile = TeamProfile.objects.create(team=current_team)
        except Team.DoesNotExist:
            # Clear invalid session
            request.session.pop('team_id', None)
            request.session.pop('team_name', None)
    
    # Handle team login
    if request.method == 'POST' and 'pin' in request.POST:
        pin = request.POST.get('pin')
        action = request.POST.get('action')
        try:
            team = Team.objects.get(pin=pin)
            # Set session data
            request.session['team_id'] = team.id
            request.session['team_name'] = team.name
            
            # Only add welcome message for default action, not for specific redirects
            if action in ['find_next', 'activate', 'submit_score']:
                # For specific actions, redirect without adding welcome message
                # to prevent duplicate messages on the target pages
                pass
            else:
                messages.success(request, f'Welcome, {team.name}!')
            
            # Route to different views based on action
            if action == 'find_next':
                return redirect('team_matches')  # For finding opponents (pending/partially initiated)
            elif action == 'activate':
                return redirect('team_start_match')  # For starting matches
            elif action == 'submit_score':
                return redirect('team_submit_score')  # For submitting scores (active/waiting validation)
            else:
                return redirect('team_login')  # Redirect back to show profile interface
                
        except Team.DoesNotExist:
            # SECURITY FIX: Clear any existing session data on authentication failure
            request.session.pop('team_id', None)
            request.session.pop('team_name', None)
            messages.error(request, 'Invalid PIN. Please try again.')
            # SECURITY FIX: Redirect to HOME PAGE to prevent access to team interface
            return redirect('home')
    
    # Handle profile form submission
    profile_form = None
    badge_form = None
    
    if current_team:
        from .forms import TeamProfileForm, TeamBadgeForm
        
        # Handle profile update
        if request.method == 'POST' and 'update_profile' in request.POST:
            profile_form = TeamProfileForm(request.POST, request.FILES, instance=current_team.profile)
            if profile_form.is_valid():
                profile = profile_form.save()
                profile.update_team_value()  # Update team value after profile changes
                messages.success(request, f'Team profile updated successfully!')
                return redirect('team_login')
        
        # Handle badge addition
        elif request.method == 'POST' and 'add_badge' in request.POST:
            badge_form = TeamBadgeForm(request.POST)
            if badge_form.is_valid():
                badge_type = badge_form.cleaned_data['badge_type']
                custom_name = badge_form.cleaned_data.get('custom_name')
                description = badge_form.cleaned_data.get('description')
                
                badge_name = custom_name if badge_type == 'custom' else badge_type
                badge_data = {'description': description} if description else {}
                
                success = current_team.profile.add_badge(badge_name, badge_data)
                if success:
                    messages.success(request, f'Badge "{badge_name}" added successfully!')
                else:
                    messages.warning(request, f'Badge "{badge_name}" already exists.')
                return redirect('team_login')
        
        # Handle team logout
        elif request.method == 'POST' and 'logout' in request.POST:
            request.session.pop('team_id', None)
            request.session.pop('team_name', None)
            messages.info(request, 'Logged out successfully.')
            return redirect('team_login')
        
        # Initialize forms for display
        if not profile_form:
            profile_form = TeamProfileForm(instance=current_team.profile)
        if not badge_form:
            badge_form = TeamBadgeForm()
    
    context = {
        'current_team': current_team,
        'profile_form': profile_form,
        'badge_form': badge_form,
    }
    
    if current_team:
        context.update({
            'profile': current_team.profile,
            'team_players': current_team.players.all(),
            'badges': current_team.profile.get_badge_display(),
        })
    
    return render(request, 'teams/team_login.html', context)

def public_player_create(request):
    """
    Public player registration with team affiliation options
    """
    if request.method == 'POST':
        form = PublicPlayerForm(request.POST, request.FILES)
        if form.is_valid():
            # Get form data
            name = form.cleaned_data['name']
            codename = form.cleaned_data['codename']
            team_choice = form.cleaned_data['team_choice']
            profile_picture = form.cleaned_data.get('profile_picture')
            
            # Handle team creation if needed
            if team_choice == 'new':
                # Handle profile picture for session storage
                profile_picture_path = None
                if profile_picture:
                    # Save the uploaded file temporarily
                    import os
                    import uuid
                    from django.conf import settings
                    from django.core.files.storage import default_storage
                    
                    # Create a unique filename
                    file_extension = os.path.splitext(profile_picture.name)[1]
                    temp_filename = f"temp_profile_{uuid.uuid4()}{file_extension}"
                    
                    # Save the file temporarily
                    temp_path = default_storage.save(f"temp/{temp_filename}", profile_picture)
                    profile_picture_path = temp_path
                
                # Redirect to team creation with player data in session
                request.session['pending_player'] = {
                    'name': name,
                    'codename': codename,
                    'profile_picture_path': profile_picture_path  # Store file path instead of file object
                }
                messages.info(request, 'Please create your team first, then your player profile will be completed.')
                return redirect('team_create')
            
            # Get the selected team
            if team_choice == 'existing':
                selected_team = form.cleaned_data['existing_team']
            else:  # friendly
                try:
                    selected_team = Team.objects.get(name='Friendly Games')
                except Team.DoesNotExist:
                    # Create the Friendly Games system team if it doesn't exist
                    selected_team = Team.objects.create(
                        name='Friendly Games',
                        pin='000000'  # Special PIN for system team
                    )
                    # Create a profile for the system team
                    from .models import TeamProfile
                    TeamProfile.objects.create(
                        team=selected_team,
                        description='Default team for friendly games and casual players',
                        motto='Play for fun!'
                    )
                    messages.info(request, 'System team "Friendly Games" has been created.')
            
            # Create the player
            player = Player.objects.create(
                name=name,  # Use the actual name entered by the user
                team=selected_team
            )
            
            # Create PlayerCodename entry for login system
            PlayerCodename.objects.create(
                player=player,
                codename=codename
            )
            
            # Create player profile with photo
            player_profile = PlayerProfile.objects.create(
                player=player,
                email='',  # Can be updated later
                skill_level=1,  # Start as beginner
                profile_picture=profile_picture  # Save uploaded photo
            )
            
            # Set session data for player login
            request.session['player_codename'] = codename
            request.session['player_name'] = name
            request.session['player_id'] = player.id
            request.session['team_id'] = selected_team.id
            request.session['team_name'] = selected_team.name
            
            # Success message
            if team_choice == 'friendly':
                messages.success(request, f'Welcome {name}! Your profile has been created and you\'ve joined Friendly Games.')
            else:
                messages.success(request, f'Welcome {name}! Your profile has been created and you\'ve joined {selected_team.name}.')
            
            # Redirect to player profile
            return redirect('player_profile', player_id=player.id)
    
    else:
        form = PublicPlayerForm()
    
    return render(request, 'teams/public_player_create.html', {'form': form})

def team_search_api(request):
    """
    API endpoint for team search functionality
    """
    if request.method == 'GET':
        query = request.GET.get('q', '').strip()
        
        if len(query) < 2:  # Require at least 2 characters
            return JsonResponse({'teams': []})
        
        # Search teams by name (case-insensitive) excluding only Friendly Games
        teams = Team.objects.filter(
            name__icontains=query
        ).exclude(
            name='Friendly Games'
        ).values('id', 'name')[:10]  # Limit to 10 results
        
        return JsonResponse({'teams': list(teams)})
    
    return JsonResponse({'error': 'Invalid request method'}, status=405)

def player_login(request):
    """
    Handle player login with codename
    """
    if request.method == 'POST':
        codename = request.POST.get('codename', '').upper()
        
        try:
            # Find player by codename using PlayerCodename model
            player_codename = PlayerCodename.objects.get(codename=codename)
            player = player_codename.player
            
            # Use CodenameSessionManager to set session properly
            CodenameSessionManager.login_player(request, codename)
            
            # Set additional session data for compatibility
            request.session['player_id'] = player.id
            request.session['team_id'] = player.team.id
            request.session['team_name'] = player.team.name
            
            # AUTO-LOGIN AS TEAM: Automatically log the player in as their team
            # This is crucial for Mêlée events where players are automatically assigned to teams
            # Users don't need to know or enter PINs - the system handles it automatically
            from pfc_core.session_utils import TeamPinSessionManager
            if player.team and player.team.pin:
                TeamPinSessionManager.login_team(request, player.team.pin)
                # Also set team session data for compatibility
                request.session['team_pin'] = player.team.pin
                request.session['team_session_active'] = True
            
            # Return JSON response for AJAX requests
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': True, 
                    'player_name': player.name,
                    'codename': codename
                })
            
            messages.success(request, f'Welcome back, {player.name}!')
            return redirect('player_profile', player_id=player.id)
            
        except PlayerCodename.DoesNotExist:
            # Return JSON response for AJAX requests
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'error': 'Codename not found. Please check your codename or create a new profile.'})
            
            messages.error(request, 'Codename not found. Please check your codename or create a new profile.')
    
    # Return JSON response for AJAX requests
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': False, 'error': 'Invalid request'})
    
    return redirect('home')  # Redirect back to home page

# New views for player statistics
def player_leaderboard(request):
    """
    Display a leaderboard of all players with their statistics
    """
    # Get filter parameters
    team_id = request.GET.get('team')
    skill_level = request.GET.get('skill_level')
    position = request.GET.get('position')
    sort_by = request.GET.get('sort_by', 'win_rate')
    order = request.GET.get('order', 'desc')
    
    # Start with all players that have profiles
    players = Player.objects.filter(profile__isnull=False).select_related('team', 'profile')
    
    # Apply filters
    if team_id:
        players = players.filter(team_id=team_id)
    
    if skill_level:
        players = players.filter(profile__skill_level=skill_level)
    
    if position:
        players = players.filter(profile__preferred_position=position)
    
    # Convert to list and add accurate statistics for each player
    players_with_stats = []
    for player in players:
        try:
            # Get accurate overall statistics
            accurate_stats = player.profile.get_accurate_statistics()
            player.accurate_matches_played = accurate_stats['matches_played']
            player.accurate_matches_won = accurate_stats['matches_won']
            player.accurate_win_rate = accurate_stats['win_rate']
            
            # Get position-based statistics
            position_stats = player.profile.get_position_stats()
            player.position_stats = position_stats
            
            # Calculate best position (position with highest win rate)
            best_position = None
            best_win_rate = 0
            for pos, stats in position_stats.items():
                if stats['matches_played'] > 0 and stats['win_rate'] > best_win_rate:
                    best_position = pos
                    best_win_rate = stats['win_rate']
            
            player.best_position = best_position
            player.best_position_win_rate = best_win_rate
            
            players_with_stats.append(player)
        except Exception:
            # Fallback to stored values if anything goes wrong
            player.accurate_matches_played = player.profile.matches_played
            player.accurate_matches_won = player.profile.matches_won
            player.accurate_win_rate = player.profile.win_rate()
            player.position_stats = {}
            player.best_position = None
            player.best_position_win_rate = 0
            players_with_stats.append(player)
    
    # Apply sorting with accurate statistics
    if sort_by == 'win_rate':
        players_with_stats.sort(
            key=lambda p: p.accurate_win_rate, 
            reverse=(order == 'desc')
        )
    elif sort_by == 'matches_played':
        players_with_stats.sort(
            key=lambda p: p.accurate_matches_played, 
            reverse=(order == 'desc')
        )
    elif sort_by == 'matches_won':
        players_with_stats.sort(
            key=lambda p: p.accurate_matches_won, 
            reverse=(order == 'desc')
        )
    elif sort_by == 'best_position_win_rate':
        players_with_stats.sort(
            key=lambda p: p.best_position_win_rate, 
            reverse=(order == 'desc')
        )
    else:
        # For other fields, use the original sorting
        order_prefix = '-' if order == 'desc' else ''
        sort_field = f"{order_prefix}profile__{sort_by}"
        players_with_stats = list(Player.objects.filter(
            profile__isnull=False
        ).select_related('team', 'profile').order_by(sort_field))
        
        # Still need to add accurate stats for display
        for player in players_with_stats:
            try:
                accurate_stats = player.profile.get_accurate_statistics()
                player.accurate_matches_played = accurate_stats['matches_played']
                player.accurate_matches_won = accurate_stats['matches_won']
                player.accurate_win_rate = accurate_stats['win_rate']
                
                position_stats = player.profile.get_position_stats()
                player.position_stats = position_stats
                
                best_position = None
                best_win_rate = 0
                for pos, stats in position_stats.items():
                    if stats['matches_played'] > 0 and stats['win_rate'] > best_win_rate:
                        best_position = pos
                        best_win_rate = stats['win_rate']
                
                player.best_position = best_position
                player.best_position_win_rate = best_win_rate
            except Exception:
                player.accurate_matches_played = player.profile.matches_played
                player.accurate_matches_won = player.profile.matches_won
                player.accurate_win_rate = player.profile.win_rate()
                player.position_stats = {}
                player.best_position = None
                player.best_position_win_rate = 0
    
    # Create position-specific leaderboards
    position_leaderboards = {}
    positions = ['pointer', 'milieu', 'tirer', 'flex']  # Use lowercase to match MatchPlayer.role choices
    position_display_names = {
        'pointer': 'Pointer',
        'milieu': 'Milieu', 
        'tirer': 'Shooter',
        'flex': 'Flex'
    }
    
    for pos in positions:
        position_players = []
        for player in players_with_stats:
            if pos in player.position_stats and player.position_stats[pos]['matches_played'] > 0:
                # Create a copy of player with position-specific stats
                pos_player = type('obj', (object,), {
                    'id': player.id,
                    'name': player.name,
                    'team': player.team,
                    'profile': player.profile,
                    'is_captain': getattr(player, 'is_captain', False),
                    'position': position_display_names[pos],
                    'matches_played': player.position_stats[pos]['matches_played'],
                    'matches_won': player.position_stats[pos]['matches_won'],
                    'win_rate': player.position_stats[pos]['win_rate']
                })()
                position_players.append(pos_player)
        
        # Sort by win rate for this position
        position_players.sort(key=lambda p: p.win_rate, reverse=True)
        position_leaderboards[position_display_names[pos]] = position_players
    
    # Get all teams for the filter dropdown (include all teams for player statistics)
    teams = Team.objects.all().order_by('name')
    
    context = {
        'players': players_with_stats,
        'position_leaderboards': position_leaderboards,
        'teams': teams,
        'selected_team': int(team_id) if team_id else None,
        'selected_skill_level': int(skill_level) if skill_level else None,
        'selected_position': position,
        'sort_by': sort_by,
        'order': order,
    }
    
    return render(request, 'teams/player_leaderboard.html', context)

def player_profile(request, player_id):
    """
    Display detailed profile and statistics for a specific player
    """
    player = get_object_or_404(Player.objects.select_related('team', 'profile'), id=player_id)
    
    # Get player's tournament match history (for Overall tab)
    # Include matches from current team AND any Mêlée teams the player participated in
    from tournaments.models import MeleePlayer
    
    # Get all teams this player has been part of (including Mêlée teams)
    player_teams = [player.team]  # Current team
    
    # Add any Mêlée teams from tournament history
    melee_registrations = MeleePlayer.objects.filter(player=player).select_related('tournament')
    for melee_reg in melee_registrations:
        # Find Mêlée teams created for this tournament
        from tournaments.models import TournamentTeam
        tournament_teams = TournamentTeam.objects.filter(
            tournament=melee_reg.tournament
        ).select_related('team')
        
        for tt in tournament_teams:
            if 'Mêlée Team' in tt.team.name:
                player_teams.append(tt.team)
    
    # Remove duplicates
    player_teams = list(set(player_teams))
    
    # Get matches where any of these teams participated
    team_queries = Q()
    for team in player_teams:
        team_queries |= Q(team1=team) | Q(team2=team)
    
    # Get only matches where the player actually participated
    try:
        from matches.models_participant import TeamMatchParticipant
        
        # Get matches where player has participation records
        participated_match_ids = TeamMatchParticipant.objects.filter(
            player=player,
            played=True
        ).values_list('match_id', flat=True)
        
        tournament_matches = Match.objects.filter(
            id__in=participated_match_ids,
            status='completed'  # Only show completed matches
        ).select_related('team1', 'team2', 'tournament', 'round').order_by('-end_time')
        
        # Add position information from TeamMatchParticipant records
        for match in tournament_matches:
            try:
                participant = TeamMatchParticipant.objects.get(match=match, player=player)
                match.position = participant.get_position_display()
            except TeamMatchParticipant.DoesNotExist:
                match.position = "N/A"
        
    except ImportError:
        # Fallback to old method if TeamMatchParticipant not available
        tournament_matches = Match.objects.filter(
            team_queries,
            status='completed'  # Only show completed matches
        ).select_related('team1', 'team2', 'tournament', 'round').order_by('-end_time')
    
    # Get friendly game matches (for Friendly Games tab)
    friendly_matches = []
    try:
        from friendly_games.models import FriendlyGame, FriendlyGamePlayer
        
        # Get friendly games where this player participated
        friendly_game_players = FriendlyGamePlayer.objects.filter(
            player=player,
            codename_verified=True,
            game__status='COMPLETED'
        ).select_related('game').order_by('-game__created_at')
        
        # Use the working version's data structure
        for fgp in friendly_game_players:
            game = fgp.game
            friendly_matches.append({
                'match_number': game.match_number,
                'date': game.created_at,
                'team': fgp.team,
                'position': fgp.position,
                'black_score': game.black_team_score,
                'white_score': game.white_team_score,
                'won': fgp.games_won > 0,
                'validation_status': game.validation_status,
                'game_name': game.name,
                'game_id': game.id
            })
    except ImportError:
        # If friendly games app is not available, use empty list
        friendly_matches = []
    
    # Get accurate statistics (safely synced)
    accurate_stats = {}
    try:
        if hasattr(player, 'profile'):
            accurate_stats = player.profile.get_accurate_statistics()
        else:
            accurate_stats = {'matches_played': 0, 'matches_won': 0, 'win_rate': 0}
    except Exception:
        accurate_stats = {'matches_played': 0, 'matches_won': 0, 'win_rate': 0}
    
    # Enhanced statistics (safe, backward-compatible)
    enhanced_stats = {}
    try:
        if hasattr(player, 'profile') and player.profile.has_enhanced_stats():
            enhanced_stats = {
                'position_stats': player.profile.get_position_stats(),
                'format_stats': player.profile.get_format_stats(),
                'role_distribution': player.profile.get_role_distribution(),
                'has_data': True,
                'recent_matches': get_recent_matches_with_participation(player, tournament_matches[:10])
            }
        else:
            enhanced_stats = {
                'has_data': False,
                'recent_matches': get_recent_matches_with_participation(player, tournament_matches[:10])
            }
    except Exception:
        enhanced_stats = {
            'has_data': False,
            'recent_matches': get_recent_matches_with_participation(player, tournament_matches[:10])
        }
    
    # Get friendly game statistics
    friendly_stats = {}
    friendly_position_stats = {}
    friendly_role_distribution = {}
    friendly_matches = []
    try:
        from friendly_games.models import FriendlyGameStatistics, FriendlyGame, FriendlyGamePlayer
        from django.db import models
        
        # Get friendly game statistics
        friendly_stats_obj, created = FriendlyGameStatistics.objects.get_or_create(player=player)
        if not created:
            friendly_stats_obj.update_statistics()  # Ensure stats are current
        
        friendly_stats = {
            'total_games': friendly_stats_obj.total_games,
            'total_wins': friendly_stats_obj.total_wins,
            'total_losses': friendly_stats_obj.total_losses,
            'win_rate': friendly_stats_obj.win_rate
        }
        
        # Get friendly game position statistics
        friendly_position_stats = {}
        friendly_game_players = FriendlyGamePlayer.objects.filter(
            player=player,
            codename_verified=True,
            game__status='COMPLETED'
        ).select_related('game')
        
        # Calculate position-specific stats
        positions = ['TIRER', 'POINTEUR', 'MILIEU']
        for position in positions:
            position_games = friendly_game_players.filter(position=position)
            total_games = position_games.count()
            total_wins = position_games.aggregate(total=models.Sum('games_won'))['total'] or 0
            
            if total_games > 0:
                win_rate = round((total_wins / total_games) * 100, 1)
            else:
                win_rate = 0
                
            friendly_position_stats[position] = {
                'matches_played': total_games,
                'matches_won': total_wins,
                'win_rate': win_rate
            }
        
        # Calculate role distribution for friendly games
        friendly_role_distribution = {}
        total_friendly_games = friendly_game_players.count()
        if total_friendly_games > 0:
            for position in positions:
                position_count = friendly_game_players.filter(position=position).count()
                percentage = round((position_count / total_friendly_games) * 100, 1)
                friendly_role_distribution[position] = {
                    'count': position_count,
                    'percentage': percentage
                }
        
        # Get friendly match history for this player
        friendly_matches = []
        for fgp in friendly_game_players.order_by('-game__created_at'):
            game = fgp.game
            friendly_matches.append({
                'match_number': game.match_number,
                'date': game.created_at,
                'team': fgp.team,
                'position': fgp.position,
                'black_score': game.black_team_score,
                'white_score': game.white_team_score,
                'won': fgp.games_won > 0,
                'validation_status': game.validation_status,
                'game_name': game.name,
                'game_id': game.id
            })
    except Exception as e:
        # If friendly games app is not available or there's an error, use empty stats
        friendly_stats = {'total_games': 0, 'total_wins': 0, 'total_losses': 0, 'win_rate': 0}
        friendly_position_stats = {}
        friendly_role_distribution = {}
        friendly_matches = []
    
    # Calculate OVERALL statistics (tournament + friendly games combined)
    # This provides comprehensive statistics for the Overall tab
    try:
        # Tournament statistics (from existing accurate_stats)
        tournament_matches_played = accurate_stats.get('matches_played', 0)
        tournament_matches_won = accurate_stats.get('matches_won', 0)
        
        # Friendly game statistics
        friendly_matches_played = friendly_stats.get('total_games', 0)
        friendly_matches_won = friendly_stats.get('total_wins', 0)
        
        # Combined totals for Overall tab
        overall_matches_played = tournament_matches_played + friendly_matches_played
        overall_matches_won = tournament_matches_won + friendly_matches_won
        
        # Calculate overall win rate
        if overall_matches_played > 0:
            overall_win_rate = round((overall_matches_won / overall_matches_played) * 100, 1)
        else:
            overall_win_rate = 0
            
        # Create overall statistics dictionary
        overall_stats = {
            'matches_played': overall_matches_played,
            'matches_won': overall_matches_won,
            'matches_lost': overall_matches_played - overall_matches_won,
            'win_rate': overall_win_rate
        }
    except Exception:
        # Fallback to tournament-only stats if there's any error
        overall_stats = {
            'matches_played': accurate_stats.get('matches_played', 0),
            'matches_won': accurate_stats.get('matches_won', 0),
            'win_rate': accurate_stats.get('win_rate', 0)
        }
    
    # Calculate bell curve data for skill comparison
    bell_curve_data = {}
    try:
        if hasattr(player, 'profile') and player.profile:
            # Import the single source of truth for thresholds
            from .rating_thresholds import get_all_categories, get_player_category, get_category_color
            
            # Get all player profiles with ratings
            all_profiles = PlayerProfile.objects.exclude(value__isnull=True).exclude(value=0)
            if all_profiles.count() > 0:
                # Get current player's rating
                current_rating = float(player.profile.value)
                
                # Get current player's category
                current_player_category = get_player_category(current_rating)
                
                # Get all ratings for distribution calculation
                all_ratings = [float(p.value) for p in all_profiles]
                all_ratings.sort()
                
                # Calculate percentile (how many players have lower rating)
                lower_count = sum(1 for rating in all_ratings if rating < current_rating)
                percentile = round((lower_count / len(all_ratings)) * 100, 1)
                
                # Get all categories with correct thresholds
                categories = get_all_categories()
                
                # Create histogram data for global player distribution
                import numpy as np
                
                # Create histogram bins - use 20 bins for good granularity
                min_rating = min(all_ratings)
                max_rating = max(all_ratings)
                
                # Ensure we have a reasonable range
                rating_range = max_rating - min_rating
                if rating_range < 50:
                    # Expand range if too narrow
                    padding = (50 - rating_range) / 2
                    min_rating -= padding
                    max_rating += padding
                
                # Create 20 bins for histogram
                bins = np.linspace(min_rating, max_rating, 21)  # 21 edges = 20 bins
                hist_counts, bin_edges = np.histogram(all_ratings, bins=bins)
                
                # Create histogram data for chart with proper positioning
                histogram_data = []
                max_count = max(hist_counts) if len(hist_counts) > 0 else 1
                
                for i in range(len(hist_counts)):
                    bin_start = bin_edges[i]
                    bin_end = bin_edges[i + 1]
                    count = int(hist_counts[i])
                    
                    # Calculate positions for SVG (800px wide chart, 20px margins)
                    x_pos = 20 + ((bin_start - min_rating) / (max_rating - min_rating)) * 760
                    width = ((bin_end - bin_start) / (max_rating - min_rating)) * 760
                    height = (count / max_count) * 100 if count > 0 else 0  # Max height 100px
                    y_pos = 160 - height  # Start from bottom (y=160) and go up
                    
                    histogram_data.append({
                        'bin_start': round(bin_start, 1),
                        'bin_end': round(bin_end, 1),
                        'count': count,
                        'x_pos': x_pos,
                        'y_pos': y_pos,
                        'width': width,
                        'height': height
                    })
                
                # Calculate current player position
                current_player_x = 20 + ((current_rating - min_rating) / (max_rating - min_rating)) * 760
                
                # Create category bands with proper positioning
                category_bands = []
                for category in categories:
                    # Calculate band positions
                    band_min = max(category['min'], min_rating)
                    band_max = min(category['max'] if category['max'] != float('inf') else max_rating + 50, max_rating + 50)
                    
                    if band_min <= max_rating:
                        x_start = 20 + ((band_min - min_rating) / (max_rating - min_rating)) * 760
                        x_end = 20 + ((band_max - min_rating) / (max_rating - min_rating)) * 760
                        
                        category_bands.append({
                            'key': category['key'],
                            'display_name': category['display_name'],
                            'min': category['min'],
                            'max': category['max'],
                            'x_start': x_start,
                            'x_end': x_end,
                            'width': x_end - x_start,
                            'label_x': (x_start + x_end) / 2,
                            'color': category['color']
                        })
                
                # Calculate average rating
                avg_rating = round(sum(all_ratings) / len(all_ratings), 1)
                
                bell_curve_data = {
                    'current_rating': current_rating,
                    'current_player_x': current_player_x,
                    'current_player_category': current_player_category,
                    'percentile': percentile,
                    'avg_rating': avg_rating,
                    'min_rating': min_rating,
                    'max_rating': max_rating,
                    'total_players': len(all_ratings),
                    'histogram_data': histogram_data,
                    'categories': category_bands,
                    'has_data': True
                }
            else:
                bell_curve_data = {'has_data': False}
        else:
            bell_curve_data = {'has_data': False}
    except Exception:
        bell_curve_data = {'has_data': False}
    
    # Prepare rating history data for chart
    rating_chart_data = {'has_data': False}
    try:
        if hasattr(player, 'profile') and player.profile and player.profile.rating_history:
            import json
            from datetime import datetime
            
            history = player.profile.rating_history
            if history and len(history) > 0:
                # Prepare data for Chart.js
                labels = []  # Timestamps
                ratings = []  # Rating values
                
                # Add starting point (100.0)
                labels.append('Start')
                ratings.append(100.0)
                
                # Add each rating change
                for i, entry in enumerate(history):
                    # Format timestamp
                    try:
                        timestamp = entry.get('timestamp', '')
                        if timestamp:
                            dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                            label = dt.strftime('%b %d, %Y')
                        else:
                            label = f'Match {i+1}'
                    except:
                        label = f'Match {i+1}'
                    
                    labels.append(label)
                    ratings.append(entry.get('new_value', 100.0))
                
                rating_chart_data = {
                    'has_data': True,
                    'labels': json.dumps(labels),
                    'ratings': json.dumps(ratings),
                    'current_rating': player.profile.value,
                    'starting_rating': 100.0,
                    'total_change': player.profile.value - 100.0,
                    'total_matches': len(history)
                }
    except Exception as e:
        rating_chart_data = {'has_data': False}
    
    context = {
        'player': player,
        'matches': tournament_matches,  # Tournament matches for match history table
        'friendly_matches': friendly_matches,  # Friendly matches with working data structure
        'accurate_stats': accurate_stats,  # Tournament statistics (unchanged)
        'enhanced_stats': enhanced_stats,  # Enhanced data, safely added
        'friendly_stats': friendly_stats,  # Friendly game statistics
        'overall_stats': overall_stats,  # NEW: Combined overall statistics
        'friendly_position_stats': friendly_position_stats,  # Friendly game position stats
        'friendly_role_distribution': friendly_role_distribution,  # Friendly game role distribution
        'bell_curve_data': bell_curve_data,  # NEW: Bell curve skill comparison data
        'rating_chart_data': rating_chart_data,  # NEW: Rating progression chart data
        'tracker_enabled': True,  # Enable shooting practice tracker tab
    }
    
    return render(request, 'teams/player_profile.html', context)


def team_matches(request):
    """
    Display available matches for the logged-in team, prioritizing partially initiated matches
    """
    team_id = request.session.get('team_id')
    if not team_id:
        messages.error(request, 'Please enter your team PIN first.')
        return redirect('team_login')
    
    try:
        team = Team.objects.get(id=team_id)
    except Team.DoesNotExist:
        messages.error(request, 'Invalid team session. Please login again.')
        return redirect('team_login')
    
    # Get only matches that are available to start (not active or completed)
    team_matches_query = Match.objects.filter(
        Q(team1=team) | Q(team2=team)
    ).filter(
        status__in=['pending', 'pending_verification']  # Only matches that can be started
    ).select_related('team1', 'team2', 'tournament', 'court').prefetch_related('activations')
    
    # Categorize matches by priority for finding opponents
    partially_initiated = []
    pending_matches = []
    
    for match in team_matches_query:
        if match.status == 'pending_verification':
            # This is a partially initiated match - highest priority (someone is waiting)
            partially_initiated.append(match)
        elif match.status == 'pending':
            # This is a pending match - lower priority (not started yet)
            pending_matches.append(match)
    
    # Create prioritized list: partially initiated first (highest priority), then pending
    prioritized_matches = partially_initiated + pending_matches
    
    # Mark the first match as system recommendation
    system_recommendation = prioritized_matches[0] if prioritized_matches else None
    
    context = {
        'team': team,
        'system_recommendation': system_recommendation,
        'partially_initiated': partially_initiated,
        'pending_matches': pending_matches,
        'all_matches': prioritized_matches,
        'has_matches': bool(prioritized_matches),
    }
    
    return render(request, 'teams/team_matches.html', context)


def team_submit_score(request):
    """
    Display active matches and matches waiting validation for score submission
    """
    team_id = request.session.get('team_id')
    if not team_id:
        messages.error(request, 'Please enter your team PIN first.')
        return redirect('team_login')
    
    try:
        team = Team.objects.get(id=team_id)
    except Team.DoesNotExist:
        messages.error(request, 'Invalid team session. Please login again.')
        return redirect('team_login')
    
    # Get matches that need score submission (active and waiting validation)
    team_matches_query = Match.objects.filter(
        Q(team1=team) | Q(team2=team)
    ).filter(
        status__in=['active', 'waiting_validation']  # Only matches that need score submission
    ).select_related('team1', 'team2', 'tournament', 'court').prefetch_related('activations')
    
    # Categorize matches by status
    active_matches = []
    waiting_validation = []
    
    for match in team_matches_query:
        if match.status == 'active':
            active_matches.append(match)
        elif match.status == 'waiting_validation':
            waiting_validation.append(match)
    
    # Create prioritized list: waiting validation first (more urgent), then active matches
    prioritized_matches = waiting_validation + active_matches
    
    # Mark the first match as system recommendation
    system_recommendation = prioritized_matches[0] if prioritized_matches else None
    
    context = {
        'team': team,
        'system_recommendation': system_recommendation,
        'active_matches': active_matches,
        'waiting_validation': waiting_validation,
        'all_matches': prioritized_matches,
        'has_matches': bool(prioritized_matches),
    }
    
    return render(request, 'teams/team_submit_score.html', context)



def friendly_games_leaderboard(request):
    """
    Friendly Games Leaderboard with Trophy System
    Shows only fully validated games and includes trophy recognition
    """
    from django.shortcuts import render
    from django.db.models import Count, Sum, Case, When, IntegerField, FloatField, F
    from django.db.models.functions import Coalesce
    
    try:
        from friendly_games.models import FriendlyGamePlayer, FriendlyGame
        
        # Get filter parameters
        position_filter = request.GET.get('position', 'all')
        format_filter = request.GET.get('format', 'all')
        
        # Base query for fully validated games only
        base_query = FriendlyGamePlayer.objects.filter(
            game__validation_status="FULLY_VALIDATED",
            game__status="COMPLETED",
            codename_verified=True
        )
        
        # Apply position filter
        if position_filter != 'all':
            base_query = base_query.filter(position=position_filter.upper())
        
        # Calculate player statistics with dynamic win/loss calculation
        player_stats = base_query.values('player__id', 'player__name').annotate(
            games_played=Count('id'),
            games_won=Sum(
                Case(
                    # Player on BLACK team and BLACK team won
                    When(
                        team='BLACK',
                        game__black_team_score__gt=F('game__white_team_score'),
                        then=1
                    ),
                    # Player on WHITE team and WHITE team won
                    When(
                        team='WHITE',
                        game__white_team_score__gt=F('game__black_team_score'),
                        then=1
                    ),
                    default=0,
                    output_field=IntegerField()
                )
            ),
            games_lost=Sum(
                Case(
                    # Player on BLACK team and BLACK team lost
                    When(
                        team='BLACK',
                        game__black_team_score__lt=F('game__white_team_score'),
                        then=1
                    ),
                    # Player on WHITE team and WHITE team lost
                    When(
                        team='WHITE',
                        game__white_team_score__lt=F('game__black_team_score'),
                        then=1
                    ),
                    default=0,
                    output_field=IntegerField()
                )
            ),
            win_rate=Case(
                When(games_played=0, then=0),
                default=F('games_won') * 100.0 / F('games_played'),
                output_field=FloatField()
            )
        ).filter(games_played__gt=0).order_by('-games_played', '-win_rate')
        
        # Calculate trophy winners
        trophies = calculate_friendly_game_trophies()
        
        # Calculate position-specific leaderboards
        position_leaderboards = calculate_position_leaderboards()
        
        # Prepare context
        context = {
            'player_stats': player_stats,
            'trophies': trophies,
            'position_leaderboards': position_leaderboards,
            'position_filter': position_filter,
            'format_filter': format_filter,
            'total_players': player_stats.count(),
            'page_title': 'Friendly Games Leaderboard',
        }
        
        return render(request, 'teams/friendly_games_leaderboard.html', context)
        
    except ImportError:
        # Friendly games not available
        context = {
            'error': 'Friendly games module not available',
            'page_title': 'Friendly Games Leaderboard',
        }
        return render(request, 'teams/friendly_games_leaderboard.html', context)


def calculate_friendly_game_trophies():
    """
    Calculate trophy winners for friendly games leaderboard
    """
    try:
        from friendly_games.models import FriendlyGamePlayer
        from django.db.models import Count, Sum, Case, When, FloatField, F, IntegerField
        from django.db.models.functions import Coalesce
        
        # Base query for fully validated games
        base_query = FriendlyGamePlayer.objects.filter(
            game__validation_status="FULLY_VALIDATED",
            game__status="COMPLETED",
            codename_verified=True
        )
        
        # Most Active Players (Star Trophies)
        most_active = base_query.values('player__id', 'player__name').annotate(
            games_played=Count('id')
        ).filter(games_played__gt=0).order_by('-games_played')[:3]
        
        # Best Shooter Players (minimum 50 entries required)
        best_shooters = base_query.filter(position="TIRER").values('player__id', 'player__name').annotate(
            games_played=Count('id'),
            games_won=Sum(
                Case(
                    # Player on BLACK team and BLACK team won
                    When(
                        team='BLACK',
                        game__black_team_score__gt=F('game__white_team_score'),
                        then=1
                    ),
                    # Player on WHITE team and WHITE team won
                    When(
                        team='WHITE',
                        game__white_team_score__gt=F('game__black_team_score'),
                        then=1
                    ),
                    default=0,
                    output_field=IntegerField()
                )
            ),
            win_rate=Case(
                When(games_played=0, then=0),
                default=F('games_won') * 100.0 / F('games_played'),
                output_field=FloatField()
            )
        ).filter(games_played__gte=50).order_by('-win_rate', '-games_played')[:3]
        
        # Best Pointer Players (minimum 50 entries required)
        best_pointers = base_query.filter(position="POINTEUR").values('player__id', 'player__name').annotate(
            games_played=Count('id'),
            games_won=Sum(
                Case(
                    # Player on BLACK team and BLACK team won
                    When(
                        team='BLACK',
                        game__black_team_score__gt=F('game__white_team_score'),
                        then=1
                    ),
                    # Player on WHITE team and WHITE team won
                    When(
                        team='WHITE',
                        game__white_team_score__gt=F('game__black_team_score'),
                        then=1
                    ),
                    default=0,
                    output_field=IntegerField()
                )
            ),
            win_rate=Case(
                When(games_played=0, then=0),
                default=F('games_won') * 100.0 / F('games_played'),
                output_field=FloatField()
            )
        ).filter(games_played__gte=50).order_by('-win_rate', '-games_played')[:3]
        
        return {
            'most_active': list(most_active),
            'best_shooters': list(best_shooters),
            'best_pointers': list(best_pointers),
        }
        
    except ImportError:
        return {
            'most_active': [],
            'best_shooters': [],
            'best_pointers': [],
        }


def calculate_position_leaderboards():
    """
    Calculate position-specific leaderboards for friendly games
    """
    try:
        from friendly_games.models import FriendlyGamePlayer
        from django.db.models import Count, Sum, Case, When, FloatField, F, IntegerField
        
        # Base query for fully validated games
        base_query = FriendlyGamePlayer.objects.filter(
            game__validation_status="FULLY_VALIDATED",
            game__status="COMPLETED",
            codename_verified=True
        )
        
        # Position-specific leaderboards
        positions = {
            'POINTEUR': 'Pointer',
            'TIRER': 'Shooter', 
            'MILIEU': 'Milieu'
        }
        
        leaderboards = {}
        
        for position_code, position_name in positions.items():
            position_stats = base_query.filter(position=position_code).values('player__id', 'player__name').annotate(
                games_played=Count('id'),
                games_won=Sum(
                    Case(
                        # Player on BLACK team and BLACK team won
                        When(
                            team='BLACK',
                            game__black_team_score__gt=F('game__white_team_score'),
                            then=1
                        ),
                        # Player on WHITE team and WHITE team won
                        When(
                            team='WHITE',
                            game__white_team_score__gt=F('game__black_team_score'),
                            then=1
                        ),
                        default=0,
                        output_field=IntegerField()
                    )
                ),
                games_lost=Sum(
                    Case(
                        # Player on BLACK team and BLACK team lost
                        When(
                            team='BLACK',
                            game__black_team_score__lt=F('game__white_team_score'),
                            then=1
                        ),
                        # Player on WHITE team and WHITE team lost
                        When(
                            team='WHITE',
                            game__white_team_score__lt=F('game__black_team_score'),
                            then=1
                        ),
                        default=0,
                        output_field=IntegerField()
                    )
                ),
                win_rate=Case(
                    When(games_played=0, then=0),
                    default=F('games_won') * 100.0 / F('games_played'),
                    output_field=FloatField()
                )
            ).filter(games_played__gt=0).order_by('-win_rate', '-games_played')[:10]
            
            leaderboards[position_code.lower()] = {
                'name': position_name,
                'players': list(position_stats)
            }
        
        return leaderboards
        
    except ImportError:
        return {
            'pointeur': {'name': 'Pointer', 'players': []},
            'tirer': {'name': 'Shooter', 'players': []},
            'milieu': {'name': 'Milieu', 'players': []}
        }


# ===== TEAM PROFILE MANAGEMENT VIEWS =====

def team_profile_view(request, team_id):
    """
    View team profile with access control logic:
    - If team has captain: only captain can edit
    - If team has no captain: any team player can edit
    """
    team = get_object_or_404(Team, id=team_id)
    
    # Get or create team profile
    try:
        profile = team.profile
    except:
        from .models import TeamProfile
        profile = TeamProfile.objects.create(team=team)
    
    # Check access permissions
    can_edit = check_team_profile_access(request, team)
    
    context = {
        'team': team,
        'profile': profile,
        'can_edit': can_edit,
        'team_players': team.players.all(),
        'captain': team.players.filter(is_captain=True).first(),
    }
    
    return render(request, 'teams/team_profile.html', context)

def team_profile_edit(request, team_id):
    """
    Edit team profile with access control
    """
    team = get_object_or_404(Team, id=team_id)
    
    # Check access permissions
    if not check_team_profile_access(request, team):
        messages.error(request, 'You do not have permission to edit this team profile.')
        return redirect('team_profile_view', team_id=team_id)
    
    # Get or create team profile
    try:
        profile = team.profile
    except:
        from .models import TeamProfile
        profile = TeamProfile.objects.create(team=team)
    
    if request.method == 'POST':
        from .forms import TeamProfileForm
        form = TeamProfileForm(request.POST, request.FILES, instance=profile)
        if form.is_valid():
            profile = form.save()
            
            # Update team value based on current roster
            profile.update_team_value()
            
            messages.success(request, f'Team profile for {team.name} updated successfully!')
            return redirect('team_profile_view', team_id=team_id)
    else:
        from .forms import TeamProfileForm
        form = TeamProfileForm(instance=profile)
    
    context = {
        'team': team,
        'profile': profile,
        'form': form,
        'captain': team.players.filter(is_captain=True).first(),
    }
    
    return render(request, 'teams/team_profile_edit.html', context)

def check_team_profile_access(request, team):
    """
    Simplified access control: if team is logged in with PIN, they can edit profile
    """
    # Check if team is logged in via team session
    session_team_id = request.session.get('team_id')
    if session_team_id and int(session_team_id) == team.id:
        return True
    
    # Staff users can always edit (for admin purposes)
    if hasattr(request, 'user') and request.user.is_authenticated and request.user.is_staff:
        return True
    
    return False

def team_management_interface(request, team_id):
    """
    Main team management interface (future implementation)
    This will be the interface described in the requirements for:
    - Sub-team creation
    - Player management (add/remove from Friendly Team)
    - Team roster management
    """
    team = get_object_or_404(Team, id=team_id)
    
    # Check access permissions
    if not check_team_profile_access(request, team):
        messages.error(request, 'You do not have permission to access team management.')
        return redirect('team_profile_view', team_id=team_id)
    
    # Get or create team profile
    try:
        profile = team.profile
    except:
        from .models import TeamProfile
        profile = TeamProfile.objects.create(team=team)
    
    # Get Friendly Team for player transfers
    friendly_team = None
    try:
        friendly_team = Team.objects.get(name='Friendly Team')
    except Team.DoesNotExist:
        # Try other common names
        for name in ['Friendly Games', 'Unassigned Players', 'Free Agents']:
            try:
                friendly_team = Team.objects.get(name=name)
                break
            except Team.DoesNotExist:
                continue
    
    context = {
        'team': team,
        'profile': profile,
        'team_players': team.players.all(),
        'captain': team.players.filter(is_captain=True).first(),
        'sub_teams': team.subteams.all() if not team.is_subteam else [],
        'friendly_team': friendly_team,
        'friendly_players': friendly_team.players.all() if friendly_team else [],
        'can_edit': True,  # Already checked access above
    }
    
    return render(request, 'teams/team_management.html', context)

def add_team_badge(request, team_id):
    """
    Add a badge to team profile (AJAX endpoint)
    """
    if request.method == 'POST' and request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        team = get_object_or_404(Team, id=team_id)
        
        # Check access permissions
        if not check_team_profile_access(request, team):
            return JsonResponse({'success': False, 'error': 'Permission denied'})
        
        badge_name = request.POST.get('badge_name')
        badge_data = request.POST.get('badge_data', {})
        
        try:
            profile = team.profile
            success = profile.add_badge(badge_name, badge_data)
            
            if success:
                return JsonResponse({
                    'success': True, 
                    'message': f'Badge "{badge_name}" added successfully!'
                })
            else:
                return JsonResponse({
                    'success': False, 
                    'error': 'Badge already exists or could not be added'
                })
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    
    return JsonResponse({'success': False, 'error': 'Invalid request'})

def update_team_value(request, team_id):
    """
    Manually update team value based on current roster (AJAX endpoint)
    """
    if request.method == 'POST' and request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        team = get_object_or_404(Team, id=team_id)
        
        # Check access permissions
        if not check_team_profile_access(request, team):
            return JsonResponse({'success': False, 'error': 'Permission denied'})
        
        try:
            profile = team.profile
            success = profile.update_team_value()
            
            if success:
                return JsonResponse({
                    'success': True,
                    'new_value': profile.team_value,
                    'level': profile.level,
                    'level_display': profile.get_level_display()[0]
                })
            else:
                return JsonResponse({
                    'success': False,
                    'error': 'No significant change in team value'
                })
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    
    return JsonResponse({'success': False, 'error': 'Invalid request'})


# ===== TEAM MANAGEMENT VIEWS =====

def team_management_dashboard(request):
    """
    Enhanced team login with comprehensive team management interface
    Handles profile management, sub-teams, and player management
    """
    # Check if team is already logged in
    session_team_id = request.session.get('team_id')
    current_team = None
    
    if session_team_id:
        try:
            current_team = Team.objects.get(id=session_team_id)
            # Get or create team profile
            try:
                profile = current_team.profile
            except:
                from .models import TeamProfile
                profile = TeamProfile.objects.create(team=current_team)
        except Team.DoesNotExist:
            # Clear invalid session
            request.session.pop('team_id', None)
            request.session.pop('team_name', None)
    
    # Handle team login
    if request.method == 'POST' and 'pin' in request.POST:
        pin = request.POST.get('pin')
        action = request.POST.get('action')
        try:
            team = Team.objects.get(pin=pin)
            # Set session data
            request.session['team_id'] = team.id
            request.session['team_name'] = team.name
            
            # Only add welcome message for default action
            if action not in ['find_next', 'activate', 'submit_score']:
                messages.success(request, f'Welcome to {team.name} Team Management!')
            
            # Route to different views based on action
            if action == 'find_next':
                return redirect('team_matches')
            elif action == 'activate':
                return redirect('team_start_match')
            elif action == 'submit_score':
                return redirect('team_submit_score')
            else:
                return redirect('team_management_dashboard')
                
        except Team.DoesNotExist:
            messages.error(request, 'Invalid PIN. Please try again.')
    
    # Initialize all forms
    profile_form = None
    badge_form = None
    sub_team_form = None
    recruitment_form = None
    release_form = None
    
    if current_team:
        from .forms import (TeamProfileForm, TeamBadgeForm, SubTeamForm, 
                           PlayerRecruitmentForm, PlayerReleaseForm)
        
        # Handle profile form submission
        if request.method == 'POST' and 'update_profile' in request.POST:
            profile_form = TeamProfileForm(request.POST, request.FILES, instance=current_team.profile)
            if profile_form.is_valid():
                profile = profile_form.save()
                profile.update_team_value()
                messages.success(request, 'Team profile updated successfully!')
                return redirect('team_management_dashboard')
        
        # Handle badge addition
        elif request.method == 'POST' and 'add_badge' in request.POST:
            badge_form = TeamBadgeForm(request.POST)
            if badge_form.is_valid():
                badge_type = badge_form.cleaned_data['badge_type']
                custom_name = badge_form.cleaned_data.get('custom_name')
                description = badge_form.cleaned_data.get('description')
                
                badge_name = custom_name if badge_type == 'custom' else badge_type
                badge_data = {'description': description} if description else {}
                
                success = current_team.profile.add_badge(badge_name, badge_data)
                if success:
                    messages.success(request, f'Badge "{badge_name}" added successfully!')
                else:
                    messages.warning(request, f'Badge "{badge_name}" already exists.')
                return redirect('team_management_dashboard')
        
        # Handle sub-team creation
        elif request.method == 'POST' and 'create_sub_team' in request.POST:
            sub_team_form = SubTeamForm(request.POST, parent_team=current_team)
            if sub_team_form.is_valid():
                sub_team = sub_team_form.save(commit=False)
                sub_team.parent_team = current_team
                sub_team.save()
                messages.success(request, f'Sub-team "{sub_team.name}" created successfully!')
                return redirect('team_management_dashboard')
        
        # Handle player recruitment
        elif request.method == 'POST' and 'recruit_player' in request.POST:
            recruitment_form = PlayerRecruitmentForm(request.POST, team=current_team)
            if recruitment_form.is_valid():
                player = recruitment_form.cleaned_data['player']
                success, message = current_team.recruit_player(player)
                if success:
                    messages.success(request, message)
                else:
                    messages.error(request, message)
                return redirect('team_management_dashboard')
        
        # Handle player release
        elif request.method == 'POST' and 'release_player' in request.POST:
            release_form = PlayerReleaseForm(request.POST, team=current_team)
            if release_form.is_valid():
                player = release_form.cleaned_data['player']
                success, message = current_team.release_player(player)
                if success:
                    messages.success(request, message)
                else:
                    messages.error(request, message)
                return redirect('team_management_dashboard')
        
        # Handle sub-team player assignment
        elif request.method == 'POST' and 'assign_player' in request.POST:
            sub_team_id = request.POST.get('sub_team_id')
            try:
                sub_team = SubTeam.objects.get(id=sub_team_id, parent_team=current_team)
                assignment_form = SubTeamPlayerAssignmentForm(request.POST, sub_team=sub_team)
                if assignment_form.is_valid():
                    player = assignment_form.cleaned_data['player']
                    position = assignment_form.cleaned_data['position']
                    
                    SubTeamPlayerAssignment.objects.create(
                        sub_team=sub_team,
                        player=player,
                        position=position
                    )
                    messages.success(request, f'Player {player.name} assigned to {sub_team.name}!')
                    return redirect('team_management_dashboard')
            except SubTeam.DoesNotExist:
                messages.error(request, 'Sub-team not found.')
        
        # Handle sub-team player removal
        elif request.method == 'POST' and 'remove_player' in request.POST:
            assignment_id = request.POST.get('assignment_id')
            try:
                assignment = SubTeamPlayerAssignment.objects.get(
                    id=assignment_id,
                    sub_team__parent_team=current_team
                )
                player_name = assignment.player.name
                sub_team_name = assignment.sub_team.name
                assignment.delete()
                messages.success(request, f'Player {player_name} removed from {sub_team_name}!')
                return redirect('team_management_dashboard')
            except SubTeamPlayerAssignment.DoesNotExist:
                messages.error(request, 'Assignment not found.')
        
        # Handle sub-team deletion
        elif request.method == 'POST' and 'delete_sub_team' in request.POST:
            sub_team_id = request.POST.get('sub_team_id')
            try:
                sub_team = SubTeam.objects.get(id=sub_team_id, parent_team=current_team)
                sub_team_name = sub_team.name
                sub_team.delete()  # This will also delete all player assignments
                messages.success(request, f'Sub-team "{sub_team_name}" deleted successfully!')
                return redirect('team_management_dashboard')
            except SubTeam.DoesNotExist:
                messages.error(request, 'Sub-team not found.')
        
        # Handle team logout
        elif request.method == 'POST' and 'logout' in request.POST:
            request.session.pop('team_id', None)
            request.session.pop('team_name', None)
            messages.info(request, 'Logged out successfully.')
            return redirect('team_management_dashboard')
        
        # Initialize forms for display
        if not profile_form:
            profile_form = TeamProfileForm(instance=current_team.profile)
        if not badge_form:
            badge_form = TeamBadgeForm()
        if not sub_team_form:
            sub_team_form = SubTeamForm(parent_team=current_team)
        if not recruitment_form:
            recruitment_form = PlayerRecruitmentForm(team=current_team)
        if not release_form:
            release_form = PlayerReleaseForm(team=current_team)
    
    # Prepare context data
    context = {
        'current_team': current_team,
        'profile_form': profile_form,
        'badge_form': badge_form,
        'sub_team_form': sub_team_form,
        'recruitment_form': recruitment_form,
        'release_form': release_form,
    }
    
    if current_team:
        # Get team data
        context.update({
            'profile': current_team.profile,
            'team_players': current_team.get_main_roster(),
            'unassigned_players': current_team.get_unassigned_players(),
            'badges': current_team.profile.get_badge_display(),
            'sub_teams': current_team.sub_teams.all(),
            'friendly_team': current_team.get_friendly_team(),
            'available_players': current_team.get_available_players_for_recruitment(),
        })
        
        # Add sub-team assignment forms for each sub-team
        sub_team_assignment_forms = {}
        for sub_team in current_team.sub_teams.all():
            sub_team_assignment_forms[sub_team.id] = SubTeamPlayerAssignmentForm(sub_team=sub_team)
        context['sub_team_assignment_forms'] = sub_team_assignment_forms
    
    return render(request, 'teams/team_management_dashboard.html', context)



def edit_player_profile(request):
    """
    Simplified player profile editing and transfer - only requires codename and destination team PIN
    """
    authenticated_player = None
    player_profile = None
    
    if request.method == 'POST':
        form = EditPlayerProfileForm(request.POST, request.FILES)
        if form.is_valid():
            authenticated_player = form.cleaned_data['authenticated_player']
            
            # Get or create the player profile
            try:
                player_profile = authenticated_player.profile
            except PlayerProfile.DoesNotExist:
                player_profile = PlayerProfile.objects.create(
                    player=authenticated_player,
                    email='',
                    skill_level=1
                )
            
            # Update profile picture if provided
            profile_picture = form.cleaned_data.get('profile_picture')
            if profile_picture:
                player_profile.profile_picture = profile_picture
                player_profile.save()
                messages.success(request, 'Profile picture updated successfully!')
            
            # Handle team transfer if requested
            change_team = form.cleaned_data.get('change_team')
            if change_team:
                destination_team = form.cleaned_data['destination_team']
                old_team = authenticated_player.team
                
                # Update player's team
                authenticated_player.team = destination_team
                authenticated_player.save()
                
                messages.success(request, f'Successfully transferred from {old_team.name} to {destination_team.name}!')
            
            # Redirect based on what was updated
            if change_team:
                # Redirect to new team page
                return redirect('team_detail', team_id=authenticated_player.team.id)
            elif profile_picture:
                # Redirect to player profile to show the updated picture
                return redirect('player_profile', player_id=authenticated_player.id)
            else:
                messages.info(request, 'No changes were made to your profile.')
        else:
            # Form is not valid, but check if we have authentication data for display
            codename = form.cleaned_data.get('codename') if 'codename' in form.cleaned_data else None
            
            if codename:
                try:
                    from friendly_games.models import PlayerCodename
                    player_codename = PlayerCodename.objects.get(codename=codename.upper())
                    authenticated_player = player_codename.player
                    try:
                        player_profile = authenticated_player.profile
                    except PlayerProfile.DoesNotExist:
                        player_profile = None
                except PlayerCodename.DoesNotExist:
                    pass
    
    else:
        form = EditPlayerProfileForm()
    
    context = {
        'form': form,
        'authenticated_player': authenticated_player,
        'player_profile': player_profile,
    }
    
    return render(request, 'teams/edit_player_profile.html', context)


def player_search_api(request):
    """
    API endpoint for player search functionality
    """
    if request.method == 'GET':
        query = request.GET.get('q', '').strip()
        
        if len(query) < 2:  # Require at least 2 characters
            return JsonResponse({'players': []})
        
        # Search players by name (case-insensitive)
        players = Player.objects.filter(
            name__icontains=query
        ).select_related('team').values('id', 'name', 'team__name')[:15]  # Limit to 15 results
        
        # Format the results to include team information
        formatted_players = []
        for player in players:
            formatted_players.append({
                'id': player['id'],
                'name': player['name'],
                'team_name': player['team__name'],
                'display_name': f"{player['name']} ({player['team__name']})"
            })
        
        return JsonResponse({'players': formatted_players})
    
    return JsonResponse({'error': 'Invalid request method'}, status=405)

