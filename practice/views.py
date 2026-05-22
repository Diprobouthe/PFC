"""
Practice Views for PFC Shooting Practice (v0.2)

Adds:
- court_complex selection on session start
- Tir de Précision structured shot recording (atelier + shot_distance)
- API endpoint for court complex list
"""

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from django.db import transaction
import json

from pfc_core.session_utils import CodenameSessionManager, SessionManager
from .models import PracticeSession, Shot, PracticeStatistics
from .utils import calculate_session_summary, get_player_progress_summary


def practice_home(request):
    """Main practice page — shows available practice types."""
    session_context = SessionManager.get_session_context(request)

    recent_sessions = []
    player_stats = None

    if session_context['player_logged_in']:
        codename = session_context['session_codename']
        recent_sessions = PracticeSession.objects.filter(
            player_codename=codename,
            is_active=False
        ).order_by('-started_at')[:5]

        try:
            player_stats = PracticeStatistics.objects.get(player_codename=codename)
        except PracticeStatistics.DoesNotExist:
            player_stats = None

    context = {
        **session_context,
        'recent_sessions': recent_sessions,
        'player_stats': player_stats,
        'page_title': 'Practice',
    }

    return render(request, 'practice/practice_home.html', context)


def shooting_practice(request):
    """Shooting practice page — main interface for recording shots."""
    if not CodenameSessionManager.is_logged_in(request):
        messages.error(request, "Please log in with your codename to start practice.")
        return redirect('practice:practice_home')

    session_context = SessionManager.get_session_context(request)
    codename = session_context['session_codename']

    active_session = PracticeSession.objects.filter(
        player_codename=codename,
        practice_type='shooting',
        is_active=True
    ).select_related('court_complex').first()

    recent_sessions = PracticeSession.objects.filter(
        player_codename=codename,
        practice_type='shooting',
        is_active=False
    ).select_related('court_complex').order_by('-started_at')[:3]

    # Court complexes for the selector — default Pedion tou Areos first
    from courts.models import CourtComplex
    court_complexes = list(CourtComplex.objects.all().order_by('name'))
    # Move "Pedion" to the front if it exists
    pedion = None
    others = []
    for cc in court_complexes:
        if 'areos' in cc.name.lower() or 'πεδίο' in cc.name.lower() or 'pedion' in cc.name.lower():
            pedion = cc
        else:
            others.append(cc)
    if pedion:
        court_complexes = [pedion] + others

    # Build TdP atelier info for the template
    tdp_ateliers = Shot.TDP_ATELIERS
    tdp_distances = Shot.TDP_DISTANCES

    # Pre-populate all TdP shots for the JS state machine (prevents desync on reload)
    import json as _json
    initial_shots_json = '[]'
    if active_session and active_session.drill_type == 'tir_de_precision':
        shots_list = list(active_session.shots.order_by('sequence_number').values(
            'sequence_number', 'outcome', 'atelier', 'shot_distance'
        ))
        # Compute tdp_points from outcome (property not stored as column)
        pts_map = {
            'tdp_carreau': 5, 'tdp_reussi': 3, 'tdp_touche': 1, 'tdp_manque': 0,
            'tdp_jack_reussi': 5, 'tdp_jack_touche': 3, 'tdp_jack_manque': 0,
        }
        for s in shots_list:
            s['tdp_points'] = pts_map.get(s.get('outcome', ''), 0)
        initial_shots_json = _json.dumps(shots_list)

    context = {
        **session_context,
        'active_session': active_session,
        'recent_sessions': recent_sessions,
        'court_complexes': court_complexes,
        'tdp_ateliers': tdp_ateliers,
        'tdp_distances': tdp_distances,
        'initial_shots_json': initial_shots_json,
        'page_title': 'Shooting Practice',
    }

    return render(request, 'practice/shooting_practice.html', context)


