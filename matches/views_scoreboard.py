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
from django.urls import reverse
import json
import logging

from .models import LiveScoreboard, ScoreUpdate, ScorekeeperRating, MatchPlayer
from friendly_games.models import PlayerCodename, FriendlyGamePlayer
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
logger = logging.getLogger(__name__)


def _is_participant(scoreboard, codename):
    """
    Return True if *codename* belongs to an actual participant of the game
    linked to *scoreboard*.

    Friendly game:   any FriendlyGamePlayer row for that game whose player
                     has the given codename.
    Tournament match: any MatchPlayer row for that match whose player has
                     the given codename.

    Returns False if the codename is unknown, or if the player is not in
    the game roster.  Never raises.
    """
    try:
        pc = PlayerCodename.objects.select_related('player').get(codename=codename)
        player = pc.player
    except PlayerCodename.DoesNotExist:
        return False
    except Exception:
        return False

    try:
        if scoreboard.friendly_game_id:
            return FriendlyGamePlayer.objects.filter(
                game=scoreboard.friendly_game,
                player=player,
            ).exists()
        elif scoreboard.tournament_match_id:
            return MatchPlayer.objects.filter(
                match=scoreboard.tournament_match,
                player=player,
            ).exists()
    except Exception as exc:
        logger.warning(
            "_is_participant check failed for scoreboard %s codename %s: %s",
            scoreboard.id, codename, exc
        )
    return False


def _resolve_scorekeeper_names(score_history_qs):
    """
    Build a codename → player name lookup dict for a queryset of ScoreUpdate rows.
    Uses a single batch query to avoid N+1 lookups.
    Returns a dict: {codename_str: player_name_str or None}
    """
    codenames = set(
        v for v in score_history_qs.values_list('scorekeeper_codename', flat=True)
        if v
    )
    if not codenames:
        return {}
    try:
        mapping = {
            pc.codename: pc.player.name
            for pc in PlayerCodename.objects.filter(
                codename__in=codenames
            ).select_related('player')
        }
    except Exception:
        mapping = {}
    return mapping


