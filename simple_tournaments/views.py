from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from django.db import transaction
from .models import TournamentScenario, VoucherCode, SimpleTournament
from .forms import TournamentCreationForm
from tournaments.models import Tournament, Stage, TournamentTeam
from teams.models import Team
from court_management.models import CourtComplex, Court
from matches.models import Match
import logging
import random
import string

logger = logging.getLogger(__name__)


def tournament_create(request):
    """Simple tournament creation interface."""
    if request.method == 'POST':
        form = TournamentCreationForm(request.POST)
        if form.is_valid():
            try:
                with transaction.atomic():
                    simple_tournament = _create_tournament(form.cleaned_data)
                    return redirect('simple_tournaments:tournament_success', pk=simple_tournament.pk)
            except Exception as e:
                logger.error(f"Error creating tournament: {e}")
                messages.error(request, f"Error creating tournament: {str(e)}")
    else:
        form = TournamentCreationForm()
    
    return render(request, 'simple_tournaments/create.html', {
        'form': form,
        'scenarios': TournamentScenario.objects.filter(is_active=True),
    })


def tournament_success(request, pk):
    """Tournament creation success page."""
    simple_tournament = get_object_or_404(SimpleTournament, pk=pk)
    
    context = {
        'tournament': simple_tournament,
        'team_pins': simple_tournament.get_team_pins(),
        'courts': simple_tournament.assigned_courts.all(),
        'tournament_url': f"/tournaments/{simple_tournament.tournament.id}/",
    }
    
    return render(request, 'simple_tournaments/success.html', context)


def check_voucher(request):
    """AJAX endpoint to check voucher validity."""
    if request.method == 'POST':
        voucher_code = request.POST.get('voucher_code', '').strip().upper()
        scenario_id = request.POST.get('scenario_id')
        
        try:
            scenario = TournamentScenario.objects.get(id=scenario_id)
            voucher = VoucherCode.objects.get(code=voucher_code, scenario=scenario)
            
            if voucher.is_valid():
                return JsonResponse({
                    'valid': True,
                    'message': f'Voucher valid for {scenario.name}'
                })
            else:
                return JsonResponse({
                    'valid': False,
                    'message': 'Voucher has already been used or expired'
                })
                
        except (TournamentScenario.DoesNotExist, VoucherCode.DoesNotExist):
            return JsonResponse({
                'valid': False,
                'message': 'Invalid voucher code'
            })
    
    return JsonResponse({'valid': False, 'message': 'Invalid request'})


def _create_tournament(data):
    """Create a complete tournament from form data."""
    scenario = data['scenario']
    format_type = data['format']
    court_complex = data['court_complex']
    voucher_code = data.get('voucher_code')
    creator_name = data.get('creator_name', 'Anonymous')
    
    # Validate and consume voucher if required
    voucher = None
    if not scenario.is_free:
        if not voucher_code:
            raise ValueError("Voucher code required for this scenario")
        
        voucher = VoucherCode.objects.get(code=voucher_code.upper(), scenario=scenario)
        if not voucher.is_valid():
            raise ValueError("Invalid or expired voucher code")
    
    # Generate tournament name
    tournament_name = f"{scenario.name} {format_type.title()} - {timezone.now().strftime('%Y%m%d_%H%M')}"
    
    # Create main tournament
    tournament = Tournament.objects.create(
        name=tournament_name,
        tournament_type='melee',
        is_multi_stage=False,
        status='active'
    )
    
    # Create stage
    stage = Stage.objects.create(
        tournament=tournament,
        name="Main Stage",
        stage_number=1,
        format=scenario.format_type,
        num_matches_per_team=scenario.matches_per_team,
        num_qualifiers=1,  # Winner takes all
        is_active=True
    )
    
    # Auto-assign courts (up to 5 available courts)
    available_courts = Court.objects.filter(
        complex=court_complex,
        is_available=True
    )[:5]
    
    if not available_courts:
        raise ValueError(f"No available courts in {court_complex.name}")
    
    # Create simple tournament record
    simple_tournament = SimpleTournament.objects.create(
        name=tournament_name,
        scenario=scenario,
        format=format_type,
        court_complex=court_complex,
        tournament=tournament,
        voucher_used=voucher,
        created_by=creator_name,
        status='created'
    )
    
    # Assign courts
    simple_tournament.assigned_courts.set(available_courts)
    
    # Consume voucher
    if voucher:
        voucher.is_used = True
        voucher.used_by = creator_name
        voucher.used_at = timezone.now()
        voucher.used_for_tournament = tournament
        voucher.save()
    
    # Build teams and generate matches
    _build_teams_and_matches(simple_tournament, stage, format_type, scenario)
    
    # Update status
    simple_tournament.status = 'active'
    simple_tournament.save()
    
    logger.info(f"Created simple tournament: {tournament_name}")
    return simple_tournament


