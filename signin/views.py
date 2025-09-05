from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.utils import timezone
from tournaments.models import Tournament, MeleePlayer
from teams.models import Team
from friendly_games.models import PlayerCodename
from pfc_core.session_utils import CodenameSessionManager
from .forms import TournamentSigninForm
from .models import TeamTournamentSignin

def tournament_signin_list(request):
    """View for listing available tournaments for sign-in"""
    active_tournaments = Tournament.objects.filter(is_active=True, is_archived=False)
    
    context = {
        'active_tournaments': active_tournaments,
    }
    return render(request, 'signin/tournament_signin_list.html', context)

def tournament_signin(request):
    """View for teams to sign in to tournaments using their PIN, or individual players for Mêlée tournaments"""
    tournament_id = request.GET.get('tournament')
    selected_tournament = None
    
    if tournament_id:
        try:
            selected_tournament = Tournament.objects.get(id=tournament_id)
        except Tournament.DoesNotExist:
            pass
    
    # Handle Mêlée tournament registration
    if selected_tournament and selected_tournament.is_melee:
        if request.method == 'POST':
            codename = request.POST.get('codename', '').strip()
            
            if not codename:
                messages.error(request, "Please enter your codename.")
                return render(request, 'signin/tournament_signin.html', {
                    'selected_tournament': selected_tournament,
                    'is_melee': True
                })
            
            # Check if tournament has already started
            now = timezone.now()
            if now > selected_tournament.start_date:
                messages.error(
                    request, 
                    f"Oooops! Tournament {selected_tournament.name} has already started. "
                    f"Try begging the admin, see if it helps."
                )
                return redirect('tournament_signin_list')
            
            # Check if teams have already been generated
            if selected_tournament.melee_teams_generated:
                messages.error(
                    request, 
                    f"Registration is closed. Teams have already been generated for {selected_tournament.name}."
                )
                return render(request, 'signin/tournament_signin.html', {
                    'selected_tournament': selected_tournament,
                    'is_melee': True
                })
            
            try:
                # Get or create player codename
                player_codename = PlayerCodename.objects.get(codename=codename)
                
                # Check if already registered
                if MeleePlayer.objects.filter(tournament=selected_tournament, player=player_codename.player).exists():
                    messages.info(request, f"You are already registered for {selected_tournament.name}.")
                else:
                    # Register player for Mêlée tournament
                    MeleePlayer.objects.create(
                        tournament=selected_tournament,
                        player=player_codename.player
                    )
                    messages.success(request, f"Successfully registered for {selected_tournament.name} Mêlée tournament!")
                
                # Get logged-in codename for auto-fill
                logged_in_codename = CodenameSessionManager.get_logged_in_codename(request) if CodenameSessionManager.is_logged_in(request) else ''
                
                return render(request, 'signin/tournament_signin.html', {
                    'selected_tournament': selected_tournament,
                    'is_melee': True,
                    'registered_players': MeleePlayer.objects.filter(tournament=selected_tournament),
                    'logged_in_codename': logged_in_codename  # Add for auto-fill
                })
                
            except PlayerCodename.DoesNotExist:
                messages.error(request, f"Codename '{codename}' not found. Please check your codename.")
                # Get logged-in codename for auto-fill
                logged_in_codename = CodenameSessionManager.get_logged_in_codename(request) if CodenameSessionManager.is_logged_in(request) else ''
                
                return render(request, 'signin/tournament_signin.html', {
                    'selected_tournament': selected_tournament,
                    'is_melee': True,
                    'logged_in_codename': logged_in_codename  # Add for auto-fill
                })
        
        else:
            # GET request for Mêlée tournament
            # Get logged-in codename for auto-fill
            logged_in_codename = CodenameSessionManager.get_logged_in_codename(request) if CodenameSessionManager.is_logged_in(request) else ''
            
            return render(request, 'signin/tournament_signin.html', {
                'selected_tournament': selected_tournament,
                'is_melee': True,
                'registered_players': MeleePlayer.objects.filter(tournament=selected_tournament),
                'logged_in_codename': logged_in_codename  # Add for auto-fill
            })
    
    # Handle regular team tournament sign-in
    if request.method == 'POST':
        form = TournamentSigninForm(request.POST)
        if form.is_valid():
            team = form.cleaned_data['team']
            tournament = form.cleaned_data['tournament']
            
            # Check if tournament has already started
            now = timezone.now()
            if now > tournament.start_date:
                messages.error(
                    request, 
                    f"Oooops! Tournament {tournament.name} has already started. "
                    f"Try begging the admin, see if it helps."
                )
                return redirect('tournament_signin_list')
            
            # Check if already signed in
            if hasattr(form, 'signin_exists') and form.signin_exists:
                messages.info(request, f"Your team is already signed in to {tournament.name}.")
            else:
                # Create new sign-in record
                signin, created = TeamTournamentSignin.objects.get_or_create(
                    team=team,
                    tournament=tournament,
                    defaults={'is_active': True}
                )
                
                if not created:
                    signin.is_active = True
                    signin.signed_in_at = timezone.now()
                    signin.save()
                
                # Also create a TournamentTeam record to ensure the team shows up in tournament views
                from tournaments.models import TournamentTeam
                tournament_team, tt_created = TournamentTeam.objects.get_or_create(
                    team=team,
                    tournament=tournament,
                    defaults={}
                )
                
                messages.success(request, f"Successfully signed in to {tournament.name}.")
            
            # Redirect to team dashboard
            return redirect('team_tournament_dashboard', team_id=team.id, tournament_id=tournament.id)
    else:
        form = TournamentSigninForm()
        if selected_tournament:
            form.fields['tournament'].initial = selected_tournament.id
    
    # Get logged-in codename for auto-fill
    logged_in_codename = CodenameSessionManager.get_logged_in_codename(request) if CodenameSessionManager.is_logged_in(request) else ''
    
    context = {
        'form': form,
        'selected_tournament': selected_tournament,
        'logged_in_codename': logged_in_codename,  # Add for auto-fill
        'is_melee': selected_tournament.is_melee if selected_tournament else False
    }
    return render(request, 'signin/tournament_signin.html', context)

def team_tournament_dashboard(request, team_id, tournament_id):
    """Dashboard view for a team signed in to a tournament"""
    team = get_object_or_404(Team, id=team_id)
    tournament = get_object_or_404(Tournament, id=tournament_id)
    
    # Verify team is signed in to this tournament
    signin = get_object_or_404(TeamTournamentSignin, team=team, tournament=tournament, is_active=True)
    
    context = {
        'team': team,
        'tournament': tournament,
        'signin': signin,
    }
    return render(request, 'signin/team_tournament_dashboard.html', context)

def tournament_signout(request, team_id, tournament_id):
    """View for teams to sign out from tournaments"""
    team = get_object_or_404(Team, id=team_id)
    tournament = get_object_or_404(Tournament, id=tournament_id)
    
    # Find and deactivate sign-in record
    signin = get_object_or_404(TeamTournamentSignin, team=team, tournament=tournament, is_active=True)
    signin.is_active = False
    signin.save()
    
    messages.success(request, f"Successfully signed out from {tournament.name}.")
    return redirect('tournament_signin_list')
