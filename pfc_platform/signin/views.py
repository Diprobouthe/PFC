from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.utils import timezone
from tournaments.models import Tournament
from teams.models import Team
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
    """View for teams to sign in to tournaments using their PIN"""
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
    
    context = {
        'form': form,
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
