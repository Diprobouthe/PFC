"""
Match Tracking views.

Provides a new, isolated Match Tracking page for every tournament match and
friendly game.  It reuses the existing:
  - LiveScoreboard / ScoreUpdate system  (score updates)
  - QR verification mechanism             (player authorisation)
  - PracticeSession / Shot system         (shot statistics)
  - MatchPlayer / FriendlyGamePlayer      (participant lists)

It does NOT replace or modify any existing match, live-score, QR, result-
confirmation, practice or shooting-statistics functionality.
"""

import json
import logging

from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _get_scoreboard_or_none(match_type, pk):
    """Return the LiveScoreboard for a tournament match or friendly game, or None."""
    from matches.models import LiveScoreboard
    try:
        if match_type == 'match':
            return LiveScoreboard.objects.select_related(
                'tournament_match',
                'tournament_match__team1',
                'tournament_match__team2',
            ).get(tournament_match_id=pk)
        else:
            return LiveScoreboard.objects.select_related(
                'friendly_game',
            ).get(friendly_game_id=pk)
    except LiveScoreboard.DoesNotExist:
        return None


def _build_player_list(match_type, pk):
    """
    Return a list of dicts describing every participant.

    Each dict:
      { player_id, player_name, team ('BLACK'/'WHITE'), position, has_codename }
    """
    players = []
    if match_type == 'match':
        from matches.models import MatchPlayer, Match
        try:
            m = Match.objects.get(pk=pk)
        except Match.DoesNotExist:
            return players
        for mp in MatchPlayer.objects.filter(match_id=pk).select_related('player'):
            side = 'BLACK' if mp.team_id == m.team1_id else 'WHITE'
            has_codename = False
            try:
                from friendly_games.models import PlayerCodename
                has_codename = PlayerCodename.objects.filter(player=mp.player).exists()
            except Exception:
                pass
            players.append({
                'player_id': mp.player_id,
                'player_name': mp.player.name,
                'team': side,
                'position': mp.role or '',
                'has_codename': has_codename,
            })
    else:
        from friendly_games.models import FriendlyGamePlayer
        for fgp in FriendlyGamePlayer.objects.filter(game_id=pk).select_related('player'):
            has_codename = False
            try:
                from friendly_games.models import PlayerCodename
                has_codename = PlayerCodename.objects.filter(player=fgp.player).exists()
            except Exception:
                pass
            players.append({
                'player_id': fgp.player_id,
                'player_name': fgp.player.name,
                'team': fgp.team,
                'position': fgp.position or '',
                'has_codename': has_codename,
            })
    return players


def _get_player_shot_stats(player_id, match_type, pk):
    """
    Return shot stats for a player (most recent shooting session).
    """
    try:
        from friendly_games.models import PlayerCodename
        pc = PlayerCodename.objects.get(player_id=player_id)
        codename = pc.codename
    except Exception:
        return _empty_stats()

    try:
        from practice.models import PracticeSession
        session = (
            PracticeSession.objects
            .filter(player_codename=codename, practice_type='shooting')
            .order_by('-started_at')
            .first()
        )
        if session:
            total = session.total_shots
            return {
                'total': total,
                'carreaux': session.carreaux,
                'petit_carreaux': session.petit_carreaux,
                'hits': session.hits,
                'misses': session.misses,
                'accuracy': round(session.hit_percentage, 1) if total > 0 else 0.0,
                'session_id': str(session.id),
                'is_active': session.is_active,
            }
    except Exception:
        pass
    return _empty_stats()


def _empty_stats():
    return {
        'total': 0,
        'carreaux': 0,
        'petit_carreaux': 0,
        'hits': 0,
        'misses': 0,
        'accuracy': 0.0,
        'session_id': None,
        'is_active': False,
    }


def _get_score_history(scoreboard):
    """Return all ScoreUpdate rows for this scoreboard, oldest first."""
    from matches.models import ScoreUpdate
    updates = (
        ScoreUpdate.objects
        .filter(scoreboard=scoreboard)
        .order_by('timestamp')
        .values('team1_score', 'team2_score', 'timestamp', 'scorekeeper_codename', 'update_type')
    )
    result = []
    for u in updates:
        result.append({
            'team1_score': u['team1_score'],
            'team2_score': u['team2_score'],
            'ts': u['timestamp'].strftime('%H:%M:%S'),
            'by': u['scorekeeper_codename'] or '',
            'type': u['update_type'],
        })
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Main page view
# ─────────────────────────────────────────────────────────────────────────────

