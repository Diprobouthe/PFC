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
                    'scenario_mode': getattr(scenario, 'scenario_mode', 'melee'),
                    'tournament_type': scenario.tournament_type,
                    'draft_type': scenario.draft_type,
                    'num_rounds': scenario.num_rounds,
                    'matches_per_team': getattr(scenario, 'matches_per_team', 3),
                    # Supported formats — drives which format cards are shown in the creator
                    'supports_singles': getattr(scenario, 'supports_singles', False),
                    'supports_doubles': getattr(scenario, 'supports_doubles', True),
                    'supports_triples': getattr(scenario, 'supports_triples', True),
                    'max_singles': scenario.max_singles_players,
                    'max_doubles': scenario.max_doubles_players,
                    'max_triples': scenario.max_triples_players,
                    'pregame_countdown_minutes': getattr(scenario, 'pregame_countdown_minutes', None),
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
        # No longer need court_complexes for virtual courts
    })


def create_simple_tournament(request):
    """Create a simple tournament using virtual courts"""
    if request.method != 'POST':
        return redirect('simple_creator_home')
    
    try:
        # Get form data
        scenario_key = request.POST.get('scenario')
        format_type = request.POST.get('format')
        num_courts = int(request.POST.get('num_courts', 3))
        voucher_code = request.POST.get('voucher_code', '').strip()
        
        # Validate inputs
        if not all([scenario_key, format_type, num_courts]):
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
        
        # Auto-generate dates (next day)
        tomorrow = timezone.now().date() + timedelta(days=1)
        start_datetime = timezone.make_aware(datetime.combine(tomorrow, datetime.min.time().replace(hour=9)))
        end_datetime = timezone.make_aware(datetime.combine(tomorrow, datetime.min.time().replace(hour=18)))
        
        # Create tournament using virtual courts
        # 'singles' maps to max_singles; 'doubles' to max_doubles; 'triples' to max_triples
        max_players = scenario.get(f'max_{format_type}', 24)
        tournament_name = f"{scenario['name']} {format_type.title()} - {tomorrow.strftime('%Y-%m-%d')}"
        
        # Determine scenario mode (default to 'melee' for backwards compatibility)
        scenario_mode = scenario.get('scenario_mode', 'melee')
        is_melee_mode = scenario_mode in ('melee', 'super_melee')
        is_super_melee = scenario_mode == 'super_melee'
        is_team_mode = scenario_mode == 'team'

        # Get timer and pregame countdown from scenario
        timer_minutes = scenario.get('pregame_countdown_minutes', None)  # match time limit
        pregame_countdown = None
        if USE_DYNAMIC_SCENARIOS and 'id' in scenario:
            try:
                scenario_obj = TournamentScenario.objects.get(id=scenario['id'])
                timer_minutes = scenario_obj.default_time_limit_minutes
                pregame_countdown = scenario_obj.pregame_countdown_minutes  # may be None
            except TournamentScenario.DoesNotExist:
                pass

        # Build tournament kwargs based on mode.
        # Tournament.save() derives play_format from the boolean flags, so we must set the
        # correct flag for each format:
        #   singles  → has_tete_a_tete=True  (play_format='tete_a_tete')
        #   doubles  → has_doublets=True      (play_format='doublets')
        #   triples  → has_triplets=True      (play_format='triplets')
        _play_fmt_map = {
            'singles': 'tete_a_tete',
            'doubles': 'doublets',
            'triples': 'triplets',
        }
        _play_fmt = _play_fmt_map.get(format_type, 'doublets')
        tournament_kwargs = dict(
            name=tournament_name,
            description=f"Simple {scenario['name']} tournament ({scenario_mode.replace('_', ' ').title()}) with {num_courts} courts",
            start_date=start_datetime,
            end_date=end_datetime,
            format="multi_stage",
            play_format=_play_fmt,
            has_tete_a_tete=(format_type == 'singles'),
            has_doublets=(format_type == 'doubles'),
            has_triplets=(format_type == 'triples'),
            is_active=True,
            automation_status="idle",
            default_time_limit_minutes=timer_minutes,
        )
        if pregame_countdown is not None:
            tournament_kwargs['pregame_countdown_minutes'] = pregame_countdown

        if is_melee_mode:
            # Mêlée and Super Mêlée: individual player registration, dynamic team generation
            # singles → tete_a_tete (1-player temp teams); doubles → doublets; triples → triplets
            _melee_fmt = {
                'singles': 'tete_a_tete',
                'doubles': 'doublets',
                'triples': 'triplets',
            }.get(format_type, 'doublets')
            tournament_kwargs.update(
                is_melee=True,
                melee_format=_melee_fmt,
                melee_teams_generated=False,
                max_participants=max_players,
                shuffle_players_after_round=is_super_melee,
            )
        else:
            # Normal Team Tournament: team-based registration, no melee
            tournament_kwargs.update(
                is_melee=False,
                melee_teams_generated=False,
                max_participants=None,  # Team tournaments use team count, not player count
            )

        tournament = Tournament.objects.create(**tournament_kwargs)
        
        # Assign real courts from scenario's default court complex
        from tournaments.models import TournamentCourt
        try:
            scenario_obj = TournamentScenario.objects.get(name=scenario_key)
            if not scenario_obj.default_court_complex:
                raise ValueError(f"Scenario '{scenario['name']}' does not have a default court complex assigned")
            
            # Get available courts from the scenario's court complex
            available_courts = Court.objects.filter(
                courtcomplex=scenario_obj.default_court_complex,
                is_available=True
            ).order_by('name')[:num_courts]
            
            if available_courts.count() < num_courts:
                raise ValueError(f"Not enough courts available in {scenario_obj.default_court_complex.name}. Requested: {num_courts}, Available: {available_courts.count()}")
            
            # Assign courts to tournament
            for court in available_courts:
                TournamentCourt.objects.create(
                    tournament=tournament,
                    court=court
                )
            
            print(f"DEBUG: Assigned {available_courts.count()} courts from {scenario_obj.default_court_complex.name}")
        except Exception as e:
            print(f"ERROR: Failed to assign courts: {str(e)}")
            tournament.delete()
            raise
        
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
        
        # No real court assignment needed for virtual courts
        
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
        real_courts = [{'name': court.name, 'number': idx+1} for idx, court in enumerate(available_courts)]
        
        request.session['simple_tournament_info'] = {
            'tournament_id': tournament.id,
            'tournament_name': tournament.name,
            'scenario': scenario['name'],
            'scenario_mode': scenario_mode,
            'format': format_type.title(),
            'court_complex': scenario_obj.default_court_complex.name,
            'selected_courts': real_courts,
            'num_courts': num_courts,
            'start_date': start_datetime.strftime('%Y-%m-%d %H:%M'),
            'voucher_used': voucher_code if not scenario['is_free'] else None,
            'registration_link': f'/tournaments/{tournament.id}/',
            'management_link': f'/simple/manage/{tournament.id}/',
            'status': 'created',
        }
        
        messages.success(request, f'Tournament "{tournament_name}" created successfully with {num_courts} courts from {scenario_obj.default_court_complex.name}!')
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
        from tournaments.models import MeleePlayer, TournamentTeam

        is_melee_mode = tournament.is_melee

        if is_melee_mode:
            # Mêlée / Super Mêlée: show individual player registrations
            registered_players = MeleePlayer.objects.filter(tournament=tournament).select_related('player')
            registered_teams = None
            team_count = 0

            # Collect generated team PINs
            team_pins = []
            if tournament.melee_teams_generated:
                for team in tournament.teams.all():
                    if team.pin and team.name.startswith('Mêlée Team'):
                        team_pins.append({
                            'name': team.name,
                            'pin': team.pin,
                            'players': [p.name for p in team.players.all()]
                        })

            can_start = registered_players.count() >= 4 and not tournament.melee_teams_generated
            is_started = tournament.melee_teams_generated
        else:
            # Normal Team Tournament: show registered teams
            registered_players = None
            registered_teams = TournamentTeam.objects.filter(
                tournament=tournament, is_active=True
            ).select_related('team').prefetch_related('team__players')
            team_count = registered_teams.count()
            team_pins = []

            # For team tournaments, "started" means matches have been generated
            from matches.models import Match
            has_matches = Match.objects.filter(tournament=tournament).exists()
            can_start = team_count >= 2 and not has_matches
            is_started = has_matches

        # Determine scenario mode label
        if is_melee_mode:
            mode_label = 'Super Mêlée' if tournament.shuffle_players_after_round else 'Mêlée'
        else:
            mode_label = 'Team Tournament'

        context = {
            'tournament': tournament,
            'is_melee_mode': is_melee_mode,
            'mode_label': mode_label,
            'registered_players': registered_players,
            'player_count': registered_players.count() if registered_players is not None else 0,
            'registered_teams': registered_teams,
            'team_count': team_count,
            'team_pins': team_pins,
            'can_start': can_start,
            'is_started': is_started,
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

        if tournament.is_melee:
            # ---- Mêlée / Super Mêlée path ----
            if tournament.melee_teams_generated:
                messages.error(request, 'Tournament has already been started')
                return redirect('manage_tournament', tournament_id=tournament_id)

            # Determine draft algorithm from scenario
            scenarios = get_available_scenarios()
            # Try to find the matching scenario by name fragment
            scenario = None
            for key, s in scenarios.items():
                if key in tournament.name or s.get('name', '') in tournament.name:
                    scenario = s
                    break
            algorithm = scenario.get('draft_type', 'balance') if scenario else 'balance'

            try:
                teams_created = tournament.generate_melee_teams(algorithm)
                if teams_created > 0:
                    matches_created = tournament.generate_matches()
                    if matches_created and matches_created > 0:
                        messages.success(request, f'Tournament started! Generated {teams_created} teams and {matches_created} matches.')
                    else:
                        messages.warning(request, f'Teams generated ({teams_created}) but no matches created. Check tournament configuration.')
                else:
                    messages.error(request, 'Failed to generate teams. Please check player registrations.')
            except Exception as e:
                messages.error(request, f'Error generating teams: {str(e)}')

        else:
            # ---- Normal Team Tournament path ----
            from matches.models import Match
            if Match.objects.filter(tournament=tournament).exists():
                messages.error(request, 'Tournament has already been started (matches exist)')
                return redirect('manage_tournament', tournament_id=tournament_id)

            from tournaments.models import TournamentTeam
            team_count = TournamentTeam.objects.filter(tournament=tournament, is_active=True).count()
            if team_count < 2:
                messages.error(request, f'Need at least 2 registered teams to start. Currently: {team_count}')
                return redirect('manage_tournament', tournament_id=tournament_id)

            try:
                matches_created = tournament.generate_matches()
                if matches_created and matches_created > 0:
                    messages.success(request, f'Tournament started! Generated {matches_created} matches for {team_count} teams.')
                else:
                    messages.warning(request, 'No matches were created. Check tournament stage configuration.')
            except Exception as e:
                messages.error(request, f'Error generating matches: {str(e)}')

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
    
    import logging as _logging
    _cc_logger = _logging.getLogger('pfc_core')
    try:
        tournament = Tournament.objects.get(id=tournament_id)
        
        # Step 1: Restore players to their original teams first.
        # This must happen before any team deletion attempt.
        if tournament.is_melee:
            tournament.restore_melee_players_to_original_teams()
        
        # Step 2: Delete only temp teams that are now empty.
        mele_teams = tournament.teams.filter(is_tournament_temp=True)
        deleted_count = 0
        skipped_count = 0
        
        for team in mele_teams:
            remaining = team.players.count()
            if remaining == 0:
                team_name = team.name
                team.delete()
                deleted_count += 1
            else:
                # Safety guard: players not fully restored — do NOT delete.
                _cc_logger.error(
                    f"SAFETY ABORT: Cannot delete temp team '{team.name}' "
                    f"(id={team.id}) — {remaining} player(s) still belong to it."
                )
                skipped_count += 1
        
        if skipped_count:
            messages.warning(
                request,
                f'Deleted {deleted_count} empty temp teams from "{tournament.name}". '
                f'WARNING: {skipped_count} team(s) skipped — they still had players attached. '
                'Check server logs for details.'
            )
        else:
            messages.success(request, f'Deleted {deleted_count} empty temp teams from tournament "{tournament.name}"')
        
    except Tournament.DoesNotExist:
        messages.error(request, 'Tournament not found')
    except Exception as e:
        messages.error(request, f'Error cleaning up teams: {str(e)}')
    
    return redirect('simple_creator_home')

