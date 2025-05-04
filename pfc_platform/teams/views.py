from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from .models import Team, Player, TeamAvailability
from .forms import TeamForm, PlayerForm, TeamAvailabilityForm, TeamPinVerificationForm
from matches.models import Match
from django.db.models import Q

# Removed login_required decorator
def team_list(request):
    """View for listing all teams"""
    teams = Team.objects.all().order_by('name')
    context = {
        'teams': teams,
    }
    return render(request, 'teams/team_list.html', context)

# Removed login_required decorator
def team_detail(request, team_id):
    """View for displaying team details"""
    team = get_object_or_404(Team, id=team_id)
    players = team.players.all()
    availabilities = team.availabilities.all().order_by('-available_from')
    
    # Use the get_pin method to get the appropriate PIN display
    pin_display = team.get_pin(request.user)
    
    context = {
        'team': team,
        'team_pin': pin_display,  # Pass the PIN display separately
        'players': players,
        'availabilities': availabilities,
        'is_staff': request.user.is_staff if request.user.is_authenticated else False,
    }
    return render(request, 'teams/team_detail.html', context)

# Removed login_required decorator
def team_create(request):
    """View for creating a new team"""
    if request.method == 'POST':
        form = TeamForm(request.POST)
        if form.is_valid():
            team = form.save()
            messages.success(request, f'Team "{team.name}" created successfully with PIN: {team.pin}')
            return redirect('team_detail', team_id=team.id)
    else:
        form = TeamForm()
    
    context = {
        'form': form,
        'title': 'Create Team',
    }
    return render(request, 'teams/team_form.html', context)

# Removed login_required decorator
def team_update(request, team_id):
    """View for updating an existing team"""
    team = get_object_or_404(Team, id=team_id)
    
    # Verify PIN before allowing edit
    if request.method == 'POST' and 'pin' in request.POST:
        pin_form = TeamPinVerificationForm(team, request.POST)
        if pin_form.is_valid():
            # PIN verified, show edit form
            if 'name' in request.POST:
                form = TeamForm(request.POST, instance=team)
                if form.is_valid():
                    team = form.save()
                    messages.success(request, f'Team "{team.name}" updated successfully.')
                    return redirect('team_detail', team_id=team.id)
            else:
                form = TeamForm(instance=team)
                context = {
                    'form': form,
                    'team': team,
                    'title': 'Update Team',
                    'pin_verified': True,
                }
                return render(request, 'teams/team_form.html', context)
        else:
            messages.error(request, "Invalid PIN. Please try again.")
            pin_form = TeamPinVerificationForm(team)
    else:
        pin_form = TeamPinVerificationForm(team)
    
    context = {
        'team': team,
        'pin_form': pin_form,
        'title': 'Verify PIN',
    }
    return render(request, 'teams/team_pin_verification.html', context)

# Removed login_required decorator
def player_create(request, team_id):
    """View for adding a player to a team"""
    team = get_object_or_404(Team, id=team_id)
    
    # Verify PIN before allowing player creation
    if request.method == 'POST' and 'pin' in request.POST:
        pin_form = TeamPinVerificationForm(team, request.POST)
        if pin_form.is_valid():
            # PIN verified, process player form
            if 'name' in request.POST:
                form = PlayerForm(request.POST)
                if form.is_valid():
                    player = form.save(commit=False)
                    player.team = team
                    player.save()
                    messages.success(request, f'Player "{player.name}" added to team "{team.name}" successfully.')
                    return redirect('team_detail', team_id=team.id)
            else:
                form = PlayerForm()
                context = {
                    'form': form,
                    'team': team,
                    'title': 'Add Player',
                    'pin_verified': True,
                }
                return render(request, 'teams/player_form.html', context)
        else:
            messages.error(request, "Invalid PIN. Please try again.")
            pin_form = TeamPinVerificationForm(team)
    else:
        pin_form = TeamPinVerificationForm(team)
    
    context = {
        'team': team,
        'pin_form': pin_form,
        'title': 'Verify PIN',
    }
    return render(request, 'teams/team_pin_verification.html', context)

# Removed login_required decorator
def player_update(request, player_id):
    """View for updating a player"""
    player = get_object_or_404(Player, id=player_id)
    team = player.team
    
    # Verify PIN before allowing player update
    if request.method == 'POST' and 'pin' in request.POST:
        pin_form = TeamPinVerificationForm(team, request.POST)
        if pin_form.is_valid():
            # PIN verified, process player form
            if 'name' in request.POST:
                form = PlayerForm(request.POST, instance=player)
                if form.is_valid():
                    player = form.save()
                    messages.success(request, f'Player "{player.name}" updated successfully.')
                    return redirect('team_detail', team_id=team.id)
            else:
                form = PlayerForm(instance=player)
                context = {
                    'form': form,
                    'player': player,
                    'team': team,
                    'title': 'Update Player',
                    'pin_verified': True,
                }
                return render(request, 'teams/player_form.html', context)
        else:
            messages.error(request, "Invalid PIN. Please try again.")
            pin_form = TeamPinVerificationForm(team)
    else:
        pin_form = TeamPinVerificationForm(team)
    
    context = {
        'team': team,
        'player': player,
        'pin_form': pin_form,
        'title': 'Verify PIN',
    }
    return render(request, 'teams/team_pin_verification.html', context)

