"""
Views for the Live Scoreboard system.
These views handle scoreboard updates and display without interfering with existing match logic.
"""

from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.contrib import messages
from django.utils import timezone
from django.db.models import Q
import json
import logging

from .models import LiveScoreboard, ScoreUpdate, ScorekeeperRating
from friendly_games.models import PlayerCodename

logger = logging.getLogger(__name__)


def live_scores_list(request):
    """
    Display all active live scoreboards.
    This is the main /live-scores/ page.
    """
    # Get all active scoreboards
    active_scoreboards = LiveScoreboard.objects.filter(is_active=True).order_by('-updated_at')
    
    # Separate tournament and friendly game scoreboards
    tournament_scoreboards = []
    friendly_scoreboards = []
    
    for scoreboard in active_scoreboards:
        if scoreboard.tournament_match:
            # Only show if tournament match is in active state
            if scoreboard.tournament_match.status in ['active', 'pending_verification']:
                tournament_scoreboards.append(scoreboard)
        elif scoreboard.friendly_game:
            # Only show if friendly game is in active state
            if scoreboard.friendly_game.status in ['ACTIVE', 'READY']:
                friendly_scoreboards.append(scoreboard)
    
    context = {
        'tournament_scoreboards': tournament_scoreboards,
        'friendly_scoreboards': friendly_scoreboards,
        'total_active': len(tournament_scoreboards) + len(friendly_scoreboards),
    }
    
    return render(request, 'matches/live_scores_list.html', context)


def scoreboard_detail(request, scoreboard_id):
    """
    Display and update a specific live scoreboard.
    This page allows authenticated users to update scores.
    """
    from pfc_core.session_utils import SessionManager
    
    scoreboard = get_object_or_404(LiveScoreboard, id=scoreboard_id)
    
    # Get recent score updates for history
    recent_updates = scoreboard.score_updates.all()[:10]
    
    # Get session context for auto-filling codename
    session_context = SessionManager.get_session_context(request)
    
    context = {
        'scoreboard': scoreboard,
        'recent_updates': recent_updates,
        'score_range': range(14),  # 0-13 for rolling selectors
        'session_codename': session_context.get('session_codename'),
        'player_logged_in': session_context.get('player_logged_in', False),
        'player_name': session_context.get('player_name'),
    }
    
    return render(request, 'matches/scoreboard_detail.html', context)


@require_http_methods(["POST"])
def update_scoreboard(request, scoreboard_id):
    """
    Update scoreboard scores via AJAX.
    Requires codename authentication.
    """
    try:
        scoreboard = get_object_or_404(LiveScoreboard, id=scoreboard_id)
        
        # Parse JSON data
        data = json.loads(request.body)
        team1_score = int(data.get('team1_score', 0))
        team2_score = int(data.get('team2_score', 0))
        scorekeeper_codename = data.get('codename', '').strip().upper()
        
        # Validate inputs
        if not scorekeeper_codename:
            return JsonResponse({
                'success': False,
                'error': 'Codename is required'
            })
        
        if not (0 <= team1_score <= 13 and 0 <= team2_score <= 13):
            return JsonResponse({
                'success': False,
                'error': 'Scores must be between 0 and 13'
            })
        
        # Optional: Validate codename exists (for better UX, but not required)
        codename_exists = PlayerCodename.objects.filter(codename=scorekeeper_codename).exists()
        
        # Update the scoreboard
        scoreboard.update_scores(team1_score, team2_score, scorekeeper_codename)
        
        # Create score update record
        ScoreUpdate.objects.create(
            scoreboard=scoreboard,
            team1_score=team1_score,
            team2_score=team2_score,
            scorekeeper_codename=scorekeeper_codename,
            update_type='increment'
        )
        
        # Prepare response
        response_data = {
            'success': True,
            'team1_score': scoreboard.team1_score,
            'team2_score': scoreboard.team2_score,
            'last_updated_by': scoreboard.last_updated_by,
            'is_active': scoreboard.is_active,
            'codename_exists': codename_exists,
        }
        
        # Add game completion message if scores reached 13
        if team1_score >= 13 or team2_score >= 13:
            response_data['message'] = 'Game completed! Live scoring has been deactivated.'
        
        return JsonResponse(response_data)
        
    except ValueError as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })
    except Exception as e:
        logger.error(f"Error updating scoreboard {scoreboard_id}: {e}")
        return JsonResponse({
            'success': False,
            'error': 'An error occurred while updating scores'
        })


