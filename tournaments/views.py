from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from .models import Tournament, TournamentTeam, Round, Bracket
from .forms import TournamentForm, TeamAssignmentForm
from matches.models import Match
from teams.models import Team
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
    
    # For Mêlée tournaments, redirect to team generation or detail page
    if tournament.is_melee:
        if not tournament.melee_teams_generated:
            messages.info(request, f'This is a Mêlée tournament. Teams will be generated automatically from individual player registrations.')
            return redirect('tournament_generate_melee_teams', tournament_id=tournament.id)
        else:
            messages.info(request, f'Teams for this Mêlée tournament have already been generated.')
            return redirect('tournament_detail', tournament_id=tournament.id)
    
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
    
    # For Mêlée tournaments, ensure teams have been generated first
    if tournament.is_melee and not tournament.melee_teams_generated:
        messages.error(request, f'Cannot generate matches for Mêlée tournament "{tournament.name}" until teams are generated from player registrations.')
        return redirect('tournament_generate_melee_teams', tournament_id=tournament.id)
    
    # Check if tournament has any teams
    if not tournament.teams.exists():
        if tournament.is_melee:
            messages.error(request, f'No teams available for Mêlée tournament "{tournament.name}". Please generate teams from player registrations first.')
            return redirect('tournament_generate_melee_teams', tournament_id=tournament.id)
        else:
            messages.error(request, f'No teams assigned to tournament "{tournament.name}". Please assign teams first.')
            return redirect('tournament_assign_teams', tournament_id=tournament.id)
    
    if tournament.format == 'round_robin':
        _generate_round_robin_matches(tournament)
        messages.success(request, f'Round-robin matches generated for "{tournament.name}".')
    
    elif tournament.format == 'knockout':
        _generate_knockout_matches(tournament)
        messages.success(request, f'Knockout matches generated for "{tournament.name}".')
    
    elif tournament.format == 'swiss':
        _generate_swiss_matches(tournament)
        messages.success(request, f'Swiss system matches generated for "{tournament.name}".')
    
    elif tournament.format == 'multi_stage':
        # For multi_stage tournaments, generate round-robin matches by default
        _generate_round_robin_matches(tournament)
        messages.success(request, f'Multi-stage matches generated for "{tournament.name}".')
    
    else:
        messages.error(request, f'Unknown tournament format: {tournament.format}')
        return redirect('tournament_detail', tournament_id=tournament.id)
    
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


# Subteam Registration Views
from .subteam_forms import SubteamRegistrationForm, QuickTeamRegistrationForm
from teams.subteam_service import get_tournament_subteam_options

def tournament_register(request, tournament_id):
    """
    Public view for teams to register for tournaments with subteam options
    """
    tournament = get_object_or_404(Tournament, id=tournament_id)
    
    if not tournament.is_active:
        messages.error(request, "This tournament is no longer accepting registrations.")
        return redirect('tournament_detail', tournament_id=tournament.id)
    
    if request.method == 'POST':
        # Check if this is a PIN-based registration
        if 'team_pin' in request.POST:
            # Validate PIN and check for subteam options
            pin_form = QuickTeamRegistrationForm(tournament, request.POST)
            if pin_form.is_valid():
                team = pin_form.cleaned_data['team']
                
                # Check if team can create subteams
                subteam_options = get_tournament_subteam_options(team, tournament)
                
                if subteam_options['has_subteam_options']:
                    # Redirect to choice page instead of auto-registering
                    from django.http import HttpResponseRedirect
                    from django.urls import reverse
                    url = reverse('tournament_register_choice', kwargs={'tournament_id': tournament_id})
                    return HttpResponseRedirect(f'{url}?pin={team.pin}')
                else:
                    # Only auto-register if no subteam options exist
                    tournament_team = pin_form.save()
                    messages.success(
                        request, 
                        f"Team '{tournament_team.team.name}' successfully registered for {tournament.name}!"
                    )
                    return redirect('tournament_detail', tournament_id=tournament.id)
        else:
            # This should not happen in normal flow, redirect to PIN entry
            messages.error(request, "Please enter your team PIN to continue.")
            return redirect('tournament_register', tournament_id=tournament.id)
    else:
        pin_form = QuickTeamRegistrationForm(tournament)
    
    context = {
        'tournament': tournament,
        'form': pin_form,
        'registration_type': 'pin_entry'
    }
    return render(request, 'tournaments/tournament_register.html', context)

