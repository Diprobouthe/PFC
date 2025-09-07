"""
Simple MELE Tournament Creator
Creates tournaments using existing admin infrastructure without model changes
"""
from django.shortcuts import render, redirect
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.utils import timezone
from django.db import transaction
from datetime import datetime, timedelta
import random
import string

from tournaments.models import Tournament, Stage
from teams.models import Team, Player
from courts.models import CourtComplex, Court

# Import Simple Creator models for dynamic scenario loading
try:
    from simple_creator.models import TournamentScenario, VoucherCode
    USE_DYNAMIC_SCENARIOS = True
except ImportError:
    USE_DYNAMIC_SCENARIOS = False

# Fallback hardcoded scenarios (if models not available)
FALLBACK_SCENARIOS = {
    'fair': {
        'name': 'Fair',
        'description': 'Balanced tournament with Swiss rounds',
        'is_free': True,
        'tournament_type': 'swiss',
        'draft_type': 'balance',
        'num_rounds': 3,
        'max_doubles': 12,
        'max_triples': 18,
    },
    'madness': {
        'name': 'Madness',
        'description': 'Exciting tournament with partial round robin',
        'is_free': False,
        'tournament_type': 'round_robin',
        'draft_type': 'snake',
        'matches_per_team': 3,
        'max_doubles': 12,
        'max_triples': 18,
    }
}

# Fallback hardcoded voucher codes (if models not available)
VOUCHER_CODES = {
    'MAD58RJU': {
        'used': False,
        'scenario': 'madness'
    },
    'MAD58RJJ': {
        'used': False,
        'scenario': 'madness'
    },
    'SWISS123': {
        'used': False,
        'scenario': 'swiss_plus_random'
    },
    'MADNESS1': {
        'used': False,
        'scenario': 'madness_for_more'
    }
}

def get_available_scenarios():
    """Get all available tournament scenarios from database or fallback"""
    if USE_DYNAMIC_SCENARIOS:
        try:
            scenarios = {}
            for scenario in TournamentScenario.objects.all():
                scenarios[scenario.name] = {
                    'id': scenario.id,
                    'name': scenario.display_name,
                    'description': scenario.description,
                    'is_free': scenario.is_free,
                    'tournament_type': scenario.tournament_type,
                    'draft_type': scenario.draft_type,
                    'num_rounds': scenario.num_rounds,
                    'matches_per_team': getattr(scenario, 'matches_per_team', 3),
                    'max_doubles': scenario.max_doubles_players,
                    'max_triples': scenario.max_triples_players,
                }
            return scenarios
        except Exception:
            pass
    
    # Fallback to hardcoded scenarios
    return FALLBACK_SCENARIOS


def simple_creator_home(request):
    """Simple tournament creator home page"""
    return render(request, 'simple_creator.html', {
        'scenarios': get_available_scenarios(),
        'court_complexes': CourtComplex.objects.all()
    })