def tracking_page(request, match_type, pk):
    """
    The Match Tracking page.

    match_type: 'match'  → tournament match (pk = Match.id)
                'game'   → friendly game    (pk = FriendlyGame.id)
    """
    if match_type not in ('match', 'game'):
        from django.http import Http404
        raise Http404

    # ── Resolve game object ──────────────────────────────────────────────────
    if match_type == 'match':
        from matches.models import Match
        game_obj = get_object_or_404(Match, pk=pk)
        team1_name = game_obj.team1.name
        team2_name = game_obj.team2.name
        game_status = game_obj.status
        game_label = str(game_obj)
        timer_start_epoch = int(game_obj.start_time.timestamp()) if game_obj.start_time else None
        timer_total_seconds = game_obj.time_limit_minutes * 60 if game_obj.time_limit_minutes else None
    else:
        from friendly_games.models import FriendlyGame
        game_obj = get_object_or_404(FriendlyGame, pk=pk)
        team1_name = 'Black'
        team2_name = 'White'
        game_status = game_obj.status
        game_label = str(game_obj)
        timer_start_epoch = int(game_obj.timer_started_at.timestamp()) if getattr(game_obj, 'timer_started_at', None) else None
        timer_total_seconds = game_obj.time_limit_minutes * 60 if getattr(game_obj, 'time_limit_minutes', None) else None

    # ── Scoreboard ───────────────────────────────────────────────────────────
    scoreboard = _get_scoreboard_or_none(match_type, pk)
    team1_score = scoreboard.team1_score if scoreboard else 0
    team2_score = scoreboard.team2_score if scoreboard else 0
    scoreboard_id = scoreboard.id if scoreboard else None

    # ── Participants ─────────────────────────────────────────────────────────
    players = _build_player_list(match_type, pk)

    # ── Detect logged-in player ──────────────────────────────────────────────
    from pfc_core.session_utils import CodenameSessionManager
    logged_in_codename = CodenameSessionManager.get_logged_in_codename(request)
    auto_auth_player_id = None
    if logged_in_codename:
        try:
            from friendly_games.models import PlayerCodename
            pc = PlayerCodename.objects.select_related('player').get(codename=logged_in_codename)
            if any(p['player_id'] == pc.player_id for p in players):
                auto_auth_player_id = pc.player_id
        except Exception:
            pass

    # ── Score history ────────────────────────────────────────────────────────
    score_history = _get_score_history(scoreboard) if scoreboard else []

    # ── QR resolve URL (reuse existing endpoints) ────────────────────────────
    if match_type == 'match':
        qr_resolve_url = '/matches/api/qr-resolve/'
    else:
        qr_resolve_url = '/friendly-games/api/qr-resolve/'

    score_update_url = f'/matches/scoreboard/{scoreboard_id}/update/' if scoreboard_id else None

    context = {
        'match_type': match_type,
        'pk': pk,
        'game_obj': game_obj,
        'game_label': game_label,
        'game_status': game_status,
        'team1_name': team1_name,
        'team2_name': team2_name,
        'team1_score': team1_score,
        'team2_score': team2_score,
        'scoreboard_id': scoreboard_id,
        'score_update_url': score_update_url,
        'players': players,
        'auto_auth_player_id': auto_auth_player_id,
        'logged_in_codename': logged_in_codename,
        'score_history_json': json.dumps(score_history),
        'qr_resolve_url': qr_resolve_url,
        'timer_start_epoch': timer_start_epoch,
        'timer_total_seconds': timer_total_seconds,
        'shot_start_url': '/practice/api/start-session/',
        'shot_record_url': '/practice/api/record-shot/',
        'shot_end_url': '/practice/api/end-session/',
    }
    return render(request, 'match_tracking/tracking_page.html', context)


# ─────────────────────────────────────────────────────────────────────────────
# AJAX: player stats
# ─────────────────────────────────────────────────────────────────────────────

@require_http_methods(["GET"])
def player_stats_api(request, match_type, pk, player_id):
    """Return current shot stats for a player in this game (JSON)."""
    if match_type not in ('match', 'game'):
        return JsonResponse({'error': 'Invalid match type'}, status=400)
    stats = _get_player_shot_stats(player_id, match_type, pk)
    return JsonResponse({'ok': True, 'stats': stats})


# ─────────────────────────────────────────────────────────────────────────────
# AJAX: verify participant
# ─────────────────────────────────────────────────────────────────────────────

@csrf_exempt
@require_http_methods(["POST"])
def verify_participant(request, match_type, pk):
    """
    POST { player_id: <int> }
    Verifies the QR-resolved player is a participant in this specific game.

    The QR resolve endpoints never send the codename to the browser (by design).
    Instead they store it in request.session['qr_resolved_codename'].  This
    endpoint reads that session value and returns it to the Match Tracking page
    so that subsequent shot-recording calls can include it.  The codename is
    consumed (popped) from the session after being read so it cannot be reused.
    """
    if match_type not in ('match', 'game'):
        return JsonResponse({'error': 'Invalid match type'}, status=400)

    try:
        data = json.loads(request.body)
        player_id = int(data.get('player_id', 0))
    except (ValueError, TypeError, json.JSONDecodeError):
        return JsonResponse({'ok': False, 'error': 'Invalid request'}, status=400)

    players = _build_player_list(match_type, pk)
    participant = next((p for p in players if p['player_id'] == player_id), None)
    if not participant:
        return JsonResponse({'ok': False, 'error': 'Player is not a participant in this game'}, status=403)

    # Read the codename that was stored server-side by the QR resolve endpoint.
    # Pop it so it cannot be replayed for a different player.
    qr_codename = request.session.pop('qr_resolved_codename', None)
    if qr_codename:
        request.session.modified = True
        # Verify the resolved codename actually belongs to this player_id
        try:
            from friendly_games.models import PlayerCodename
            pc = PlayerCodename.objects.get(codename=qr_codename)
            if pc.player_id != player_id:
                # Mismatch — someone sent a player_id that doesn't match the QR scan
                return JsonResponse({'ok': False, 'error': 'QR identity mismatch'}, status=403)
            codename = qr_codename
        except PlayerCodename.DoesNotExist:
            codename = None
    else:
        codename = None

    stats = _get_player_shot_stats(player_id, match_type, pk)
    return JsonResponse({
        'ok': True,
        'player_id': player_id,
        'player_name': participant['player_name'],
        'team': participant['team'],
        'position': participant['position'],
        'codename': codename,   # returned only to this browser session; used for shot recording
        'stats': stats,
    })


