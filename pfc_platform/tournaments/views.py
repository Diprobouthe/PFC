from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from .models import Tournament, TournamentTeam, Round, Bracket
from .forms import TournamentForm, TeamAssignmentForm
from matches.models import Match
import random
import math

def is_staff(user):
    return user.is_staff

# Removed login_required decorator
def tournament_list(request):
    """View for listing all tournaments"""
    active_tournaments = Tournament.objects.filter(is_active=True, is_archived=False)
    archived_tournaments = Tournament.objects.filter(is_archived=True)
    
    context = {
        'active_tournaments': active_tournaments,
        'archived_tournaments': archived_tournaments,
    }
    return render(request, 'tournaments/tournament_list.html', context)

# Removed login_required decorator
def tournament_detail(request, tournament_id):
    """View for displaying tournament details"""
    tournament = get_object_or_404(Tournament, id=tournament_id)
    rounds = tournament.rounds.all().order_by('number')
    teams = tournament.teams.all()
    
    # Import the update_tournament_leaderboard function
    from leaderboards.views import update_tournament_leaderboard
    
    # Ensure leaderboard is created and updated
    update_tournament_leaderboard(tournament)
    
    context = {
        'tournament': tournament,
        'rounds': rounds,
        'teams': teams,
    }
    return render(request, 'tournaments/tournament_detail.html', context)

@user_passes_test(is_staff)
def tournament_create(request):
    """View for creating a new tournament (staff only)"""
    if request.method == 'POST':
        form = TournamentForm(request.POST)
        if form.is_valid():
            tournament = form.save()
            
            # Import the update_tournament_leaderboard function
            from leaderboards.views import update_tournament_leaderboard
            
            # Create and initialize leaderboard
            update_tournament_leaderboard(tournament)
            
            messages.success(request, f'Tournament "{tournament.name}" created successfully.')
            return redirect('tournament_assign_teams', tournament_id=tournament.id)
    else:
        form = TournamentForm()
    
    context = {
        'form': form,
        'title': 'Create Tournament',
    }
    return render(request, 'tournaments/tournament_form.html', context)

@user_passes_test(is_staff)
def tournament_update(request, tournament_id):
    """View for updating an existing tournament (staff only)"""
    tournament = get_object_or_404(Tournament, id=tournament_id)
    
    if request.method == 'POST':
        form = TournamentForm(request.POST, instance=tournament)
        if form.is_valid():
            tournament = form.save()
            
            # Import the update_tournament_leaderboard function
            from leaderboards.views import update_tournament_leaderboard
            
            # Update leaderboard
            update_tournament_leaderboard(tournament)
            
            messages.success(request, f'Tournament "{tournament.name}" updated successfully.')
            return redirect('tournament_detail', tournament_id=tournament.id)
    else:
        form = TournamentForm(instance=tournament)
    
    context = {
        'form': form,
        'tournament': tournament,
        'title': 'Update Tournament',
    }
    return render(request, 'tournaments/tournament_form.html', context)

@user_passes_test(is_staff)
def tournament_assign_teams(request, tournament_id):
    """View for assigning teams to a tournament (staff only)"""
    tournament = get_object_or_404(Tournament, id=tournament_id)
    
    if request.method == 'POST':
        form = TeamAssignmentForm(tournament, request.POST)
        if form.is_valid():
            form.save()
            
            # Import the update_tournament_leaderboard function
            from leaderboards.views import update_tournament_leaderboard
            
            # Update leaderboard after team assignment
            update_tournament_leaderboard(tournament)
            
            messages.success(request, f'Teams assigned to "{tournament.name}" successfully.')
            return redirect('tournament_detail', tournament_id=tournament.id)
    else:
        form = TeamAssignmentForm(tournament)
    
    context = {
        'form': form,
        'tournament': tournament,
    }
    return render(request, 'tournaments/team_assignment_form.html', context)

@user_passes_test(is_staff)
def tournament_archive(request, tournament_id):
    """View for archiving a tournament (staff only)"""
    tournament = get_object_or_404(Tournament, id=tournament_id)
    tournament.is_active = False
    tournament.is_archived = True
    tournament.save()
    
    messages.success(request, f'Tournament "{tournament.name}" has been archived.')
    return redirect('tournament_list')

