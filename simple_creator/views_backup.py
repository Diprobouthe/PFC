from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.utils import timezone
from django.db import transaction
from datetime import datetime, timedelta
import random
import string

from .models import TournamentScenario, VoucherCode, SimpleTournament
from .forms import SimpleTournamentCreationForm
from tournaments.models import Tournament, Stage, MeleePlayer
from teams.models import Team, Player
from courts.models import Court


def simple_tournament_home(request):
    """Home page for simple tournament creation"""
    scenarios = TournamentScenario.objects.all().order_by('is_free', 'name')
    return render(request, 'simple_creator/home.html', {
        'scenarios': scenarios
    })


def create_tournament(request):
    """Simple tournament creation view"""
    if request.method == 'POST':
        form = SimpleTournamentCreationForm(request.POST)
        if form.is_valid():
            try:
                with transaction.atomic():
                    # Create the tournament
                    simple_tournament = _create_simple_tournament(form.cleaned_data)
                    
                    # Redirect to success page
                    return redirect('simple_creator:tournament_success', pk=simple_tournament.pk)
                    
            except Exception as e:
                messages.error(request, f'Error creating tournament: {str(e)}')
                
    else:
        form = SimpleTournamentCreationForm()
    
    return render(request, 'simple_creator/create.html', {
        'form': form
    })


def tournament_success(request, pk):
    """Tournament creation success page"""
    simple_tournament = get_object_or_404(SimpleTournament, pk=pk)
    
    # Get team PINs
    team_pins = []
    for team in simple_tournament.tournament.teams.all():
        team_pins.append({
            'name': team.name,
            'pin': team.pin
        })
    
    # Get assigned courts
    real_courts = simple_tournament.tournament.courts.all()
    assigned_courts = [{
        'name': court.name,
        'court_number': court.id
    } for court in real_courts]
    
    return render(request, 'simple_creator/success.html', {
        'simple_tournament': simple_tournament,
        'team_pins': team_pins,
        'assigned_courts': assigned_courts
    })


def _create_simple_tournament(form_data):
    """Create a simple tournament using virtual courts"""
    import traceback
    try:
        scenario = form_data['scenario']
        format_type = form_data['format_type']
        num_courts = form_data['num_courts']
        voucher_code = form_data.get('voucher_code')
    except Exception as e:
        with open('/tmp/tournament_create_error.log', 'a') as f:
            f.write(f'ERROR in form data extraction: {e}\n')
            f.write(traceback.format_exc())
        raise
    
    # Validate and get voucher if provided
    voucher_object = None
    if voucher_code:
        try:
            voucher_object = VoucherCode.objects.get(
                code=voucher_code,
                scenario=scenario,
                is_used=False
            )
        except VoucherCode.DoesNotExist:
            raise ValueError(f"Invalid or already used voucher code: {voucher_code}")
    
    # Generate auto dates (next day)
    start_date, end_date = SimpleTournament.get_auto_dates()
    
    # Create the main tournament
    tournament_name = f"{scenario.display_name} {format_type.title()} - {start_date.strftime('%Y-%m-%d')}"
    
    tournament = Tournament.objects.create(
        name=tournament_name,
        description=f"Auto-generated {scenario.display_name} tournament with {num_courts} virtual courts",
        start_date=start_date,
        end_date=end_date,
        format="multi_stage",  # Use multi-stage for flexibility
        play_format="triplets" if format_type == "triples" else "doublets",
        is_active=True,
        max_participants=scenario.max_triples_players if format_type == "triples" else scenario.max_doubles_players,
        is_melee=True,  # This is a mêlée tournament
        melee_teams_generated=False,
        automation_status="idle"
    )
    
    # Require court complex from scenario
    if not scenario.default_court_complex:
        raise ValueError(f"Scenario '{scenario.display_name}' does not have a default court complex set. Please configure it in the admin panel.")
    
    court_complex = scenario.default_court_complex
    print(f"DEBUG: Using court complex: {court_complex.name}")
    
    # Create the simple tournament record
    simple_tournament = SimpleTournament.objects.create(
        tournament=tournament,
        scenario=scenario,
        format_type=format_type,
        uses_virtual_courts=False,  # Always use real courts
        num_courts=num_courts,
        court_complex=court_complex,
        voucher_used=voucher_object,
        auto_start_date=start_date,
        auto_end_date=end_date
    )
    
    # Assign real courts from the court complex
    print(f"DEBUG: Assigning courts from {court_complex.name}")
    available_courts = Court.objects.filter(courtcomplex=court_complex, is_available=True)[:num_courts]
    print(f"DEBUG: Found {available_courts.count()} available courts")
    
    if available_courts.count() < num_courts:
        raise ValueError(f"Court complex '{court_complex.name}' only has {available_courts.count()} available courts, but {num_courts} were requested.")
    
    # Assign courts to tournament using TournamentCourt intermediate model
    from tournaments.models import TournamentCourt
    for court in available_courts:
        tc = TournamentCourt.objects.create(tournament=tournament, court=court)
        print(f"DEBUG: Created TournamentCourt {tc.id} for court {court.name}")
    print(f"DEBUG: Total TournamentCourt objects created: {TournamentCourt.objects.filter(tournament=tournament).count()}")
    
    # Use voucher if provided
    if voucher_object:
        voucher_object.use_voucher(tournament)
    
    # Create tournament stage based on scenario
    from tournaments.models import Stage
    stage = Stage.objects.create(
        tournament=tournament,
        name="Main Stage",
        stage_number=1,
        stage_type=scenario.tournament_type,
        num_qualifiers=1,  # Winner takes all for simple tournaments
        is_complete=False
    )
    
    # Handle multi-stage scenarios if defined
    if scenario.stages:
        try:
            import json
            stages_config = json.loads(scenario.stages) if isinstance(scenario.stages, str) else scenario.stages
            
            # Create additional stages based on configuration
            for i, stage_config in enumerate(stages_config[1:], start=2):  # Skip first stage already created
                Stage.objects.create(
                    tournament=tournament,
                    name=stage_config.get('name', f"Stage {i}"),
                    stage_number=i,
                    stage_type=stage_config.get('type', 'knockout'),
                    num_qualifiers=stage_config.get('qualifiers', 1),
                    is_complete=False
                )
        except (json.JSONDecodeError, KeyError, TypeError):
            # If stages configuration is invalid, continue with single stage
            pass
    
    # No real court assignment needed - virtual courts handle scheduling
    
    return simple_tournament