def _broadcast_score(scoreboard):
    """Push a score.updated event to all clients watching this scoreboard."""
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return
    group = f"scoreboard_{scoreboard.id}"
    payload = {
        "type": "score_updated",   # maps to score_updated() handler in consumer
        "scoreboard_id": scoreboard.id,
        "team1_score": scoreboard.team1_score,
        "team2_score": scoreboard.team2_score,
        "last_updated_by": scoreboard.last_updated_by or "",
        "is_active": scoreboard.is_active,
    }
    try:
        async_to_sync(channel_layer.group_send)(group, payload)
    except Exception as exc:
        logger.warning("score broadcast failed for scoreboard %s: %s", scoreboard.id, exc)


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
    
    # Get full score history (ordered oldest-first for progression display)
    score_history = list(scoreboard.score_updates.order_by('timestamp'))
    recent_updates = score_history  # keep backward compat alias

    # Resolve codenames → player names in one batch query (privacy: never expose raw codenames)
    scorekeeper_names = _resolve_scorekeeper_names(
        scoreboard.score_updates.all()  # pass the original queryset for the values_list
    )
    for _upd in score_history:
        _upd.scorekeeper_display_name = scorekeeper_names.get(_upd.scorekeeper_codename) or ''

    
    # Get session context for auto-filling codename
    session_context = SessionManager.get_session_context(request)
    
    # Get match and team information for submit score links
    match_id = None
    team1_id = None
    team2_id = None
    team1_name = None
    team2_name = None
    
    # Resolve court complex for timezone-aware timestamp display
    court_complex = None
    if scoreboard.tournament_match:
        match_id = scoreboard.tournament_match.id
        team1_id = scoreboard.tournament_match.team1.id
        team2_id = scoreboard.tournament_match.team2.id
        team1_name = scoreboard.tournament_match.team1.name
        team2_name = scoreboard.tournament_match.team2.name
        if scoreboard.tournament_match.court:
            court_complex = scoreboard.tournament_match.court.courtcomplex_set.first()
    elif scoreboard.friendly_game:
        match_id = scoreboard.friendly_game.id
        # For friendly games, we'll use the game ID as both team references
        # since friendly games don't have separate team entities
        team1_id = scoreboard.friendly_game.id  # Use game ID as placeholder
        team2_id = scoreboard.friendly_game.id  # Use game ID as placeholder
        team1_name = scoreboard.get_team1_name()
        team2_name = scoreboard.get_team2_name()
        court_complex = scoreboard.friendly_game.court_complex
    
    # Resolve which team the current session belongs to (for single submit button)
    my_team_id = None
    if scoreboard.tournament_match:
        codename = request.session.get('player_codename')
        if codename:
            try:
                from matches.models import MatchPlayer
                player_obj = PlayerCodename.objects.get(codename=codename.upper()).player
                mp = MatchPlayer.objects.filter(
                    match=scoreboard.tournament_match, player=player_obj
                ).select_related('team').first()
                if mp:
                    my_team_id = mp.team.id
            except Exception:
                pass
        # Fall back to team PIN session
        if my_team_id is None:
            team_pin = request.session.get('team_pin')
            if team_pin:
                try:
                    from teams.models import Team
                    t = Team.objects.get(pin=team_pin)
                    if t.id in (team1_id, team2_id):
                        my_team_id = t.id
                except Exception:
                    pass

    context = {
        'scoreboard': scoreboard,
        'recent_updates': recent_updates,
        'score_history': score_history,
        'score_range': range(14),  # 0-13 for rolling selectors
        'session_codename': session_context.get('session_codename'),
        'player_logged_in': session_context.get('player_logged_in', False),
        'player_name': session_context.get('player_name'),
        # Match and team context for submit score link
        'match_id': match_id,
        'team1_id': team1_id,
        'team2_id': team2_id,
        'team1_name': team1_name,
        'team2_name': team2_name,
        'my_team_id': my_team_id,   # session-resolved team — used for single submit button
        'has_submit_links': match_id is not None,
        # Court complex for timezone-aware timestamp display in templates
        'court_complex': court_complex,
        # Codename → player name map (privacy: templates must use this, never raw codename)
        'scorekeeper_names': scorekeeper_names,
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

        # ── Participant-only permission check ──────────────────────────────────
        # Only players who are actually in this game/match may update the score.
        # Visitors, unrelated players, and public viewers are rejected here.
        if not _is_participant(scoreboard, scorekeeper_codename):
            logger.warning(
                "Scoreboard %s: update rejected — codename %s is not a participant",
                scoreboard_id, scorekeeper_codename,
            )
            return JsonResponse(
                {
                    'success': False,
                    'error': 'Only participants of this game may update the score.',
                },
                status=403,
            )
        # ──────────────────────────────────────────────────────────────────────

        # Determine update_type for pétanque scoring.
        # In pétanque, a single end can award multiple points (1–6) to ONE team.
        # increment: exactly one team's score increased (by any amount), the other stayed the same.
        # correction: both teams' scores changed, any score decreased, or any other anomaly.
        prev_t1 = scoreboard.team1_score
        prev_t2 = scoreboard.team2_score
        delta1 = team1_score - prev_t1
        delta2 = team2_score - prev_t2
        is_normal_increment = (
            (delta1 > 0 and delta2 == 0) or   # team1 scored, team2 unchanged
            (delta1 == 0 and delta2 > 0)       # team2 scored, team1 unchanged
        )
        update_type = 'increment' if is_normal_increment else 'correction'

        # Update the scoreboard
        scoreboard.update_scores(team1_score, team2_score, scorekeeper_codename)
        
        # Create score update record
        ScoreUpdate.objects.create(
            scoreboard=scoreboard,
            team1_score=team1_score,
            team2_score=team2_score,
            scorekeeper_codename=scorekeeper_codename,
            update_type=update_type
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
        
        # Inform players when a score reaches 13 (game likely complete)
        if team1_score >= 13 or team2_score >= 13:
            response_data['message'] = 'Score reached 13 — ready to submit final result.'

        # Broadcast updated score to all spectators and players watching this scoreboard
        _broadcast_score(scoreboard)

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

        # ── Participant-only permission check ──────────────────────────────────
        # Only players who are actually in this game/match may reset the score.
        if not _is_participant(scoreboard, scorekeeper_codename):
            logger.warning(
                "Scoreboard %s: reset rejected — codename %s is not a participant",
                scoreboard_id, scorekeeper_codename,
            )
            return JsonResponse(
                {
                    'success': False,
                    'error': 'Only participants of this game may reset the score.',
                },
                status=403,
            )
        # ──────────────────────────────────────────────────────────────────────

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
        
        # Broadcast reset to all spectators and players watching this scoreboard
        _broadcast_score(scoreboard)

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


def score_history(request, scoreboard_id):
    """
    Full score progression history for a scoreboard.
    Accessible from both the scoreboard detail page and the match/game detail pages.
    """
    scoreboard = get_object_or_404(LiveScoreboard, id=scoreboard_id)

    # Full history ordered oldest-first for chronological progression
    history = list(scoreboard.score_updates.order_by('timestamp'))

    # Resolve codenames → player names in one batch query (privacy: never expose raw codenames)
    scorekeeper_names = _resolve_scorekeeper_names(
        scoreboard.score_updates.all()  # pass the original queryset for the values_list
    )
    for _upd in history:
        _upd.scorekeeper_display_name = scorekeeper_names.get(_upd.scorekeeper_codename) or ''

    # Determine final score from the last history entry (or current scoreboard state)
    final_score_t1 = None
    final_score_t2 = None
    if history:
        last = history[-1]  # history is now a list, use index instead of .last()
        if last:
            final_score_t1 = last.team1_score
            final_score_t2 = last.team2_score
    elif not scoreboard.is_active:
        final_score_t1 = scoreboard.team1_score
        final_score_t2 = scoreboard.team2_score

    # Smart back URL: prefer the match/game detail page
    back_url = None
    if scoreboard.tournament_match:
        back_url = reverse('match_detail', kwargs={'match_id': scoreboard.tournament_match.id})
    elif scoreboard.friendly_game:
        back_url = reverse('friendly_games:game_detail', kwargs={'game_id': scoreboard.friendly_game.id})
    if not back_url:
        back_url = reverse('scoreboard_detail', kwargs={'scoreboard_id': scoreboard_id})

    # Resolve court complex for timezone-aware timestamp display
    court_complex = None
    if scoreboard.tournament_match and scoreboard.tournament_match.court:
        court_complex = scoreboard.tournament_match.court.courtcomplex_set.first()
    elif scoreboard.friendly_game:
        court_complex = scoreboard.friendly_game.court_complex

    context = {
        'scoreboard': scoreboard,
        'score_history': history,
        'final_score_t1': final_score_t1,
        'final_score_t2': final_score_t2,
        'back_url': back_url,
        # Court complex for timezone-aware timestamp display in templates
        'court_complex': court_complex,
        # Codename → player name map (privacy: templates must use this, never raw codename)
        'scorekeeper_names': scorekeeper_names,
    }
    return render(request, 'matches/score_history.html', context)


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