@user_passes_test(is_staff)
def generate_matches(request, tournament_id):
    """View for generating matches based on tournament format (staff only)"""
    tournament = get_object_or_404(Tournament, id=tournament_id)
    
    if tournament.format == 'round_robin':
        _generate_round_robin_matches(tournament)
        messages.success(request, f'Round-robin matches generated for "{tournament.name}".')
    
    elif tournament.format == 'knockout':
        _generate_knockout_matches(tournament)
        messages.success(request, f'Knockout matches generated for "{tournament.name}".')
    
    elif tournament.format == 'swiss':
        _generate_swiss_matches(tournament)
        messages.success(request, f'Swiss system matches generated for "{tournament.name}".')
    
    # Import the update_tournament_leaderboard function
    from leaderboards.views import update_tournament_leaderboard
    
    # Update leaderboard after generating matches
    update_tournament_leaderboard(tournament)
    
    return redirect('tournament_detail', tournament_id=tournament.id)

def _generate_round_robin_matches(tournament):
    """Generate matches for a round-robin tournament"""
    teams = list(tournament.teams.all())
    
    # If odd number of teams, add a "bye" team
    if len(teams) % 2 != 0:
        teams.append(None)
    
    n = len(teams)
    matches_per_round = n // 2
    
    # Create rounds
    for round_num in range(1, n):
        round_obj, created = Round.objects.get_or_create(
            tournament=tournament,
            number=round_num
        )
        
        # Generate matches for this round
        for i in range(matches_per_round):
            team1 = teams[i]
            team2 = teams[n - 1 - i]
            
            # Skip if one team is the "bye" team
            if team1 is None or team2 is None:
                continue
            
            Match.objects.create(
                tournament=tournament,
                round=round_obj,
                team1=team1,
                team2=team2,
                status='pending'
            )
        
        # Rotate teams for next round (first team stays fixed)
        teams = [teams[0]] + [teams[-1]] + teams[1:-1]

def _generate_knockout_matches(tournament):
    """Generate matches for a knockout tournament"""
    teams = list(tournament.teams.all())
    random.shuffle(teams)  # Random seeding
    
    # Calculate number of rounds needed
    num_teams = len(teams)
    num_rounds = math.ceil(math.log2(num_teams))
    
    # Create rounds
    for round_num in range(1, num_rounds + 1):
        round_obj, created = Round.objects.get_or_create(
            tournament=tournament,
            number=round_num
        )
    
    # First round matches
    first_round = Round.objects.get(tournament=tournament, number=1)
    matches_in_first_round = 2 ** (num_rounds - 1)
    byes = matches_in_first_round * 2 - num_teams
    
    for i in range(matches_in_first_round):
        position = i + 1
        bracket, created = Bracket.objects.get_or_create(
            tournament=tournament,
            round=first_round,
            position=position
        )
        
        # If we have enough teams for this match
        if i < (num_teams - byes) // 2:
            team1 = teams[i * 2]
            team2 = teams[i * 2 + 1]
            
            Match.objects.create(
                tournament=tournament,
                round=first_round,
                bracket=bracket,
                team1=team1,
                team2=team2,
                status='pending'
            )
        # If one team gets a bye
        elif i < num_teams - byes:
            team1 = teams[i + (num_teams - byes) // 2]
            
            # Create brackets for subsequent rounds
            current_bracket = bracket
            for round_num in range(2, num_rounds + 1):
                next_round = Round.objects.get(tournament=tournament, number=round_num)
                next_position = math.ceil(current_bracket.position / 2)
                
                next_bracket, created = Bracket.objects.get_or_create(
                    tournament=tournament,
                    round=next_round,
                    position=next_position
                )
                
                current_bracket = next_bracket

def _generate_swiss_matches(tournament):
    """Generate matches for a Swiss system tournament"""
    teams = list(tournament.teams.all())
    random.shuffle(teams)  # Random initial pairing
    
    # Create first round
    round_obj, created = Round.objects.get_or_create(
        tournament=tournament,
        number=1
    )
    
    # Generate matches for first round
    for i in range(0, len(teams), 2):
        # If we have an odd number of teams, the last team gets a bye
        if i + 1 >= len(teams):
            break
            
        team1 = teams[i]
        team2 = teams[i + 1]
        
        Match.objects.create(
            tournament=tournament,
            round=round_obj,
            team1=team1,
            team2=team2,
            status='pending'
        )
    
    # For subsequent rounds, matches will be generated after previous round results are in
