"""
Practice Views for PFC Shooting Practice (v0.1)

Simple training module views using existing PFC authentication system.
Maintains design consistency and non-breaking requirements.
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
    """
    Main practice page - shows available practice types
    """
    # Get session context for authentication
    session_context = SessionManager.get_session_context(request)
    
    # Get player's recent sessions if logged in
    recent_sessions = []
    player_stats = None
    
    if session_context['player_logged_in']:
        codename = session_context['session_codename']
        recent_sessions = PracticeSession.objects.filter(
            player_codename=codename,
            is_active=False
        ).order_by('-started_at')[:5]
        
        # Get or create player statistics
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
    """
    Shooting practice page - main interface for recording shots
    """
    # Check authentication
    if not CodenameSessionManager.is_logged_in(request):
        messages.error(request, "Please log in with your codename to start practice.")
        return redirect('practice:practice_home')
    
    session_context = SessionManager.get_session_context(request)
    codename = session_context['session_codename']
    
    # Check for active session
    active_session = PracticeSession.objects.filter(
        player_codename=codename,
        practice_type='shooting',
        is_active=True
    ).first()
    
    # Get recent completed sessions for reference
    recent_sessions = PracticeSession.objects.filter(
        player_codename=codename,
        practice_type='shooting',
        is_active=False
    ).order_by('-started_at')[:3]
    
    context = {
        **session_context,
        'active_session': active_session,
        'recent_sessions': recent_sessions,
        'page_title': 'Shooting Practice',
    }
    
    return render(request, 'practice/shooting_practice.html', context)


def pointing_practice(request):
    """
    Pointing practice page - main interface for recording pointing attempts
    """
    # Check authentication
    if not CodenameSessionManager.is_logged_in(request):
        messages.error(request, "Please log in with your codename to start practice.")
        return redirect('practice:practice_home')
    
    session_context = SessionManager.get_session_context(request)
    codename = session_context['session_codename']
    
    # Check for active session
    active_session = PracticeSession.objects.filter(
        player_codename=codename,
        practice_type='pointing',
        is_active=True
    ).first()
    
    # Get recent completed sessions for reference
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
    """
    Start a new practice session
    """
    if not CodenameSessionManager.is_logged_in(request):
        return JsonResponse({'error': 'Authentication required'}, status=401)
    
    codename = CodenameSessionManager.get_logged_in_codename(request)
    
    # Get practice type and session attributes from request
    try:
        data = json.loads(request.body)
        practice_type = data.get('practice_type', 'shooting')
        distance = data.get('distance', '7m')
        sequence_tracking = data.get('sequence_tracking', True)
    except:
        practice_type = 'shooting'
        distance = '7m'
        sequence_tracking = True
    
    if practice_type not in ['shooting', 'pointing']:
        return JsonResponse({'error': 'Invalid practice type'}, status=400)
    
    # Validate distance
    valid_distances = ['6m', '7m', '8m', '9m', '10m']
    if distance not in valid_distances:
        return JsonResponse({'error': 'Invalid distance. Must be one of: 6m, 7m, 8m, 9m, 10m'}, status=400)
    
    # Check for existing active session
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
    
    # Create new session with attributes
    try:
        with transaction.atomic():
            session = PracticeSession.objects.create(
                player_codename=codename,
                practice_type=practice_type,
                distance=distance,
                sequence_tracking=sequence_tracking
            )
        
        return JsonResponse({
            'success': True,
            'session_id': str(session.id),
            'message': 'Practice session started!'
        })
    
    except Exception as e:
        return JsonResponse({'error': 'Failed to start session'}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def record_shot(request):
    """
    Record a shot in the active session
    """
    if not CodenameSessionManager.is_logged_in(request):
        return JsonResponse({'error': 'Authentication required'}, status=401)
    
    try:
        data = json.loads(request.body)
        outcome = data.get('outcome')
        
        # Validate outcome (supports both shooting and pointing)
        valid_outcomes = ['miss', 'hit', 'petit_carreau', 'carreau', 'perfect', 'petit_perfect', 'good', 'fair', 'far']
        if outcome not in valid_outcomes:
            return JsonResponse({'error': 'Invalid shot outcome'}, status=400)
        
        codename = CodenameSessionManager.get_logged_in_codename(request)
        
        # Get active session (any practice type)
        session = PracticeSession.objects.filter(
            player_codename=codename,
            is_active=True
        ).first()
        
        if not session:
            return JsonResponse({'error': 'No active session found'}, status=404)
        
        # Create shot record
        with transaction.atomic():
            shot = Shot.objects.create(
                session=session,
                outcome=outcome
            )
            
            # Get updated session statistics
            session.refresh_from_db()
            
            # Get recent shots for display (last 10)
            recent_shots = list(session.shots.order_by('-sequence_number')[:10].values(
                'sequence_number', 'outcome', 'timestamp'
            ))
            
            # Calculate current streak (successful shots)
            current_streak = 0
            success_outcomes = ['hit', 'petit_carreau', 'carreau', 'perfect', 'petit_perfect', 'good']
            for shot_data in session.shots.order_by('-sequence_number'):
                if shot_data.outcome in success_outcomes:
                    current_streak += 1
                else:
                    break
        
        # Build response based on practice type
        response_data = {
            'success': True,
            'shot_number': shot.sequence_number,
            'outcome': outcome,
            'session_stats': {
                'total_shots': session.total_shots,
                'current_streak': current_streak,
            },
            'recent_shots': recent_shots
        }
        
        # Add practice-type specific stats
        if session.practice_type == 'shooting':
            response_data['session_stats'].update({
                'hits': session.hits,
                'petit_carreaux': session.petit_carreaux,
                'carreaux': session.carreaux,
                'misses': session.misses,
                'hit_percentage': round(session.hit_percentage, 1),
                'carreau_percentage': round(session.carreau_percentage, 1),
            })
        elif session.practice_type == 'pointing':
            # Calculate pointing-specific percentages
            total = session.total_shots
            response_data['session_stats'].update({
                'perfects': session.perfects,
                'petit_perfects': session.petit_perfects,
                'goods': session.goods,
                'fairs': session.fairs,
                'fars': session.fars,
                'perfect_percentage': round((session.perfects / total * 100) if total > 0 else 0, 1),
                'good_percentage': round((session.goods / total * 100) if total > 0 else 0, 1),
                'far_percentage': round(((session.fairs + session.fars) / total * 100) if total > 0 else 0, 1),
            })
        
        return JsonResponse(response_data)
    
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON data'}, status=400)
    except Exception as e:
        return JsonResponse({'error': 'Failed to record shot'}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def undo_last_shot(request):
    """
    Undo the last shot in the active session
    """
    if not CodenameSessionManager.is_logged_in(request):
        return JsonResponse({'error': 'Authentication required'}, status=401)
    
    codename = CodenameSessionManager.get_logged_in_codename(request)
    
    # Get active session (any practice type)
    session = PracticeSession.objects.filter(
        player_codename=codename,
        is_active=True
    ).first()
    
    if not session:
        return JsonResponse({'error': 'No active session found'}, status=404)
    
    # Get last shot
    last_shot = session.shots.order_by('-sequence_number').first()
    
    if not last_shot:
        return JsonResponse({'error': 'No shots to undo'}, status=400)
    
    try:
        with transaction.atomic():
            # Delete the last shot
            last_shot.delete()
            
            # Update session statistics
            session.update_statistics()
            
            # Get updated recent shots
            recent_shots = list(session.shots.order_by('-sequence_number')[:10].values(
                'sequence_number', 'outcome', 'timestamp'
            ))
            
            # Calculate current streak
            current_streak = 0
            for shot_data in session.shots.order_by('-sequence_number'):
                if shot_data.outcome in ['hit', 'carreau']:
                    current_streak += 1
                else:
                    break
        
        return JsonResponse({
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
            'recent_shots': recent_shots
        })
    
    except Exception as e:
        return JsonResponse({'error': 'Failed to undo shot'}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def end_session(request):
    """
    End the active practice session
    """
    if not CodenameSessionManager.is_logged_in(request):
        return JsonResponse({'error': 'Authentication required'}, status=401)
    
    codename = CodenameSessionManager.get_logged_in_codename(request)
    
    # Get active session (any practice type)
    session = PracticeSession.objects.filter(
        player_codename=codename,
        is_active=True
    ).first()
    
    if not session:
        return JsonResponse({'error': 'No active session found'}, status=404)
    
    try:
        with transaction.atomic():
            # End the session
            session.end_session()
            
            # Update player statistics
            PracticeStatistics.update_for_player(codename)
            
            # Calculate session summary
            summary = calculate_session_summary(session)
        
        return JsonResponse({
            'success': True,
            'message': 'Session ended successfully',
            'session_id': str(session.id),
            'summary': summary
        })
    
    except Exception as e:
        return JsonResponse({'error': 'Failed to end session'}, status=500)


def session_summary(request, session_id):
    """
    Display session summary page
    """
    session_context = SessionManager.get_session_context(request)
    
    # Get session (check ownership if logged in)
    session = get_object_or_404(PracticeSession, id=session_id)
    
    # Check if user can view this session
    if session_context['player_logged_in']:
        if session.player_codename != session_context['session_codename']:
            messages.error(request, "You can only view your own practice sessions.")
            return redirect('practice:practice_home')
    
    # Calculate detailed summary
    summary = calculate_session_summary(session)
    
    # Get all shots for detailed view
    shots = session.shots.order_by('sequence_number')
    
    context = {
        **session_context,
        'session': session,
        'summary': summary,
        'shots': shots,
        'page_title': f'Session Summary - {session.started_at.strftime("%Y-%m-%d %H:%M")}',
    }
    
    return render(request, 'practice/session_summary.html', context)


# Session summary calculation is now handled by utils.calculate_session_summary