@require_http_methods(["GET"])
def scenario_details(request, scenario_id):
    """AJAX endpoint to get scenario details"""
    try:
        scenario = TournamentScenario.objects.get(id=scenario_id)
        return JsonResponse({
            'success': True,
            'data': {
                'name': scenario.display_name,
                'description': scenario.description,
                'is_free': scenario.is_free,
                'requires_voucher': scenario.requires_voucher,
                'max_doubles_players': scenario.max_doubles_players,
                'max_triples_players': scenario.max_triples_players,
                'tournament_type': scenario.get_tournament_type_display(),
                'draft_type': scenario.get_draft_type_display(),
                'num_rounds': scenario.num_rounds,
                'matches_per_team': scenario.matches_per_team
            }
        })
    except TournamentScenario.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Scenario not found'
        })


@require_http_methods(["POST"])
def validate_voucher(request):
    """AJAX endpoint to validate voucher codes"""
    voucher_code = request.POST.get('voucher_code', '').strip()
    scenario_id = request.POST.get('scenario_id')
    
    if not voucher_code or not scenario_id:
        return JsonResponse({
            'success': False,
            'error': 'Missing voucher code or scenario'
        })
    
    try:
        scenario = TournamentScenario.objects.get(id=scenario_id)
        voucher = VoucherCode.objects.get(
            code=voucher_code,
            scenario=scenario,
            is_used=False
        )
        
        return JsonResponse({
            'success': True,
            'message': f'Valid voucher for {scenario.display_name}'
        })
        
    except TournamentScenario.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Invalid scenario'
        })
    except VoucherCode.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Invalid or already used voucher code'
        })


def tournament_list(request):
    """List of simple tournaments"""
    tournaments = SimpleTournament.objects.all().order_by('-created_at')
    return render(request, 'simple_creator/list.html', {
        'tournaments': tournaments
    })


def tournament_detail(request, pk):
    """Detail view for a simple tournament"""
    simple_tournament = get_object_or_404(SimpleTournament, pk=pk)
    
    # Check if tournament is completed and trigger cleanup
    simple_tournament.check_completion()
    
    return render(request, 'simple_creator/detail.html', {
        'simple_tournament': simple_tournament
    })