def create_simple_tournament(request):
    """Create a simple tournament using existing admin infrastructure"""
    if request.method != 'POST':
        return redirect('simple_creator_home')
    
    try:
        # Get form data
        scenario_key = request.POST.get('scenario')
        format_type = request.POST.get('format')
        court_complex_id = request.POST.get('court_complex')
        voucher_code = request.POST.get('voucher_code', '').strip()
        
        # Validate inputs
        if not all([scenario_key, format_type, court_complex_id]):
            messages.error(request, 'Please fill all required fields')
            return redirect('simple_creator_home')
        
        scenarios = get_available_scenarios()
        scenario = scenarios.get(scenario_key)
        if not scenario:
            messages.error(request, 'Invalid scenario selected')
            return redirect('simple_creator_home')
        
        # Validate voucher for paid scenarios
        if not scenario['is_free']:
            if USE_DYNAMIC_SCENARIOS:
                # Use VoucherCode model
                try:
                    print(f"DEBUG: Looking for voucher code: {voucher_code}")
                    print(f"DEBUG: Scenario key: {scenario_key}")
                    voucher = VoucherCode.objects.get(code=voucher_code, is_used=False)
                    print(f"DEBUG: Found voucher: {voucher.code}, scenario: {voucher.scenario.name}")
                    if voucher.scenario.name != scenario_key:
                        print(f"DEBUG: Scenario mismatch: {voucher.scenario.name} != {scenario_key}")
                        messages.error(request, 'Voucher code is not valid for this scenario')
                        return redirect('simple_creator_home')
                except VoucherCode.DoesNotExist:
                    print(f"DEBUG: Voucher not found or already used")
                    messages.error(request, 'Invalid or already used voucher code')
                    return redirect('simple_creator_home')
            else:
                # Fallback to hardcoded vouchers
                if not voucher_code or voucher_code not in VOUCHER_CODES:
                    messages.error(request, 'Valid voucher code required for this scenario')
                    return redirect('simple_creator_home')
                
                voucher = VOUCHER_CODES[voucher_code]
                if voucher['used'] or voucher['scenario'] != scenario_key:
                    messages.error(request, 'Invalid or already used voucher code')
                    return redirect('simple_creator_home')
        
        # Get court complex and available courts
        try:
            court_complex = CourtComplex.objects.get(id=court_complex_id)
        except CourtComplex.DoesNotExist:
            messages.error(request, 'Invalid court complex selected')
            return redirect('simple_creator_home')
        
        available_courts = list(Court.objects.filter(
            courtcomplex=court_complex,
            is_available=True
        ))
        
        if not available_courts:
            messages.error(request, f'No available courts at {court_complex.name}')
            return redirect('simple_creator_home')
        
        # Randomly select up to 5 available courts
        selected_courts = random.sample(available_courts, min(5, len(available_courts)))
        
        # Auto-generate dates (next day)
        tomorrow = timezone.now().date() + timedelta(days=1)
        start_datetime = timezone.make_aware(datetime.combine(tomorrow, datetime.min.time().replace(hour=9)))
        end_datetime = timezone.make_aware(datetime.combine(tomorrow, datetime.min.time().replace(hour=18)))
        
        # Create tournament using existing admin infrastructure
        max_teams = scenario[f'max_{format_type}']
        max_players = scenario[f'max_{format_type}']  # Use scenario limit for max participants
        tournament_name = f"{scenario['name']} {format_type.title()} - {tomorrow.strftime('%Y-%m-%d')}"
        
        tournament = Tournament.objects.create(
            name=tournament_name,
            description=f"Simple {scenario['name']} tournament",
            start_date=start_datetime,
            end_date=end_datetime,
            format="multi_stage",
            play_format="triplets" if format_type == "triples" else "doublets",
            has_triplets=(format_type == "triples"),
            has_doublets=(format_type == "doubles"),
            is_active=True,
            is_melee=True,
            melee_format="triplets" if format_type == "triples" else "doublets",
            melee_teams_generated=False,
            automation_status="idle",
            max_participants=max_players  # Set registration limit based on scenario
        )
        
        # Create tournament stage
        stage = Stage.objects.create(
            tournament=tournament,
            name="Main Stage",
            stage_number=1,
            format=scenario['tournament_type'],
            num_qualifiers=1,
            is_complete=False
        )
        
        if scenario['tournament_type'] == 'swiss':
            stage.num_rounds_in_stage = scenario['num_rounds']
        else:  # round_robin
            stage.num_rounds_in_stage = scenario['num_rounds']
            stage.num_matches_per_team = scenario['matches_per_team']
        stage.save()
        
        # Assign selected courts
        for court in selected_courts:
            tournament.courts.add(court)
        
        # Use voucher if provided
        if not scenario['is_free'] and voucher_code:
            if USE_DYNAMIC_SCENARIOS:
                # Mark database voucher as used
                voucher.is_used = True
                voucher.used_at = timezone.now()
                voucher.used_for_tournament = tournament
                voucher.save()
                print(f"DEBUG: Marked voucher {voucher_code} as used for tournament {tournament.id}")
            else:
                # Mark hardcoded voucher as used
                VOUCHER_CODES[voucher_code]['used'] = True
        
        # Store creation info for success page
        request.session['simple_tournament_info'] = {
            'tournament_id': tournament.id,
            'tournament_name': tournament.name,
            'scenario': scenario['name'],
            'format': format_type.title(),
            'court_complex': court_complex.name,
            'selected_courts': [{'name': c.name, 'number': c.number} for c in selected_courts],
            'start_date': start_datetime.strftime('%Y-%m-%d %H:%M'),
            'voucher_used': voucher_code if not scenario['is_free'] else None,
            'registration_link': f'/tournaments/{tournament.id}/',
            'management_link': f'/simple/manage/{tournament.id}/',
            'status': 'created',  # Tournament created but not started
        }
        
        messages.success(request, f'Tournament "{tournament_name}" created successfully!')
        return redirect('simple_creator_success')
        
    except Exception as e:
        messages.error(request, f'Error creating tournament: {str(e)}')
        return redirect('simple_creator_home')


def simple_creator_success(request):
    """Tournament creation success page"""
    tournament_info = request.session.get('simple_tournament_info')
    if not tournament_info:
        return redirect('simple_creator_home')
    
    return render(request, 'simple_creator_success.html', {
        'tournament_info': tournament_info
    })


def manage_tournament(request, tournament_id):
    """Tournament management page for game creator"""
    try:
        tournament = Tournament.objects.get(id=tournament_id)
        
        # Get registered players (MeleePlayer objects)
        from tournaments.models import MeleePlayer
        registered_players = MeleePlayer.objects.filter(tournament=tournament).select_related('player')
        
        # Get tournament teams if generated
        team_pins = []
        if tournament.melee_teams_generated:
            for team in tournament.teams.all():
                if team.pin and team.name.startswith('Mêlée Team'):
                    team_pins.append({
                        'name': team.name,
                        'pin': team.pin,
                        'players': [p.name for p in team.players.all()]
                    })
        
        # Get scenario info for team generation
        scenario_key = 'fair' if 'Fair' in tournament.name else 'madness'
        scenarios = get_available_scenarios()
        scenario = scenarios.get(scenario_key, scenarios.get('fair', {}))
        
        context = {
            'tournament': tournament,
            'registered_players': registered_players,
            'player_count': registered_players.count(),
            'team_pins': team_pins,
            'scenario': scenario,
            'can_start': registered_players.count() >= 4 and not tournament.melee_teams_generated,
            'is_started': tournament.melee_teams_generated,
        }
        
        return render(request, 'simple_tournament_manage.html', context)
        
    except Tournament.DoesNotExist:
        messages.error(request, 'Tournament not found')
        return redirect('simple_creator_home')