# Removed login_required decorator
def player_delete(request, player_id):
    """View for deleting a player"""
    player = get_object_or_404(Player, id=player_id)
    team = player.team
    
    # Verify PIN before allowing player deletion
    if request.method == 'POST':
        pin_form = TeamPinVerificationForm(team, request.POST)
        if pin_form.is_valid():
            player_name = player.name
            player.delete()
            messages.success(request, f'Player "{player_name}" removed from team "{team.name}" successfully.')
            return redirect('team_detail', team_id=team.id)
        else:
            messages.error(request, "Invalid PIN. Please try again.")
    
    pin_form = TeamPinVerificationForm(team)
    context = {
        'team': team,
        'player': player,
        'pin_form': pin_form,
        'title': 'Verify PIN to Delete Player',
    }
    return render(request, 'teams/team_pin_verification.html', context)

# Removed login_required decorator
def team_availability_create(request, team_id):
    """View for setting team availability"""
    team = get_object_or_404(Team, id=team_id)
    
    # Verify PIN before allowing availability creation
    if request.method == 'POST' and 'pin' in request.POST:
        pin_form = TeamPinVerificationForm(team, request.POST)
        if pin_form.is_valid():
            # PIN verified, process availability form
            if 'available_from' in request.POST:
                form = TeamAvailabilityForm(request.POST)
                if form.is_valid():
                    availability = form.save(commit=False)
                    availability.team = team
                    availability.save()
                    messages.success(request, f'Availability for team "{team.name}" set successfully.')
                    return redirect('team_detail', team_id=team.id)
            else:
                form = TeamAvailabilityForm()
                context = {
                    'form': form,
                    'team': team,
                    'title': 'Set Team Availability',
                    'pin_verified': True,
                }
                return render(request, 'teams/availability_form.html', context)
        else:
            messages.error(request, "Invalid PIN. Please try again.")
            pin_form = TeamPinVerificationForm(team)
    else:
        pin_form = TeamPinVerificationForm(team)
    
    context = {
        'team': team,
        'pin_form': pin_form,
        'title': 'Verify PIN',
    }
    return render(request, 'teams/team_pin_verification.html', context)

# Removed login_required decorator
def show_team_pin(request, team_id):
    """View for displaying team PIN after verification"""
    team = get_object_or_404(Team, id=team_id)
    
    if request.method == 'POST':
        form = TeamPinVerificationForm(team, request.POST)
        if form.is_valid():
            context = {
                'team': team,
                'pin_verified': True,
            }
            return render(request, 'teams/show_pin.html', context)
        else:
            messages.error(request, "Invalid PIN. Please try again.")
    
    form = TeamPinVerificationForm(team)
    context = {
        'team': team,
        'pin_form': form,
        'title': 'Verify PIN',
    }
    return render(request, 'teams/team_pin_verification.html', context)

def team_login(request):
    """View for team login using PIN and handling actions like finding next match."""
    if request.method == "POST":
        pin = request.POST.get("pin")
        action = request.POST.get("action") # Get the action value

        try:
            team = Team.objects.get(pin=pin)

            if action == "find_next":
                # Find available pending matches for this team
                available_matches = Match.objects.filter(
                    status__in=["pending", "pending_verification", "waiting_for_court"],
                ).filter(
                    Q(team1=team) | Q(team2=team)
                ).order_by("created_at") # Order to get the earliest pending match

                if available_matches.exists():
                    next_match = available_matches.first()
                    opponent_team = next_match.team2 if team == next_match.team1 else next_match.team1
                    messages.success(request, f"Welcome, {team.name}! Your next scheduled match is against {opponent_team.name}. Click to view details.")
                    return redirect("match_detail", match_id=next_match.id)
                else:
                    # No pending matches found, inform the user and redirect to home
                    messages.info(request, f"Welcome, {team.name}! You don't have any scheduled pending matches at the moment. Please check back later or contact the organizer.")
                    return redirect("home")

            elif action == "activate":
                # Logic to find the match the team wants to activate (might need match ID)
                # This might be better handled by a button on the match detail page
                messages.warning(request, "Please go to the specific match page to activate it.")
                return redirect("match_list") # Or redirect to a relevant page

            elif action == "submit_score":
                # Logic to find the active match the team wants to submit score for
                # This might be better handled by a button on the match detail page
                active_match = Match.objects.filter(status="active").filter(Q(team1=team) | Q(team2=team)).first()
                if active_match:
                    return redirect("match_submit_result", match_id=active_match.id, team_id=team.id)
                else:
                    messages.warning(request, "You don't have an active match to submit scores for.")
                    return redirect("match_list")

            else:
                # Default action if none specified (or handle error)
                messages.warning(request, "Invalid action.")
                return redirect("home")

        except Team.DoesNotExist:
            messages.error(request, "Invalid PIN. Please try again.")

    return redirect("home")