@require_http_methods(["POST"])
def reset_scoreboard(request, scoreboard_id):
    """
    Reset scoreboard to 0-0.
    Requires codename authentication.
    """
    try:
        scoreboard = get_object_or_404(LiveScoreboard, id=scoreboard_id)
        
        # Parse JSON data
        data = json.loads(request.body)
        scorekeeper_codename = data.get('codename', '').strip().upper()
        
        if not scorekeeper_codename:
            return JsonResponse({
                'success': False,
                'error': 'Codename is required'
            })
        
        # Reset the scoreboard
        scoreboard.reset_scores(scorekeeper_codename)
        
        # Create score update record
        ScoreUpdate.objects.create(
            scoreboard=scoreboard,
            team1_score=0,
            team2_score=0,
            scorekeeper_codename=scorekeeper_codename,
            update_type='reset'
        )
        
        return JsonResponse({
            'success': True,
            'team1_score': 0,
            'team2_score': 0,
            'last_updated_by': scorekeeper_codename,
            'is_active': True,
            'message': 'Scoreboard reset to 0-0'
        })
        
    except Exception as e:
        logger.error(f"Error resetting scoreboard {scoreboard_id}: {e}")
        return JsonResponse({
            'success': False,
            'error': 'An error occurred while resetting scores'
        })


def scoreboard_embed(request, scoreboard_id):
    """
    Embeddable scoreboard view for displaying on external screens.
    This is a minimal view without controls, just showing current scores.
    """
    scoreboard = get_object_or_404(LiveScoreboard, id=scoreboard_id)
    
    context = {
        'scoreboard': scoreboard,
    }
    
    return render(request, 'matches/scoreboard_embed.html', context)


@require_http_methods(["POST"])
def rate_scorekeeper(request, scoreboard_id):
    """
    Allow players to rate scorekeeper accuracy after match completion.
    This is optional functionality for future scorekeeper reputation system.
    """
    try:
        scoreboard = get_object_or_404(LiveScoreboard, id=scoreboard_id)
        
        # Parse form data
        rater_codename = request.POST.get('rater_codename', '').strip().upper()
        accuracy_rating = int(request.POST.get('accuracy_rating', 0))
        feedback = request.POST.get('feedback', '').strip()
        
        # Validate inputs
        if not rater_codename:
            messages.error(request, 'Codename is required')
            return redirect('scoreboard_detail', scoreboard_id=scoreboard_id)
        
        if not (1 <= accuracy_rating <= 5):
            messages.error(request, 'Rating must be between 1 and 5')
            return redirect('scoreboard_detail', scoreboard_id=scoreboard_id)
        
        # Create or update rating
        rating, created = ScorekeeperRating.objects.get_or_create(
            scoreboard=scoreboard,
            rater_codename=rater_codename,
            defaults={
                'accuracy_rating': accuracy_rating,
                'feedback': feedback,
            }
        )
        
        if not created:
            # Update existing rating
            rating.accuracy_rating = accuracy_rating
            rating.feedback = feedback
            rating.save()
            messages.success(request, 'Your rating has been updated')
        else:
            messages.success(request, 'Thank you for rating the scorekeeper!')
        
        return redirect('scoreboard_detail', scoreboard_id=scoreboard_id)
        
    except Exception as e:
        logger.error(f"Error rating scorekeeper for scoreboard {scoreboard_id}: {e}")
        messages.error(request, 'An error occurred while submitting your rating')
        return redirect('scoreboard_detail', scoreboard_id=scoreboard_id)