def start_tournament(request, tournament_id):
    """Start tournament - generate teams and matches automatically"""
    if request.method != 'POST':
        return redirect('manage_tournament', tournament_id=tournament_id)
    
    try:
        tournament = Tournament.objects.get(id=tournament_id)
        
        if tournament.melee_teams_generated:
            messages.error(request, 'Tournament has already been started')
            return redirect('manage_tournament', tournament_id=tournament_id)
        
        # Get scenario info
        scenario_key = 'fair' if 'Fair' in tournament.name else 'madness'
        scenarios = get_available_scenarios()
        scenario = scenarios.get(scenario_key, scenarios.get('fair', {}))
        
        # Generate teams based on scenario using admin function
        algorithm = scenario.get('draft_type', 'balance')  # 'balance' or 'snake'
        
        try:
            teams_created = tournament.generate_melee_teams(algorithm)
            
            if teams_created > 0:
                # Use existing tournament automation - just call generate_matches()
                matches_created = tournament.generate_matches()
                
                if matches_created and matches_created > 0:
                    messages.success(request, f'Tournament started! Generated {teams_created} teams and {matches_created} matches.')
                else:
                    messages.warning(request, f'Teams generated ({teams_created}) but no matches created. Check tournament configuration.')
            else:
                messages.error(request, 'Failed to generate teams. Please check player registrations.')
                
        except Exception as e:
            messages.error(request, f'Error starting tournament: {str(e)}')
        
        return redirect('manage_tournament', tournament_id=tournament_id)
        
    except Tournament.DoesNotExist:
        messages.error(request, 'Tournament not found')
        return redirect('simple_creator_home')
    except Exception as e:
        messages.error(request, f'Error starting tournament: {str(e)}')
        return redirect('manage_tournament', tournament_id=tournament_id)


@require_http_methods(["GET"])
def get_available_courts(request):
    """AJAX endpoint to get available courts for a court complex"""
    complex_id = request.GET.get('complex_id')
    if not complex_id:
        return JsonResponse({'error': 'Complex ID required'}, status=400)
    
    try:
        court_complex = CourtComplex.objects.get(id=complex_id)
        available_courts = Court.objects.filter(
            courtcomplex=court_complex,
            is_available=True
        ).values('id', 'name', 'number')
        
        return JsonResponse({
            'success': True,
            'courts': list(available_courts),
            'count': len(available_courts)
        })
    except CourtComplex.DoesNotExist:
        return JsonResponse({'error': 'Court complex not found'}, status=404)


@require_http_methods(["POST"])
def validate_voucher(request):
    """AJAX endpoint to validate voucher codes"""
    voucher_code = request.POST.get('voucher_code', '').strip()
    scenario = request.POST.get('scenario', '')
    
    if not voucher_code:
        return JsonResponse({'error': 'Voucher code required'}, status=400)
    
    if voucher_code not in VOUCHER_CODES:
        return JsonResponse({'error': 'Invalid voucher code'}, status=400)
    
    voucher = VOUCHER_CODES[voucher_code]
    if voucher['used']:
        return JsonResponse({'error': 'Voucher code already used'}, status=400)
    
    if voucher['scenario'] != scenario:
        return JsonResponse({'error': 'Voucher not valid for this scenario'}, status=400)
    
    return JsonResponse({'success': True, 'message': 'Valid voucher code'})


def cleanup_empty_mele_teams(request, tournament_id):
    """Admin action to cleanup empty MELE teams for a tournament"""
    if not request.user.is_staff:
        messages.error(request, 'Admin access required')
        return redirect('simple_creator_home')
    
    try:
        tournament = Tournament.objects.get(id=tournament_id)
        
        # Only delete MELE teams that are empty
        mele_teams = tournament.teams.filter(name__startswith='Mêlée Team')
        deleted_count = 0
        
        for team in mele_teams:
            if team.players.count() == 0:  # Only delete if completely empty
                team_name = team.name
                team.delete()
                deleted_count += 1
        
        messages.success(request, f'Deleted {deleted_count} empty MELE teams from tournament "{tournament.name}"')
        
    except Tournament.DoesNotExist:
        messages.error(request, 'Tournament not found')
    except Exception as e:
        messages.error(request, f'Error cleaning up teams: {str(e)}')
    
    return redirect('simple_creator_home')

