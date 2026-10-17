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


def _is_tracking_active(match_type, pk):
    """Return whether this exact match/game is still eligible for tracking."""
    if match_type == 'match':
        from matches.models import Match
        return Match.objects.filter(pk=pk, status__in=['active', 'ACTIVE']).exists()
    from friendly_games.models import FriendlyGame
    return FriendlyGame.objects.filter(
        pk=pk,
        status__in=['active', 'ACTIVE', 'pending_verification', 'PENDING_VERIFICATION'],
    ).exists()


def _close_tracking_only_if_terminal(match_type, pk):
    """Finalize common tracking only when the underlying game is terminal.

    A submitted result awaiting validation is NOT terminal: it can be rejected
    and the same match can reopen without losing anyone's tracking period.
    """
    if match_type == "match":
        from matches.models import Match
        status = Match.objects.filter(pk=pk).values_list("status", flat=True).first()
        terminal = status in {"completed", "cancelled"}
    else:
        from friendly_games.models import FriendlyGame
        status = FriendlyGame.objects.filter(pk=pk).values_list("status", flat=True).first()
        terminal = status in {"COMPLETED", "CANCELLED", "EXPIRED"}

    if terminal:
        from .services import end_tracking_sessions
        end_tracking_sessions(match_type, pk, "match_completed")
    return terminal


def _serialize_practice_stats(session):
    """Return the established open-ended statistics shape for one PracticeSession."""
    total = session.total_shots
    base = {
        'total': total,
        'accuracy': round(session.hit_percentage, 1) if total > 0 else 0.0,
        'session_id': str(session.id),
        'is_active': session.is_active,
    }
    if session.practice_type == 'shooting':
        return {
            **base,
            'carreaux': session.carreaux,
            'petit_carreaux': session.petit_carreaux,
            'hits': session.hits,
            'misses': session.misses,
        }
    return {
        **base,
        'perfects': session.perfects,
        'petit_perfects': session.petit_perfects,
        'goods': session.goods,
        'fairs': session.fairs,
        'fars': session.fars,
    }


# Shooting outcomes (open-ended, no fixed total)
SHOOTING_OUTCOMES = {'carreau', 'petit_carreau', 'hit', 'miss'}
# Pointing outcomes — exactly the four categories used in the PFC Pointing practice UI
POINTING_OUTCOMES = {'perfect', 'good', 'fair', 'far'}


