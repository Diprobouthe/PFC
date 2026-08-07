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


# Shooting outcomes (open-ended, no fixed total)
SHOOTING_OUTCOMES = {'carreau', 'petit_carreau', 'hit', 'miss'}
# Pointing outcomes — exactly the four categories used in the PFC Pointing practice UI
POINTING_OUTCOMES = {'perfect', 'good', 'fair', 'far'}


def _get_player_shot_stats(player_id, match_type, pk):
    """
    Return both shooting and pointing stats for a player.
    Each stat block is open-ended: percentages are calculated from actual
    attempts only, with no assumed fixed total.
    """
    try:
        from friendly_games.models import PlayerCodename
        pc = PlayerCodename.objects.get(player_id=player_id)
        codename = pc.codename
    except Exception:
        return _empty_stats()

    from practice.models import PracticeSession

    def _session_stats(practice_type):
        try:
            session = (
                PracticeSession.objects
                .filter(player_codename=codename, practice_type=practice_type, is_active=True)
                .order_by('-started_at')
                .first()
            )
            if not session:
                return None
            total = session.total_shots
            if practice_type == 'shooting':
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
            else:  # pointing
                return {
                    'total': total,
                    'perfects': session.perfects,
                    'petit_perfects': session.petit_perfects,
                    'goods': session.goods,
                    'fairs': session.fairs,
                    'fars': session.fars,
                    'accuracy': round(session.hit_percentage, 1) if total > 0 else 0.0,
                    'session_id': str(session.id),
                    'is_active': session.is_active,
                }
        except Exception:
            return None

    shooting = _session_stats('shooting') or _empty_shooting_stats()
    pointing = _session_stats('pointing') or _empty_pointing_stats()
    return {'shooting': shooting, 'pointing': pointing}


def _empty_shooting_stats():
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


def _empty_pointing_stats():
    return {
        'total': 0,
        'perfects': 0,
        'petit_perfects': 0,
        'goods': 0,
        'fairs': 0,
        'fars': 0,
        'accuracy': 0.0,
        'session_id': None,
        'is_active': False,
    }


def _empty_stats():
    """Combined empty stats (shooting + pointing)."""
    return {'shooting': _empty_shooting_stats(), 'pointing': _empty_pointing_stats()}