def tournament_register_subteams(request, tournament_id):
    """
    View for teams to register with subteam configuration
    """
    tournament = get_object_or_404(Tournament, id=tournament_id)
    
    # Get team from PIN (should be in session or passed as parameter)
    team_pin = request.GET.get('pin') or request.session.get('registration_team_pin')
    if not team_pin:
        messages.error(request, "Please enter your team PIN first.")
        return redirect('tournament_register', tournament_id=tournament.id)
    
    try:
        team = Team.objects.get(pin=team_pin)
    except Team.DoesNotExist:
        messages.error(request, "Invalid team PIN.")
        return redirect('tournament_register', tournament_id=tournament.id)
    
    # Check if team is already registered
    if TournamentTeam.objects.filter(tournament=tournament, team=team).exists():
        messages.warning(request, f"Team '{team.name}' is already registered for this tournament.")
        return redirect('tournament_detail', tournament_id=tournament.id)
    
    if request.method == 'POST':
        form = SubteamRegistrationForm(tournament, team, request.POST)
        if form.is_valid():
            result = form.save()
            
            if result['success']:
                # Create success message with details
                created_count = len(result['created_subteams'])
                reused_count = len(result['reused_subteams'])
                total_registered = len(result['registered_teams'])
                
                message_parts = [f"Successfully registered {total_registered} subteam(s) for {tournament.name}!"]
                
                if created_count > 0:
                    message_parts.append(f"Created {created_count} new subteam(s)")
                if reused_count > 0:
                    message_parts.append(f"Reused {reused_count} existing subteam(s)")
                
                messages.success(request, " | ".join(message_parts))
                
                # Clear session data
                if 'registration_team_pin' in request.session:
                    del request.session['registration_team_pin']
                
                return redirect('tournament_detail', tournament_id=tournament.id)
            else:
                for error in result['errors']:
                    messages.error(request, error)
    else:
        form = SubteamRegistrationForm(tournament, team)
        # Store PIN in session for form processing
        request.session['registration_team_pin'] = team_pin
    
    # Get subteam options for display
    subteam_options = get_tournament_subteam_options(team, tournament)
    
    context = {
        'tournament': tournament,
        'team': team,
        'form': form,
        'subteam_options': subteam_options,
        'registration_type': 'subteam_config'
    }
    return render(request, 'tournaments/tournament_register.html', context)

def tournament_register_choice(request, tournament_id):
    """
    View to let teams choose between simple registration or subteam registration
    """
    tournament = get_object_or_404(Tournament, id=tournament_id)
    
    # Get team from PIN
    team_pin = request.GET.get('pin')
    if not team_pin:
        messages.error(request, "Please enter your team PIN first.")
        return redirect('tournament_register', tournament_id=tournament.id)
    
    try:
        team = Team.objects.get(pin=team_pin)
    except Team.DoesNotExist:
        messages.error(request, "Invalid team PIN.")
        return redirect('tournament_register', tournament_id=tournament.id)
    
    # Check if team is already registered
    if TournamentTeam.objects.filter(tournament=tournament, team=team).exists():
        messages.warning(request, f"Team '{team.name}' is already registered for this tournament.")
        return redirect('tournament_detail', tournament_id=tournament.id)
    
    # Get subteam options for display
    subteam_options = get_tournament_subteam_options(team, tournament)
    
    context = {
        'tournament': tournament,
        'team': team,
        'subteam_options': subteam_options,
        'registration_type': 'choice'
    }
    return render(request, 'tournaments/tournament_register.html', context)



def tournament_overview(request, tournament_id):
    """
    Full-screen tournament overview showing all active matches with live scores.
    This bundles all active games of a tournament into one consolidated display.
    """
    from matches.models import LiveScoreboard, MatchPlayer
    from django.shortcuts import render, get_object_or_404
    
    tournament = get_object_or_404(Tournament, id=tournament_id)
    
    # Get all active matches for this tournament
    active_matches = Match.objects.filter(
        tournament=tournament,
        status__in=['active', 'pending_verification']
    ).select_related('team1', 'team2').order_by('created_at')
    
    # Get live scoreboards for these matches
    tournament_scoreboards = []
    for match in active_matches:
        try:
            scoreboard = LiveScoreboard.objects.get(
                tournament_match=match,
                is_active=True
            )
            
            # Get MatchPlayer data with positions for both teams
            team1_players = MatchPlayer.objects.filter(match=match, team=match.team1).select_related('player')
            team2_players = MatchPlayer.objects.filter(match=match, team=match.team2).select_related('player')
            
            tournament_scoreboards.append({
                'match': match,
                'scoreboard': scoreboard,
                'team1_name': match.team1.name if match.team1 else 'Team 1',
                'team2_name': match.team2.name if match.team2 else 'Team 2',
                'team1_players': team1_players,
                'team2_players': team2_players,
            })
        except LiveScoreboard.DoesNotExist:
            # Create a placeholder for matches without live scoreboards
            tournament_scoreboards.append({
                'match': match,
                'scoreboard': None,
                'team1_name': match.team1.name if match.team1 else 'Team 1',
                'team2_name': match.team2.name if match.team2 else 'Team 2',
                'team1_players': match.team1.players.all() if match.team1 and hasattr(match.team1, 'players') else [],
                'team2_players': match.team2.players.all() if match.team2 and hasattr(match.team2, 'players') else [],
            })
    
    context = {
        'tournament': tournament,
        'tournament_scoreboards': tournament_scoreboards,
        'total_matches': len(tournament_scoreboards),
        'has_active_matches': len(tournament_scoreboards) > 0,
    }
    
    return render(request, 'tournaments/tournament_overview.html', context)