def _build_teams_and_matches(simple_tournament, stage, format_type, scenario):
    """Build teams and generate matches for the tournament."""
    # Determine team size and count
    if format_type == 'doubles':
        team_size = 2
        max_players = scenario.max_players_doubles
    else:  # triples
        team_size = 3
        max_players = scenario.max_players_triples
    
    num_teams = max_players // team_size
    
    # Create mêlée teams
    teams_created = []
    for i in range(1, num_teams + 1):
        team_name = f"Mêlée Team {i}"
        team_pin = _generate_team_pin()
        
        team = Team.objects.create(
            name=team_name,
            pin=team_pin,
            complex=simple_tournament.court_complex
        )
        
        # Add team to tournament
        tournament_team = TournamentTeam.objects.create(
            tournament=simple_tournament.tournament,
            team=team,
            stage=stage
        )
        
        teams_created.append(team)
    
    # Track created teams for cleanup
    simple_tournament.created_teams.set(teams_created)
    
    # Generate matches based on scenario
    if scenario.format_type == 'swiss':
        _generate_swiss_matches(stage, teams_created)
    elif scenario.format_type == 'partial_robin':
        _generate_partial_robin_matches(stage, teams_created, scenario.matches_per_team)
    
    logger.info(f"Created {len(teams_created)} teams and generated matches for {simple_tournament.name}")


def _generate_team_pin():
    """Generate a unique 6-digit team PIN."""
    while True:
        pin = ''.join(random.choices(string.digits, k=6))
        if not Team.objects.filter(pin=pin).exists():
            return pin


def _generate_swiss_matches(stage, teams):
    """Generate Swiss system matches."""
    # For simplicity, generate first round matches randomly
    # In a full implementation, this would use proper Swiss pairing
    teams_list = list(teams)
    random.shuffle(teams_list)
    
    # Create first round
    from tournaments.models import Round
    round_obj = Round.objects.create(
        tournament=stage.tournament,
        stage=stage,
        round_number=1
    )
    
    # Pair teams
    for i in range(0, len(teams_list), 2):
        if i + 1 < len(teams_list):
            Match.objects.create(
                tournament=stage.tournament,
                round=round_obj,
                team1=teams_list[i],
                team2=teams_list[i + 1],
                status="pending"
            )


def _generate_partial_robin_matches(stage, teams, matches_per_team):
    """Generate partial round robin matches."""
    # Use the existing Smart Robin algorithm
    from tournaments.models import Round
    round_obj = Round.objects.create(
        tournament=stage.tournament,
        stage=stage,
        round_number=1
    )
    
    # Convert teams to tournament teams for the algorithm
    tournament_teams = []
    for team in teams:
        tournament_team = TournamentTeam.objects.get(team=team, tournament=stage.tournament)
        tournament_teams.append(tournament_team)
    
    # Use the stage's partial round robin generation
    stage.num_matches_per_team = matches_per_team
    stage.save()
    stage._generate_partial_round_robin_matches(tournament_teams, round_obj)