def pointing_practice(request):
    """Pointing practice page."""
    if not CodenameSessionManager.is_logged_in(request):
        messages.error(request, "Please log in with your codename to start practice.")
        return redirect('practice:practice_home')

    session_context = SessionManager.get_session_context(request)
    codename = session_context['session_codename']

    active_session = PracticeSession.objects.filter(
        player_codename=codename,
        practice_type='pointing',
        is_active=True
    ).first()

    recent_sessions = PracticeSession.objects.filter(
        player_codename=codename,
        practice_type='pointing',
        is_active=False
    ).order_by('-started_at')[:3]

    context = {
        **session_context,
        'active_session': active_session,
        'recent_sessions': recent_sessions,
        'page_title': 'Pointing Practice',
    }

    return render(request, 'practice/pointing_practice.html', context)


@csrf_exempt
@require_http_methods(["POST"])
def start_session(request):
    """Start a new practice session."""
    if not CodenameSessionManager.is_logged_in(request):
        return JsonResponse({'error': 'Authentication required'}, status=401)

    codename = CodenameSessionManager.get_logged_in_codename(request)

    try:
        data = json.loads(request.body)
        practice_type = data.get('practice_type', 'shooting')
        distance = data.get('distance', '7m')
        sequence_tracking = data.get('sequence_tracking', True)
        drill_type = data.get('drill_type', '')
        court_complex_id = data.get('court_complex_id', None)
    except Exception:
        practice_type = 'shooting'
        distance = '7m'
        sequence_tracking = True
        drill_type = ''
        court_complex_id = None

    if practice_type not in ['shooting', 'pointing']:
        return JsonResponse({'error': 'Invalid practice type'}, status=400)

    valid_distances = ['6m', '7m', '8m', '9m', '10m', 'ing']
    if distance not in valid_distances:
        return JsonResponse({'error': 'Invalid distance'}, status=400)

    valid_drill_types = [
        '', 'open', 'boule_in_line', 'hidden_target', 'boule_behind_boule',
        'sequence', 'tir_de_precision', 'obstacle', 'tactical',
        # legacy value kept for backward compat
        'precision',
    ]
    if drill_type not in valid_drill_types:
        drill_type = ''

    # Normalise legacy 'precision' → 'tir_de_precision'
    if drill_type == 'precision':
        drill_type = 'tir_de_precision'

    # Tir de Précision always uses sequence tracking and ignores the global distance
    if drill_type == 'tir_de_precision':
        sequence_tracking = True

    # Resolve court complex
    court_complex_obj = None
    if court_complex_id:
        try:
            from courts.models import CourtComplex
            court_complex_obj = CourtComplex.objects.get(id=court_complex_id)
        except Exception:
            court_complex_obj = None

    existing_session = PracticeSession.objects.filter(
        player_codename=codename,
        practice_type=practice_type,
        is_active=True
    ).first()

    if existing_session:
        return JsonResponse({
            'error': 'You already have an active session',
            'session_id': str(existing_session.id)
        }, status=400)

    try:
        with transaction.atomic():
            session = PracticeSession.objects.create(
                player_codename=codename,
                practice_type=practice_type,
                distance=distance,
                sequence_tracking=sequence_tracking,
                drill_type=drill_type if practice_type == 'shooting' else '',
                court_complex=court_complex_obj,
            )

        response = {
            'success': True,
            'session_id': str(session.id),
            'message': 'Practice session started!',
            'drill_type': session.drill_type,
        }
        if court_complex_obj:
            response['court_complex_name'] = court_complex_obj.name

        return JsonResponse(response)

    except Exception as e:
        return JsonResponse({'error': 'Failed to start session'}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def record_shot(request):
    """Record a shot in the active session."""
    if not CodenameSessionManager.is_logged_in(request):
        return JsonResponse({'error': 'Authentication required'}, status=401)

    try:
        data = json.loads(request.body)
        outcome = data.get('outcome')
        atelier = data.get('atelier', None)       # int 1-5, only for TdP
        shot_distance = data.get('shot_distance', '')  # e.g. '6m', only for TdP

        # All valid outcomes (regular + TdP)
        valid_outcomes = [
            'miss', 'hit', 'petit_carreau', 'carreau',
            'tdp_manque', 'tdp_touche', 'tdp_reussi', 'tdp_carreau',
            'tdp_jack_manque', 'tdp_jack_touche', 'tdp_jack_reussi',
            'perfect', 'petit_perfect', 'good', 'fair', 'far',
        ]
        if outcome not in valid_outcomes:
            return JsonResponse({'error': 'Invalid shot outcome'}, status=400)

        codename = CodenameSessionManager.get_logged_in_codename(request)

        session = PracticeSession.objects.filter(
            player_codename=codename,
            is_active=True
        ).first()

        if not session:
            return JsonResponse({'error': 'No active session found'}, status=404)

        # Validate TdP-specific fields
        if session.drill_type == 'tir_de_precision':
            if atelier is None or int(atelier) not in range(1, 6):
                return JsonResponse({'error': 'atelier (1-5) required for Tir de Précision'}, status=400)
            if shot_distance not in Shot.TDP_DISTANCES:
                return JsonResponse({'error': 'shot_distance (6m/7m/8m/9m) required for Tir de Précision'}, status=400)

        with transaction.atomic():
            shot_kwargs = {
                'session': session,
                'outcome': outcome,
            }
            if session.drill_type == 'tir_de_precision':
                shot_kwargs['atelier'] = int(atelier)
                shot_kwargs['shot_distance'] = shot_distance

            shot = Shot.objects.create(**shot_kwargs)

            session.refresh_from_db()

            recent_shots = list(session.shots.order_by('-sequence_number')[:10].values(
                'sequence_number', 'outcome', 'timestamp', 'atelier', 'shot_distance'
            ))

            current_streak = 0
            success_outcomes = ['hit', 'petit_carreau', 'carreau', 'perfect', 'petit_perfect', 'good', 'fair']
            for shot_data in session.shots.order_by('-sequence_number'):
                if shot_data.outcome in success_outcomes:
                    current_streak += 1
                else:
                    break

        response_data = {
            'success': True,
            'shot_number': shot.sequence_number,
            'outcome': outcome,
            'session_stats': {
                'total_shots': session.total_shots,
                'current_streak': current_streak,
            },
            'recent_shots': recent_shots,
        }

        if session.practice_type == 'shooting':
            if session.drill_type == 'tir_de_precision':
                response_data['session_stats'].update({
                    'tdp_score': session.tdp_score,
                    'tdp_points_this_shot': shot.tdp_points,
                    'misses': session.misses,
                })
            else:
                response_data['session_stats'].update({
                    'hits': session.hits,
                    'petit_carreaux': session.petit_carreaux,
                    'carreaux': session.carreaux,
                    'misses': session.misses,
                    'hit_percentage': round(session.hit_percentage, 1),
                    'carreau_percentage': round(session.carreau_percentage, 1),
                })
        elif session.practice_type == 'pointing':
            total = session.total_shots
            response_data['session_stats'].update({
                'perfects': session.perfects,
                'petit_perfects': session.petit_perfects,
                'goods': session.goods,
                'fairs': session.fairs,
                'fars': session.fars,
                'perfect_percentage': round((session.perfects / total * 100) if total > 0 else 0, 1),
                'good_percentage': round((session.goods / total * 100) if total > 0 else 0, 1),
                'success_percentage': round(
                    ((session.perfects + session.petit_perfects + session.goods + session.fairs) / total * 100)
                    if total > 0 else 0, 1
                ),
            })

        return JsonResponse(response_data)

    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON data'}, status=400)
    except Exception as e:
        return JsonResponse({'error': 'Failed to record shot'}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def undo_last_shot(request):
    """Undo the last shot in the active session."""
    if not CodenameSessionManager.is_logged_in(request):
        return JsonResponse({'error': 'Authentication required'}, status=401)

    codename = CodenameSessionManager.get_logged_in_codename(request)

    session = PracticeSession.objects.filter(
        player_codename=codename,
        is_active=True
    ).first()

    if not session:
        return JsonResponse({'error': 'No active session found'}, status=404)

    last_shot = session.shots.order_by('-sequence_number').first()

    if not last_shot:
        return JsonResponse({'error': 'No shots to undo'}, status=400)

    try:
        with transaction.atomic():
            last_shot.delete()
            session.update_statistics()

            recent_shots = list(session.shots.order_by('-sequence_number')[:10].values(
                'sequence_number', 'outcome', 'timestamp', 'atelier', 'shot_distance'
            ))

            current_streak = 0
            for shot_data in session.shots.order_by('-sequence_number'):
                if shot_data.outcome in ['hit', 'carreau']:
                    current_streak += 1
                else:
                    break

        response = {
            'success': True,
            'message': 'Last shot undone',
            'session_stats': {
                'total_shots': session.total_shots,
                'hits': session.hits,
                'carreaux': session.carreaux,
                'misses': session.misses,
                'hit_percentage': round(session.hit_percentage, 1),
                'carreau_percentage': round(session.carreau_percentage, 1),
                'current_streak': current_streak,
            },
            'recent_shots': recent_shots,
        }
        if session.drill_type == 'tir_de_precision':
            response['session_stats']['tdp_score'] = session.tdp_score

        return JsonResponse(response)

    except Exception as e:
        return JsonResponse({'error': 'Failed to undo shot'}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def end_session(request):
    """End the active practice session."""
    if not CodenameSessionManager.is_logged_in(request):
        return JsonResponse({'error': 'Authentication required'}, status=401)

    codename = CodenameSessionManager.get_logged_in_codename(request)

    session = PracticeSession.objects.filter(
        player_codename=codename,
        is_active=True
    ).first()

    if not session:
        return JsonResponse({'error': 'No active session found'}, status=404)

    try:
        with transaction.atomic():
            session.end_session()
            PracticeStatistics.update_for_player(codename)
            summary = calculate_session_summary(session)

        return JsonResponse({
            'success': True,
            'message': 'Session ended successfully',
            'session_id': str(session.id),
            'summary': summary,
        })

    except Exception as e:
        return JsonResponse({'error': 'Failed to end session'}, status=500)


def session_summary(request, session_id):
    """Display session summary page."""
    session_context = SessionManager.get_session_context(request)

    session = get_object_or_404(PracticeSession, id=session_id)

    if session_context['player_logged_in']:
        if session.player_codename != session_context['session_codename']:
            messages.error(request, "You can only view your own practice sessions.")
            return redirect('practice:practice_home')

    summary = calculate_session_summary(session)
    shots = session.shots.order_by('sequence_number')

    # For TdP sessions, build a structured atelier breakdown
    tdp_breakdown = None
    if session.drill_type == 'tir_de_precision':
        tdp_breakdown = []
        for atelier_info in Shot.TDP_ATELIERS:
            a_num = atelier_info['number']
            a_shots = [s for s in shots if s.atelier == a_num]
            a_score = sum(s.tdp_points for s in a_shots)
            tdp_breakdown.append({
                'atelier': atelier_info,
                'shots': a_shots,
                'score': a_score,
                'max_score': 20,  # 4 shots × 5 pts max
            })

    context = {
        **session_context,
        'session': session,
        'summary': summary,
        'shots': shots,
        'tdp_breakdown': tdp_breakdown,
        'page_title': f'Session Summary — {session.started_at.strftime("%Y-%m-%d %H:%M")}',
    }

    return render(request, 'practice/session_summary.html', context)


def session_history(request):
    """Display all practice sessions for the logged-in player."""
    session_context = SessionManager.get_session_context(request)

    if not session_context['player_logged_in']:
        messages.error(request, "Please log in with your player codename to view session history.")
        return redirect('practice:practice_home')

    player_codename = session_context['session_codename']

    sessions = PracticeSession.objects.filter(
        player_codename=player_codename
    ).select_related('court_complex').order_by('-started_at')

    sessions_with_summary = []
    for session in sessions:
        summary = calculate_session_summary(session)
        sessions_with_summary.append({
            'session': session,
            'summary': summary,
        })

    context = {
        **session_context,
        'sessions': sessions_with_summary,
        'total_sessions': sessions.count(),
        'page_title': 'Practice Session History',
    }

    return render(request, 'practice/session_history.html', context)


@require_http_methods(["GET"])
def court_complexes_api(request):
    """Return list of court complexes for the session start form."""
    from courts.models import CourtComplex
    complexes = CourtComplex.objects.all().order_by('name')
    data = []
    for cc in complexes:
        data.append({
            'id': cc.id,
            'name': cc.name,
            'is_default': (
                'areos' in cc.name.lower() or
                'πεδίο' in cc.name.lower() or
                'pedion' in cc.name.lower()
            ),
        })
    return JsonResponse({'court_complexes': data})