# Mêlée Mode Views
def tournament_register_melee(request, tournament_id):
    """View for individual player registration in Mêlée tournaments"""
    tournament = get_object_or_404(Tournament, id=tournament_id)
    
    # Check if tournament is in Mêlée mode
    if not tournament.is_melee:
        messages.error(request, "This tournament is not configured for Mêlée mode.")
        return redirect('tournament_detail', tournament_id=tournament.id)
    
    # Check if tournament is still accepting registrations
    if not tournament.is_active:
        messages.error(request, "This tournament is no longer accepting registrations.")
        return redirect('tournament_detail', tournament_id=tournament.id)
    
    # Check if teams have already been generated
    if tournament.melee_teams_generated:
        messages.error(request, "Registration is closed. Teams have already been generated for this tournament.")
        return redirect('tournament_detail', tournament_id=tournament.id)
    
    from .forms import MeleePlayerRegistrationForm
    
    if request.method == 'POST':
        form = MeleePlayerRegistrationForm(tournament, request.POST)
        if form.is_valid():
            melee_player = form.save()
            messages.success(
                request, 
                f"Successfully registered for {tournament.name}! You will be assigned to a team when registration closes."
            )
            return redirect('tournament_detail', tournament_id=tournament.id)
    else:
        form = MeleePlayerRegistrationForm(tournament)
    
    # Get current registrations for display
    current_registrations = tournament.melee_players.all().select_related('player')
    team_size = 2 if tournament.melee_format == "doublets" else 3
    estimated_teams = len(current_registrations) // team_size
    
    # Check if tournament is full
    is_full = False
    if tournament.max_participants:
        is_full = len(current_registrations) >= tournament.max_participants
    
    context = {
        'tournament': tournament,
        'form': form,
        'current_registrations': current_registrations,
        'registration_count': len(current_registrations),
        'max_participants': tournament.max_participants,
        'is_full': is_full,
        'team_size': team_size,
        'estimated_teams': estimated_teams,
        'leftover_players': len(current_registrations) % team_size,
    }
    
    return render(request, 'tournaments/melee_register.html', context)

def tournament_melee_status(request, tournament_id):
    """View to show Mêlée tournament registration status and generated teams"""
    tournament = get_object_or_404(Tournament, id=tournament_id)
    
    if not tournament.is_melee:
        messages.error(request, "This tournament is not configured for Mêlée mode.")
        return redirect('tournament_detail', tournament_id=tournament.id)
    
    # Get registrations and teams
    registrations = tournament.melee_players.all().select_related('player', 'assigned_team')
    generated_teams = []
    
    if tournament.melee_teams_generated:
        # Group registrations by assigned team
        teams_dict = {}
        for reg in registrations:
            if reg.assigned_team:
                if reg.assigned_team.id not in teams_dict:
                    teams_dict[reg.assigned_team.id] = {
                        'team': reg.assigned_team,
                        'players': []
                    }
                teams_dict[reg.assigned_team.id]['players'].append(reg.player)
        
        generated_teams = list(teams_dict.values())
    
    context = {
        'tournament': tournament,
        'registrations': registrations,
        'registration_count': len(registrations),
        'generated_teams': generated_teams,
        'teams_generated': tournament.melee_teams_generated,
    }
    
    return render(request, 'tournaments/melee_status.html', context)