def _get_player_shot_stats(player_id, match_type, pk):
    """Aggregate every recorded tracking period for this exact match and player.

    The previous lookup took the last session only, silently hiding shots
    from earlier periods. Group all match-scoped links, never other games'
    PracticeSession records. The UI and historical PDF share this truth.
    """
    from .models import TrackingPracticeSession

    links = (
        TrackingPracticeSession.objects
        .filter(
            tracking_session__match_type=match_type,
            tracking_session__match_pk=pk,
            player_id=player_id,
        )
        .select_related("practice_session", "tracking_session")
        .order_by("created_at", "pk")
    )
    shooting_fields = ("carreaux", "petit_carreaux", "hits", "misses")
    pointing_fields = ("perfects", "petit_perfects", "goods", "fairs", "fars")
    groups = {
        "shooting": _empty_shooting_stats(),
        "pointing": _empty_pointing_stats(),
    }
    for link in links:
        kind = link.practice_type
        if kind not in groups:
            continue
        stats = groups[kind]
        session = link.practice_session
        stats["total"] += session.total_shots
        for field in shooting_fields if kind == "shooting" else pointing_fields:
            stats[field] += getattr(session, field)
        stats["session_id"] = str(session.pk)
        stats["is_active"] = bool(
            stats["is_active"]
            or (session.is_active and link.tracking_session.status == "active")
        )
    for kind, stats in groups.items():
        count = stats["total"]
        successes = (
            stats["hits"] + stats["petit_carreaux"] + stats["carreaux"]
            if kind == "shooting" else
            stats["perfects"] + stats["petit_perfects"] + stats["goods"] + stats["fairs"]
        )
        stats["accuracy"] = round(successes / count * 100, 1) if count else 0.0
        stats["has_recordings"] = count > 0
    return groups


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
    from matches.scoreboard_time import format_score_update_time
    updates = list(
        ScoreUpdate.objects
        .filter(scoreboard=scoreboard)
        .order_by('timestamp')
        .values('id', 'team1_score', 'team2_score', 'timestamp', 'scorekeeper_codename', 'update_type')
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
        display_name = codename_to_name.get(raw, '')  # Never expose a raw codename in history.
        result.append({
            'id': u['id'],
            'team1_score': u['team1_score'],
            'team2_score': u['team2_score'],
            'ts': format_score_update_time(u['timestamp'], scoreboard),
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

    # ── Browser-scoped tracking delegation + persistent broadcast state ─────
    from .services import (
        authorize_player,
        browser_delegated_authorizations,
        browser_score_authorization,
        get_active_tracking_session,
        remember_browser_delegation,
    )

    # A participant already logged in under their own codename keeps the
    # existing self-authorization convenience. Bind it to this browser session
    # exactly like a QR-granted tracking delegation.
    from pfc_core.session_utils import CodenameSessionManager
    logged_in_codename = CodenameSessionManager.get_logged_in_codename(request)
    auto_auth_player_id = None
    if logged_in_codename:
        try:
            from friendly_games.models import PlayerCodename
            pc = PlayerCodename.objects.select_related('player').get(codename=logged_in_codename)
            if any(p['player_id'] == pc.player_id for p in players):
                auto_auth_player_id = pc.player_id
                if _is_tracking_active(match_type, pk):
                    tracking_session, authorization = authorize_player(
                        match_type, pk, pc.player, pc.codename
                    )
                    remember_browser_delegation(request, tracking_session, authorization)
        except Exception:
            pass

    tracking_session = get_active_tracking_session(match_type, pk, create=False)
    if tracking_session:
        broadcast_by_player = {
            auth.player_id: auth.broadcast_permitted
            for auth in tracking_session.authorizations.filter(is_active=True)
        }
    else:
        broadcast_by_player = {}
    for player_data in players:
        player_data['broadcast_permitted'] = bool(
            broadcast_by_player.get(player_data['player_id'], False)
        )

    # Restore only the authorizations that this browser itself acquired. The
    # active DB rows alone never unlock another browser.
    browser_authorizations = browser_delegated_authorizations(
        request, match_type, pk, tracking_session=tracking_session
    )
    score_authorization = browser_score_authorization(request, match_type, pk)
    score_actor_player_id = score_authorization.player_id if score_authorization else None
    participant_by_id = {player['player_id']: player for player in players}
    browser_authorizations.sort(
        key=lambda authorization: 0 if authorization.player_id == score_actor_player_id else 1
    )
    browser_authorization_payload = []
    for authorization in browser_authorizations:
        participant = participant_by_id.get(authorization.player_id)
        if not participant:
            continue
        browser_authorization_payload.append({
            'player_id': authorization.player_id,
            'player_name': participant['player_name'],
            'broadcast_permitted': authorization.broadcast_permitted,
            'stats': _get_player_shot_stats(authorization.player_id, match_type, pk),
        })

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
        'browser_authorizations_json': json.dumps(browser_authorization_payload),
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
    """Persist QR authorization for one valid participant in this exact match/game."""
    if match_type not in ('match', 'game'):
        return JsonResponse({'error': 'Invalid match type'}, status=400)
    if not _is_tracking_active(match_type, pk):
        _close_tracking_only_if_terminal(match_type, pk)
        return JsonResponse({'ok': False, 'error': 'Match is no longer active'}, status=403)

    try:
        player_id = int(json.loads(request.body).get('player_id', 0))
    except (ValueError, TypeError, json.JSONDecodeError):
        return JsonResponse({'ok': False, 'error': 'Invalid request'}, status=400)

    participant = next((p for p in _build_player_list(match_type, pk) if p['player_id'] == player_id), None)
    if not participant:
        return JsonResponse({'ok': False, 'error': 'Player is not a participant in this game'}, status=403)

    # The shared QR resolver stores its proof server-side for this browser session.
    qr_codename = request.session.pop('qr_resolved_codename', None)
    request.session.modified = True
    if not qr_codename:
        return JsonResponse({'ok': False, 'error': 'Scan the player QR card again to authorize tracking'}, status=403)

    try:
        from friendly_games.models import PlayerCodename
        pc = PlayerCodename.objects.select_related('player').get(codename=qr_codename)
    except PlayerCodename.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'QR identity could not be resolved'}, status=403)
    if pc.player_id != player_id:
        return JsonResponse({'ok': False, 'error': 'QR identity mismatch'}, status=403)

    from .services import authorize_player, remember_browser_delegation
    tracking_session, authorization = authorize_player(match_type, pk, pc.player, pc.codename)
    remember_browser_delegation(request, tracking_session, authorization)
    stats = _get_player_shot_stats(player_id, match_type, pk)
    return JsonResponse({
        'ok': True,
        'tracking_session_id': tracking_session.id,
        'player_id': player_id,
        'player_name': participant['player_name'],
        'team': participant['team'],
        'position': participant['position'],
        'broadcast_permitted': authorization.broadcast_permitted,
        'stats': stats,
    })


# ─────────────────────────────────────────────────────────────────────────────
# AJAX: broadcast consent for an already tracking-authorized player
# ─────────────────────────────────────────────────────────────────────────────

@csrf_exempt
@require_http_methods(["POST"])
def broadcast_permission(request, match_type, pk):
    """Set explicit public-feed consent after a fresh QR proof for this player."""
    if match_type not in ('match', 'game'):
        return JsonResponse({'ok': False, 'error': 'Invalid match type'}, status=400)
    if not _is_tracking_active(match_type, pk):
        return JsonResponse({'ok': False, 'error': 'Match is no longer active'}, status=403)
    try:
        data = json.loads(request.body)
        player_id = int(data.get('player_id', 0))
        enabled = bool(data.get('enabled', False))
    except (ValueError, TypeError, json.JSONDecodeError):
        return JsonResponse({'ok': False, 'error': 'Invalid request'}, status=400)

    # A participant who is already signed in under their own active PFC
    # codename may control their own broadcast setting without scanning their
    # own QR card. This is the same self-authorization principle used for
    # their own Match Tracking. Every other player's broadcast still requires
    # a fresh QR proof from this browser session.
    from pfc_core.session_utils import CodenameSessionManager
    from friendly_games.models import PlayerCodename

    logged_in_codename = (CodenameSessionManager.get_logged_in_codename(request) or '').upper()
    pc = None
    if logged_in_codename:
        try:
            candidate = PlayerCodename.objects.select_related('player').get(codename=logged_in_codename)
            if candidate.player_id == player_id:
                pc = candidate
        except PlayerCodename.DoesNotExist:
            pass

    if pc is None:
        qr_codename = request.session.pop('qr_resolved_codename', None)
        request.session.modified = True
        if not qr_codename:
            return JsonResponse({'ok': False, 'error': 'Scan the player QR card to confirm broadcast permission'}, status=403)
        try:
            pc = PlayerCodename.objects.select_related('player').get(codename=qr_codename)
        except PlayerCodename.DoesNotExist:
            return JsonResponse({'ok': False, 'error': 'QR identity could not be resolved'}, status=403)
        if pc.player_id != player_id:
            return JsonResponse({'ok': False, 'error': 'QR identity mismatch'}, status=403)

    from .services import active_authorization, broadcast_current_end_feed
    authorization = active_authorization(match_type, pk, player_id, codename=pc.codename)
    if not authorization:
        return JsonResponse({'ok': False, 'error': 'Authorize tracking before enabling broadcast'}, status=403)
    authorization.broadcast_permitted = enabled
    authorization.save(update_fields=['broadcast_permitted'])
    broadcast_current_end_feed(match_type, pk)
    return JsonResponse({
        'ok': True,
        'player_id': player_id,
        'player_name': pc.player.name,
        'broadcast_permitted': authorization.broadcast_permitted,
    })


# ─────────────────────────────────────────────────────────────────────────────
# AJAX: record shot for an authorized player
# ─────────────────────────────────────────────────────────────────────────────

@csrf_exempt
@require_http_methods(["POST"])
def record_shot(request, match_type, pk):
    """Record one open-ended shot for a player authorized in this exact tracking period."""
    if match_type not in ('match', 'game'):
        return JsonResponse({'error': 'Invalid match type'}, status=400)
    try:
        data = json.loads(request.body)
        outcome = data.get('outcome', '').strip().lower()
        player_id = int(data.get('player_id', 0))
    except (json.JSONDecodeError, ValueError, TypeError):
        return JsonResponse({'ok': False, 'error': 'Invalid request'}, status=400)

    if outcome in SHOOTING_OUTCOMES:
        practice_type = 'shooting'
    elif outcome in POINTING_OUTCOMES:
        practice_type = 'pointing'
    else:
        return JsonResponse({'ok': False, 'error': 'Invalid outcome'}, status=400)

    if not _is_tracking_active(match_type, pk):
        _close_tracking_only_if_terminal(match_type, pk)
        return JsonResponse({'ok': False, 'error': 'Match is no longer active'}, status=403)

    from .services import (
        authorize_player,
        browser_authorization,
        get_or_create_tracking_practice_session,
        remember_browser_delegation,
    )
    authorization = browser_authorization(request, match_type, pk, player_id)
    if not authorization:
        # Preserve the existing logged-in participant convenience, but bind it
        # to this browser before accepting any tracking mutation.
        from pfc_core.session_utils import CodenameSessionManager
        logged_in_codename = (CodenameSessionManager.get_logged_in_codename(request) or '').upper()
        if logged_in_codename:
            try:
                from friendly_games.models import PlayerCodename
                pc = PlayerCodename.objects.select_related('player').get(codename=logged_in_codename)
                if (
                    pc.player_id == player_id
                    and any(p['player_id'] == player_id for p in _build_player_list(match_type, pk))
                ):
                    tracking_session, authorization = authorize_player(
                        match_type, pk, pc.player, pc.codename
                    )
                    remember_browser_delegation(request, tracking_session, authorization)
            except PlayerCodename.DoesNotExist:
                authorization = None
        if not authorization:
            return JsonResponse(
                {'ok': False, 'error': 'Scan this participant QR card to authorize tracking'},
                status=403,
            )

    try:
        from practice.models import Shot
        from django.db import transaction
        with transaction.atomic():
            session = get_or_create_tracking_practice_session(
                authorization.tracking_session,
                authorization.player,
                authorization.codename,
                practice_type,
            )
            shot = Shot.objects.create(session=session, outcome=outcome)
            session.refresh_from_db()

        from .services import broadcast_permitted_action
        broadcast_permitted_action(match_type, pk, authorization, shot)
        combined = _get_player_shot_stats(player_id, match_type, pk)
        return JsonResponse({
            'ok': True,
            'practice_type': practice_type,
            'stats': combined,
        })
    except Exception as exc:
        logger.exception("match_tracking record_shot failed for %s:%s", match_type, pk)
        return JsonResponse({'ok': False, 'error': 'Shot recording failed'}, status=500)


# ─────────────────────────────────────────────────────────────────────────────
# AJAX: undo last shot for an authorized player
# ─────────────────────────────────────────────────────────────────────────────

@csrf_exempt
@require_http_methods(["POST"])
def undo_last_shot(request, match_type, pk):
    """Undo one latest shot belonging only to this player and tracking period."""
    if match_type not in ('match', 'game'):
        return JsonResponse({'error': 'Invalid match type'}, status=400)
    try:
        data = json.loads(request.body)
        player_id = int(data.get('player_id', 0))
    except (json.JSONDecodeError, ValueError, TypeError):
        return JsonResponse({'ok': False, 'error': 'Invalid request'}, status=400)

    if not _is_tracking_active(match_type, pk):
        _close_tracking_only_if_terminal(match_type, pk)
        return JsonResponse({'ok': False, 'error': 'Match is no longer active'}, status=403)

    from .services import browser_authorization
    authorization = browser_authorization(request, match_type, pk, player_id)
    if not authorization:
        return JsonResponse(
            {'ok': False, 'error': 'Scan this participant QR card to authorize tracking'},
            status=403,
        )

    try:
        from practice.models import Shot
        last_shot = (
            Shot.objects.filter(
                session__match_tracking_link__tracking_session=authorization.tracking_session,
                session__match_tracking_link__player=authorization.player,
            )
            .select_related('session')
            .order_by('-timestamp', '-id')
            .first()
        )
        if not last_shot:
            return JsonResponse({'ok': False, 'error': 'No shots to undo'}, status=404)

        session = last_shot.session
        undone_outcome = last_shot.outcome
        last_shot.delete()
        session.update_statistics()
        session.refresh_from_db()
        from .services import broadcast_current_end_feed
        broadcast_current_end_feed(match_type, pk)
        return JsonResponse({
            'ok': True,
            'undone_outcome': undone_outcome,
            'practice_type': session.practice_type,
            'stats': _get_player_shot_stats(player_id, match_type, pk),
        })
    except Exception:
        logger.exception("match_tracking undo_last_shot failed for %s:%s", match_type, pk)
        return JsonResponse({'ok': False, 'error': 'Undo failed'}, status=500)


# ─────────────────────────────────────────────────────────────────────────────
# Export Match Analysis to PDF
# ─────────────────────────────────────────────────────────────────────────────

@require_http_methods(["GET"])
def export_pdf(request, match_type, pk):
    """Render Match Analysis on demand, including historical tracking periods."""
    if match_type not in ("match", "game"):
        from django.http import Http404
        raise Http404

    from io import BytesIO
    from django.http import HttpResponse
    from django.utils import timezone
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Spacer

    from pfc_core.pdf_reporting import header, heading, table, text, page_footer

    if match_type == "match":
        from matches.models import Match
        game_obj = get_object_or_404(Match, pk=pk)
        team1_name, team2_name = game_obj.team1.name, game_obj.team2.name
        game_status = game_obj.status
    else:
        from friendly_games.models import FriendlyGame
        game_obj = get_object_or_404(FriendlyGame, pk=pk)
        team1_name, team2_name = "Black", "White"
        game_status = game_obj.status

    scoreboard = _get_scoreboard_or_none(match_type, pk)
    # After confirmation, official scores always win over an old/missing live
    # scoreboard. An absent live scoreboard must never become a fake 0-0.
    if match_type == "match" and game_status == "completed":
        score1, score2 = game_obj.team1_score, game_obj.team2_score
        score_source = "Επικυρωμένο αποτέλεσμα"
    elif match_type == "game" and game_status == "COMPLETED":
        score1, score2 = game_obj.black_team_score, game_obj.white_team_score
        score_source = "Επικυρωμένο αποτέλεσμα"
    elif scoreboard is not None:
        score1, score2 = scoreboard.team1_score, scoreboard.team2_score
        score_source = "LiveScore (προσωρινό)"
    else:
        score1 = score2 = None
        score_source = "Δεν υπάρχει διαθέσιμο σκορ"

    history = _get_score_history(scoreboard) if scoreboard else []
    players = _build_player_list(match_type, pk)
    player_stats = [
        {**player, "stats": _get_player_shot_stats(player["player_id"], match_type, pk)}
        for player in players
    ]
    has_shots = any(
        row["stats"][kind]["has_recordings"]
        for row in player_stats for kind in ("shooting", "pointing")
    )
    buff = BytesIO()
    doc = SimpleDocTemplate(
        buff, pagesize=A4, leftMargin=15*mm, rightMargin=15*mm,
        topMargin=13*mm, bottomMargin=18*mm,
        title=f"PFC Match Analysis {match_type} {pk}", author="PFC",
    )
    date_str = timezone.localtime().strftime("%d/%m/%Y %H:%M")
    story = header(
        "PFC – Ανάλυση παιχνιδιού",
        f"{team1_name} vs {team2_name} | #{pk} | {date_str}",
    )
    score = f"{score1} – {score2}" if score1 is not None and score2 is not None else "—"
    story.append(table([
        ["Πεδίο", "Τιμή"],
        ["Κατάσταση", game_status],
        ["Ομάδες", f"{team1_name} – {team2_name}"],
        ["Σκορ", score],
        ["Πηγή σκορ", score_source],
    ], [39*mm, 141*mm]))
    story.append(Spacer(1, 4*mm))
    if history:
        story.append(heading("Εξέλιξη σκορ"))
        rows = [["Χρόνος", "Σκορ", "Καταγραφή"]]
        rows.extend([
            item["ts"], f'{item["team1_score"]} – {item["team2_score"]}',
            item.get("by", "") or "—",
        ] for item in history)
        story.append(table(rows, [40*mm, 34*mm, 106*mm]))
        story.append(Spacer(1, 3*mm))

    if not has_shots:
        story.append(heading("Στατιστικά παικτών"))
        story.append(text(
            "Δεν έχουν καταγραφεί βολές στο Match Tracking για αυτό το παιχνίδι. "
            "Το επίσημο αποτέλεσμα παραμένει διαθέσιμο."
        ))
    else:
        story.append(text(
            "Στατιστικά: συγκεντρωτικά από ΟΛΕΣ τις αποθηκευμένες περιόδους "
            "Match Tracking του συγκεκριμένου παιχνιδιού.", size=8,
        ))
        for kind, title, keys, captions in [
            ("shooting", "Σουτ", ("carreaux", "petit_carreaux", "hits", "misses"),
             ("Carreau", "Petit C.", "Hit", "Miss")),
            ("pointing", "Προσέγγιση", ("perfects", "petit_perfects", "goods", "fairs", "fars"),
             ("Perfect", "Petit P.", "Good", "Fair", "Far")),
        ]:
            story.append(heading(title))
            rows = [["Παίκτης", "Πλευρά", "Βολές", "Ευστοχία", *captions]]
            for row in player_stats:
                stats = row["stats"][kind]
                if stats["has_recordings"]:
                    shots = [
                        stats["total"], f'{stats["accuracy"]:.1f}%',
                        *[stats[field] for field in keys],
                    ]
                else:
                    shots = ["—"] * (2 + len(keys))
                rows.append([row["player_name"], row["team"], *shots])
            if kind == "shooting":
                widths = [42, 22, 16, 24, 20, 22, 17, 17]
            else:
                widths = [40, 20, 16, 24, 18, 18, 15, 15, 14]
            story.append(table(rows, [width*mm for width in widths]))
            story.append(Spacer(1, 3*mm))
        story.append(text(
            "Το «—» σημαίνει ότι δεν υπάρχουν καταγεγραμμένες βολές για την "
            "κατηγορία, όχι μηδενική επίδοση.", size=7,
        ))
    doc.build(story, onFirstPage=page_footer, onLaterPages=page_footer)
    buff.seek(0)
    response = HttpResponse(buff.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="PFC_Match_Analysis_{match_type}_{pk}.pdf"'
    return response


# ─────────────────────────────────────────────────────────────────────────────
# AJAX: tracking session lifecycle
# ─────────────────────────────────────────────────────────────────────────────

@require_http_methods(["POST"])
def end_tracking_session(request, match_type, pk):
    """Disabled legacy route: a participant must never end shared tracking.

    Keep a rejecting endpoint for existing open browser tabs; removing only
    the button would leave the destructive POST callable.
    """
    if match_type not in ('match', 'game'):
        return JsonResponse({'error': 'Invalid match type'}, status=400)
    return JsonResponse(
        {'ok': False, 'error': 'Tracking ends automatically with the match.'},
        status=403,
    )


@require_http_methods(["GET"])
def game_status_api(request, match_type, pk):
    """Return status and automatically close tracking when the match has ended."""
    if match_type not in ('match', 'game'):
        return JsonResponse({'error': 'Invalid match type'}, status=400)
    try:
        if match_type == 'match':
            from matches.models import Match
            obj = Match.objects.only('status').get(pk=pk)
        else:
            from friendly_games.models import FriendlyGame
            obj = FriendlyGame.objects.only('status').get(pk=pk)
        is_active = _is_tracking_active(match_type, pk)
        if not is_active and _close_tracking_only_if_terminal(match_type, pk):
            from .services import clear_browser_delegation
            clear_browser_delegation(request, match_type, pk)
        return JsonResponse({'ok': True, 'status': obj.status, 'tracking_active': is_active})
    except Exception:
        return JsonResponse({'ok': False, 'error': 'Not found'}, status=404)