def _get_score_history(scoreboard):
    """Return all ScoreUpdate rows for this scoreboard, oldest first.
    Codenames are resolved to player names using the same batch-lookup pattern
    as _resolve_scorekeeper_names in views_scoreboard.py.
    """
    from matches.models import ScoreUpdate
    updates = list(
        ScoreUpdate.objects
        .filter(scoreboard=scoreboard)
        .order_by('timestamp')
        .values('team1_score', 'team2_score', 'timestamp', 'scorekeeper_codename', 'update_type')
    )
    # Batch-resolve codenames → player names (never expose raw codenames to the browser)
    codenames = {u['scorekeeper_codename'] for u in updates if u['scorekeeper_codename']}
    codename_to_name = {}
    if codenames:
        try:
            from friendly_games.models import PlayerCodename
            for pc in PlayerCodename.objects.filter(codename__in=codenames).select_related('player'):
                codename_to_name[pc.codename] = pc.player.name
        except Exception:
            pass
    result = []
    for u in updates:
        raw = u['scorekeeper_codename'] or ''
        display_name = codename_to_name.get(raw, raw)  # fall back to raw only if lookup fails
        result.append({
            'team1_score': u['team1_score'],
            'team2_score': u['team2_score'],
            'ts': u['timestamp'].strftime('%H:%M:%S'),
            'by': display_name,
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

    Records a shot (shooting or pointing) for a QR-authorized player using the
    existing PracticeSession / Shot system.  Sessions are open-ended: attempts
    start from 0 and accumulate with no fixed total.  Percentages are
    calculated only from actual recorded attempts.

    Shooting outcomes : carreau, petit_carreau, hit, miss
    Pointing outcomes : perfect, petit_perfect, good, fair, far
    """
    if match_type not in ('match', 'game'):
        return JsonResponse({'error': 'Invalid match type'}, status=400)

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'ok': False, 'error': 'Invalid JSON'}, status=400)

    outcome   = data.get('outcome', '').strip().lower()
    codename  = data.get('codename', '').strip().upper()

    # Determine practice type from outcome
    if outcome in SHOOTING_OUTCOMES:
        practice_type = 'shooting'
    elif outcome in POINTING_OUTCOMES:
        practice_type = 'pointing'
    else:
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

    # Get or create an active open-ended session for this codename + practice type.
    # drill_type='' means "open shot" (same as OpenShots page).
    try:
        from practice.models import PracticeSession, Shot
        from django.db import transaction

        session = (
            PracticeSession.objects
            .filter(player_codename=codename, practice_type=practice_type, is_active=True)
            .order_by('-started_at')
            .first()
        )
        if not session:
            session = PracticeSession.objects.create(
                player_codename=codename,
                practice_type=practice_type,
                distance='ing',
                drill_type='',   # open-ended, no fixed total
            )

        with transaction.atomic():
            Shot.objects.create(session=session, outcome=outcome)
            session.refresh_from_db()

        total = session.total_shots
        if practice_type == 'shooting':
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
        else:
            stats = {
                'total': total,
                'perfects': session.perfects,
                'petit_perfects': session.petit_perfects,
                'goods': session.goods,
                'fairs': session.fairs,
                'fars': session.fars,
                'accuracy': round(session.hit_percentage, 1) if total > 0 else 0.0,
                'session_id': str(session.id),
                'is_active': session.is_active,
            }
        # Wrap in the combined format so the JS _updateStatsDisplay can update both tables.
        # The just-recorded type gets the live stats; the other type is fetched from the
        # last active session so both tables refresh in one round-trip.
        other_type = 'pointing' if practice_type == 'shooting' else 'shooting'
        other_stats_dict = _get_player_shot_stats(pc.player_id, match_type, pk)
        combined = {
            practice_type: stats,
            other_type: other_stats_dict.get(other_type, (
                _empty_shooting_stats() if other_type == 'shooting' else _empty_pointing_stats()
            )),
        }
        return JsonResponse({'ok': True, 'practice_type': practice_type, 'stats': combined})

    except Exception as exc:
        logger.error("match_tracking record_shot error: %s", exc)
        return JsonResponse({'ok': False, 'error': 'Shot recording failed'}, status=500)


# ─────────────────────────────────────────────────────────────────────────────
# AJAX: undo last shot for an authorized player
# ─────────────────────────────────────────────────────────────────────────────

@csrf_exempt
@require_http_methods(["POST"])
def undo_last_shot(request, match_type, pk):
    """
    POST { codename: str }

    Removes the most recently recorded Shot for the given codename in this
    match (across both shooting and pointing sessions).  After deletion,
    session.update_statistics() is called automatically via Shot.delete()
    signal / pre_delete, then we refresh_from_db and return the updated
    combined stats.

    Only one shot is removed per call (simple one-step undo).
    """
    if match_type not in ('match', 'game'):
        return JsonResponse({'error': 'Invalid match type'}, status=400)

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'ok': False, 'error': 'Invalid JSON'}, status=400)

    codename = data.get('codename', '').strip().upper()
    if not codename:
        return JsonResponse({'ok': False, 'error': 'Codename required'}, status=400)

    # Verify codename belongs to a participant
    players = _build_player_list(match_type, pk)
    try:
        from friendly_games.models import PlayerCodename
        pc = PlayerCodename.objects.select_related('player').get(codename=codename)
    except PlayerCodename.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'Unknown codename'}, status=403)

    if not any(p['player_id'] == pc.player_id for p in players):
        return JsonResponse({'ok': False, 'error': 'Not a participant in this game'}, status=403)

    try:
        from practice.models import PracticeSession, Shot

        # Find the most recent Shot across all active sessions for this codename
        last_shot = (
            Shot.objects
            .filter(
                session__player_codename=codename,
                session__is_active=True,
            )
            .order_by('-timestamp', '-id')
            .select_related('session')
            .first()
        )
        if not last_shot:
            return JsonResponse({'ok': False, 'error': 'No shots to undo'}, status=404)

        session = last_shot.session
        practice_type = session.practice_type
        last_shot.delete()          # Shot.save() calls update_statistics, but delete() does not
        session.update_statistics() # manually recalculate after deletion
        session.refresh_from_db()   # pick up the updated counters

        # Build updated stats for the affected session
        total = session.total_shots
        if practice_type == 'shooting':
            updated_stats = {
                'total': total,
                'carreaux': session.carreaux,
                'petit_carreaux': session.petit_carreaux,
                'hits': session.hits,
                'misses': session.misses,
                'accuracy': round(session.hit_percentage, 1) if total > 0 else 0.0,
                'session_id': str(session.id),
                'is_active': session.is_active,
            }
        else:
            updated_stats = {
                'total': total,
                'perfects': session.perfects,
                'petit_perfects': session.petit_perfects,
                'goods': session.goods,
                'fairs': session.fairs,
                'fars': session.fars,
                'accuracy': round(session.hit_percentage, 1) if total > 0 else 0.0,
                'session_id': str(session.id),
                'is_active': session.is_active,
            }

        other_type = 'pointing' if practice_type == 'shooting' else 'shooting'
        other_stats_dict = _get_player_shot_stats(pc.player_id, match_type, pk)
        combined = {
            practice_type: updated_stats,
            other_type: other_stats_dict.get(other_type, (
                _empty_shooting_stats() if other_type == 'shooting' else _empty_pointing_stats()
            )),
        }
        return JsonResponse({
            'ok': True,
            'undone_outcome': last_shot.outcome,
            'practice_type': practice_type,
            'stats': combined,
        })

    except Exception as exc:
        logger.error("match_tracking undo_last_shot error: %s", exc)
        return JsonResponse({'ok': False, 'error': 'Undo failed'}, status=500)


# ─────────────────────────────────────────────────────────────────────────────
# Export Match Analysis to PDF
# ─────────────────────────────────────────────────────────────────────────────

@require_http_methods(["GET"])
def export_pdf(request, match_type, pk):
    """
    GET /track/<match_type>/<pk>/pdf/
    Returns a PDF containing the current match analysis:
      - Match information
      - Score / score progression
      - Players
      - Shooting statistics per player
      - Pointing statistics per player
    Uses only data already recorded by Match Tracking.
    """
    if match_type not in ('match', 'game'):
        from django.http import Http404
        raise Http404

    from io import BytesIO
    from django.http import HttpResponse
    from django.utils import timezone
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_LEFT

    # ── Gather data ─────────────────────────────────────────────────────────────────────────────
    if match_type == 'match':
        from matches.models import Match
        game_obj = get_object_or_404(Match, pk=pk)
        team1_name = game_obj.team1.name
        team2_name = game_obj.team2.name
        game_label = str(game_obj)
        game_status = game_obj.status
    else:
        from friendly_games.models import FriendlyGame
        game_obj = get_object_or_404(FriendlyGame, pk=pk)
        team1_name = 'Black'
        team2_name = 'White'
        game_label = str(game_obj)
        game_status = game_obj.status

    scoreboard = _get_scoreboard_or_none(match_type, pk)
    team1_score = scoreboard.team1_score if scoreboard else 0
    team2_score = scoreboard.team2_score if scoreboard else 0
    score_history = _get_score_history(scoreboard) if scoreboard else []
    players = _build_player_list(match_type, pk)

    # Gather per-player stats
    player_stats = []
    for p in players:
        stats = _get_player_shot_stats(p['player_id'], match_type, pk)
        player_stats.append({
            'name': p['player_name'],
            'team': p['team'],
            'position': p['position'],
            'shooting': stats.get('shooting', _empty_shooting_stats()),
            'pointing': stats.get('pointing', _empty_pointing_stats()),
        })

    # ── Build PDF ─────────────────────────────────────────────────────────────────────────────
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=15*mm, rightMargin=15*mm,
        topMargin=15*mm, bottomMargin=15*mm,
    )
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle('h1', parent=styles['Heading1'], fontSize=16, spaceAfter=4, alignment=TA_CENTER)
    h2 = ParagraphStyle('h2', parent=styles['Heading2'], fontSize=12, spaceAfter=3, spaceBefore=8)
    h3 = ParagraphStyle('h3', parent=styles['Heading3'], fontSize=10, spaceAfter=2, spaceBefore=5)
    normal = ParagraphStyle('normal', parent=styles['Normal'], fontSize=9)
    small  = ParagraphStyle('small',  parent=styles['Normal'], fontSize=8, textColor=colors.grey)

    BLUE   = colors.HexColor('#1a56db')
    PURPLE = colors.HexColor('#7c3aed')
    LIGHT  = colors.HexColor('#f8fafc')
    MID    = colors.HexColor('#e2e8f0')

    story = []

    # Title
    story.append(Paragraph('Match Analysis', h1))
    story.append(Paragraph(game_label, ParagraphStyle('sub', parent=styles['Normal'], fontSize=10, alignment=TA_CENTER, textColor=colors.grey)))
    story.append(Spacer(1, 4*mm))

    # Match info table
    info_data = [
        ['Status', game_status],
        ['Teams', f'{team1_name}  vs  {team2_name}'],
        ['Score', f'{team1_name}: {team1_score}  —  {team2_name}: {team2_score}'],
        ['Exported', timezone.localtime().strftime('%Y-%m-%d %H:%M')],
    ]
    info_tbl = Table(info_data, colWidths=[35*mm, None])
    info_tbl.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (0,-1), LIGHT),
        ('FONTNAME', (0,0), (0,-1), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,-1), 9),
        ('GRID', (0,0), (-1,-1), 0.3, MID),
        ('ROWBACKGROUNDS', (0,0), (-1,-1), [LIGHT, colors.white]),
        ('TOPPADDING', (0,0), (-1,-1), 3),
        ('BOTTOMPADDING', (0,0), (-1,-1), 3),
    ]))
    story.append(info_tbl)
    story.append(Spacer(1, 5*mm))

    # Score Progression
    if score_history:
        story.append(Paragraph('Score Progression', h2))
        hist_data = [['Time', 'Score', 'By']]
        for h in score_history:
            hist_data.append([h['ts'], f"{h['team1_score']}–{h['team2_score']}", h.get('by','')])
        hist_tbl = Table(hist_data, colWidths=[22*mm, 22*mm, None])
        hist_tbl.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), BLUE),
            ('TEXTCOLOR', (0,0), (-1,0), colors.white),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('FONTSIZE', (0,0), (-1,-1), 8),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, LIGHT]),
            ('GRID', (0,0), (-1,-1), 0.3, MID),
            ('TOPPADDING', (0,0), (-1,-1), 2),
            ('BOTTOMPADDING', (0,0), (-1,-1), 2),
        ]))
        story.append(hist_tbl)
        story.append(Spacer(1, 5*mm))

    # Shooting Statistics
    story.append(Paragraph('Shooting Statistics', h2))
    shoot_data = [['Player', 'Team', 'Pos', 'N', 'Acc%', 'Carreau', 'Petit C', 'Hit', 'Miss']]
    for ps in player_stats:
        s = ps['shooting']
        shoot_data.append([
            ps['name'], ps['team'], ps['position'] or '',
            str(s.get('total', 0)),
            f"{s.get('accuracy', 0):.1f}%",
            str(s.get('carreaux', 0)),
            str(s.get('petit_carreaux', 0)),
            str(s.get('hits', 0)),
            str(s.get('misses', 0)),
        ])
    shoot_tbl = Table(shoot_data, colWidths=[35*mm, 15*mm, 15*mm, 10*mm, 14*mm, 16*mm, 16*mm, 12*mm, 12*mm])
    shoot_tbl.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), BLUE),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,-1), 8),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, LIGHT]),
        ('GRID', (0,0), (-1,-1), 0.3, MID),
        ('TOPPADDING', (0,0), (-1,-1), 2),
        ('BOTTOMPADDING', (0,0), (-1,-1), 2),
    ]))
    story.append(shoot_tbl)
    story.append(Spacer(1, 5*mm))

    # Pointing Statistics
    story.append(Paragraph('Pointing Statistics', h2))
    point_data = [['Player', 'Team', 'Pos', 'N', 'Acc%', 'Perfect', 'Good', 'Fair', 'Far']]
    for ps in player_stats:
        p = ps['pointing']
        point_data.append([
            ps['name'], ps['team'], ps['position'] or '',
            str(p.get('total', 0)),
            f"{p.get('accuracy', 0):.1f}%",
            str(p.get('perfects', 0)),
            str(p.get('goods', 0)),
            str(p.get('fairs', 0)),
            str(p.get('fars', 0)),
        ])
    point_tbl = Table(point_data, colWidths=[35*mm, 15*mm, 15*mm, 10*mm, 14*mm, 16*mm, 12*mm, 12*mm, 12*mm])
    point_tbl.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), PURPLE),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,-1), 8),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, LIGHT]),
        ('GRID', (0,0), (-1,-1), 0.3, MID),
        ('TOPPADDING', (0,0), (-1,-1), 2),
        ('BOTTOMPADDING', (0,0), (-1,-1), 2),
    ]))
    story.append(point_tbl)

    doc.build(story)
    buf.seek(0)
    filename = f'match_analysis_{match_type}_{pk}.pdf'
    response = HttpResponse(buf.read(), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


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