def tournament_generate_melee_teams(request, tournament_id):
    """Admin view to generate Mêlée teams with algorithm selection"""
    tournament = get_object_or_404(Tournament, id=tournament_id)
    
    # Check admin permissions
    if not request.user.is_staff:
        messages.error(request, "You don't have permission to perform this action.")
        return redirect('tournament_detail', tournament_id=tournament.id)
    
    # Check if tournament is in Mêlée mode
    if not tournament.is_melee:
        messages.error(request, "This tournament is not configured for Mêlée mode.")
        return redirect('tournament_detail', tournament_id=tournament.id)
    
    # Check if teams have already been generated
    if tournament.melee_teams_generated:
        messages.warning(request, "Teams have already been generated for this tournament.")
        return redirect('tournament_detail', tournament_id=tournament.id)
    
    if request.method == 'POST':
        algorithm = request.POST.get('algorithm', 'random')
        
        try:
            teams_created = tournament.generate_melee_teams(algorithm)
            
            if teams_created > 0:
                algorithm_names = {
                    'random': 'Random Assignment',
                    'balanced': 'Balanced by Skill',
                    'snake_draft': 'Snake Draft'
                }
                algorithm_name = algorithm_names.get(algorithm, algorithm)
                
                messages.success(
                    request, 
                    f"Successfully generated {teams_created} teams using {algorithm_name} algorithm!"
                )
            else:
                messages.warning(request, "No teams were generated. Check if there are enough registered players.")
                
        except Exception as e:
            messages.error(request, f"Error generating teams: {e}")
        
        return redirect('tournament_detail', tournament_id=tournament.id)
    
    # Get current registrations for display
    registrations = tournament.melee_players.all().select_related('player')
    team_size = 2 if tournament.melee_format == "doublets" else 3
    estimated_teams = len(registrations) // team_size
    
    context = {
        'tournament': tournament,
        'registrations': registrations,
        'registration_count': len(registrations),
        'team_size': team_size,
        'estimated_teams': estimated_teams,
        'leftover_players': len(registrations) % team_size,
    }
    
    return render(request, 'tournaments/generate_melee_teams.html', context)


@user_passes_test(is_staff)
def tournament_restore_melee_players(request, tournament_id):
    """Admin view to restore mêlée players to their original teams"""
    tournament = get_object_or_404(Tournament, id=tournament_id)
    
    # Check if tournament is in Mêlée mode
    if not tournament.is_melee:
        messages.error(request, "This tournament is not configured for Mêlée mode.")
        return redirect('tournament_detail', tournament_id=tournament.id)
    
    if request.method == 'POST':
        # Perform the restoration
        restored_count = tournament.restore_melee_players_to_original_teams()
        
        if restored_count > 0:
            messages.success(request, f'Successfully restored {restored_count} players to their original teams.')
        else:
            messages.info(request, 'No players needed to be restored (they may already be in their original teams).')
        
        return redirect('tournament_detail', tournament_id=tournament.id)
    
    # GET request - show confirmation page
    melee_players = tournament.melee_players.all()
    players_to_restore = []
    
    for mp in melee_players:
        if mp.original_team and mp.player.team != mp.original_team:
            players_to_restore.append({
                'player': mp.player,
                'current_team': mp.player.team,
                'original_team': mp.original_team
            })
    
    context = {
        'tournament': tournament,
        'players_to_restore': players_to_restore,
        'total_players': len(players_to_restore),
        'is_complete': tournament.is_tournament_complete(),
    }
    
    return render(request, 'tournaments/restore_melee_players.html', context)

@user_passes_test(is_staff)
def tournament_check_completion(request, tournament_id):
    """Admin view to check tournament completion status and auto-restore if complete"""
    tournament = get_object_or_404(Tournament, id=tournament_id)
    
    if not tournament.is_melee:
        messages.error(request, "This tournament is not configured for Mêlée mode.")
        return redirect('tournament_detail', tournament_id=tournament.id)
    
    is_complete = tournament.is_tournament_complete()
    
    if is_complete:
        # Auto-restore players
        restored_count = tournament.auto_restore_players_on_completion()
        if restored_count > 0:
            messages.success(request, f'Tournament is complete! Auto-restored {restored_count} players to their original teams.')
        else:
            messages.info(request, 'Tournament is complete! All players are already in their original teams.')
    else:
        from matches.models import Match
        pending_matches = Match.objects.filter(
            tournament=tournament,
            status__in=['pending', 'pending_verification', 'active', 'waiting_validation']
        ).count()
        messages.info(request, f'Tournament is not yet complete. {pending_matches} matches are still pending.')
    
    return redirect('tournament_detail', tournament_id=tournament.id)