# ─────────────────────────────────────────────────────────────────────────────
# AJAX: record shot for an authorized player
# ─────────────────────────────────────────────────────────────────────────────

@csrf_exempt
@require_http_methods(["POST"])
def record_shot(request, match_type, pk):
    """
    POST { outcome: str, codename: str, player_id: int }

    Records a shot for a QR-authorized player using the existing
    PracticeSession / Shot system.  Creates or resumes an active shooting
    session for the player's codename.

    Valid outcomes: carreau, petit_carreau, hit, miss
    """
    if match_type not in ('match', 'game'):
        return JsonResponse({'error': 'Invalid match type'}, status=400)

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'ok': False, 'error': 'Invalid JSON'}, status=400)

    outcome  = data.get('outcome', '').strip().lower()
    codename = data.get('codename', '').strip().upper()
    player_id = data.get('player_id')

    valid_outcomes = ['carreau', 'petit_carreau', 'hit', 'miss']
    if outcome not in valid_outcomes:
        return JsonResponse({'ok': False, 'error': 'Invalid outcome'}, status=400)

    if not codename:
        return JsonResponse({'ok': False, 'error': 'Codename required'}, status=400)

    # Enforce match-status lifecycle: only allow shot recording while the game is active
    try:
        if match_type == 'match':
            from matches.models import Match
            game_obj = Match.objects.only('status').get(pk=pk)
            is_active = game_obj.status in ('active', 'ACTIVE')
        else:
            from friendly_games.models import FriendlyGame
            game_obj = FriendlyGame.objects.only('status').get(pk=pk)
            is_active = game_obj.status in ('active', 'ACTIVE', 'pending_verification')
        if not is_active:
            return JsonResponse({'ok': False, 'error': 'Match is no longer active'}, status=403)
    except Exception:
        pass  # If we can't determine status, allow the shot (fail-open for safety)

    # Verify codename belongs to a participant in this game
    players = _build_player_list(match_type, pk)
    try:
        from friendly_games.models import PlayerCodename
        pc = PlayerCodename.objects.select_related('player').get(codename=codename)
    except PlayerCodename.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'Unknown codename'}, status=403)

    if not any(p['player_id'] == pc.player_id for p in players):
        return JsonResponse({'ok': False, 'error': 'Not a participant in this game'}, status=403)

    # Get or create an active shooting session for this codename
    try:
        from practice.models import PracticeSession, Shot
        from django.db import transaction

        session = (
            PracticeSession.objects
            .filter(player_codename=codename, practice_type='shooting', is_active=True)
            .first()
        )
        if not session:
            session = PracticeSession.objects.create(
                player_codename=codename,
                practice_type='shooting',
                distance='ing',
                drill_type='',
            )

        with transaction.atomic():
            Shot.objects.create(session=session, outcome=outcome)
            session.refresh_from_db()

        total = session.total_shots
        stats = {
            'total': total,
            'carreaux': session.carreaux,
            'petit_carreaux': session.petit_carreaux,
            'hits': session.hits,
            'misses': session.misses,
            'accuracy': round(session.hit_percentage, 1) if total > 0 else 0.0,
            'session_id': str(session.id),
            'is_active': session.is_active,
        }
        return JsonResponse({'ok': True, 'stats': stats})

    except Exception as exc:
        logger.error("match_tracking record_shot error: %s", exc)
        return JsonResponse({'ok': False, 'error': 'Shot recording failed'}, status=500)


# ─────────────────────────────────────────────────────────────────────────────
# AJAX: game status poll (used by the page to auto-disable controls)
# ─────────────────────────────────────────────────────────────────────────────

@require_http_methods(["GET"])
def game_status_api(request, match_type, pk):
    """
    GET /track/<match_type>/<pk>/status/
    Returns the current match/game status so the page can disable controls
    when the game is no longer active.
    """
    if match_type not in ('match', 'game'):
        return JsonResponse({'error': 'Invalid match type'}, status=400)
    try:
        if match_type == 'match':
            from matches.models import Match
            obj = Match.objects.only('status').get(pk=pk)
        else:
            from friendly_games.models import FriendlyGame
            obj = FriendlyGame.objects.only('status').get(pk=pk)
        return JsonResponse({'ok': True, 'status': obj.status})
    except Exception:
        return JsonResponse({'ok': False, 'error': 'Not found'}, status=404)
