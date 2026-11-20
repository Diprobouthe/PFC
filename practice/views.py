"""
Practice Views for PFC Shooting Practice (v0.2)

Adds:
- court_complex selection on session start
- Tir de Précision structured shot recording (atelier + shot_distance)
- API endpoint for court complex list
"""

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import JsonResponse, HttpResponse, HttpResponseForbidden
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from django.db import transaction
import json

from pfc_core.session_utils import CodenameSessionManager, SessionManager
from .models import (
    PracticeSession, Shot, PracticeStatistics,
    SHOOTING_SUCCESS_OUTCOMES, POINTING_SUCCESS_OUTCOMES,
)
from .utils import calculate_session_summary, get_player_progress_summary



# Authorizations are browser-session scoped and do not change the operator login.
PRACTICE_DELEGATION_KEY = "delegated_practice_session"  # backwards-compatible single QR
PRACTICE_GRANTS_KEY = "practice_qr_grants"
PRACTICE_SELECTED_KEY = "practice_selected_owner"
PRACTICE_SUMMARY_GRANT_KEY = "delegated_practice_summary"
PRACTICE_SUMMARY_GRANT_SECONDS = 900


def _practice_grant_key(grant):
    return f"{grant['codename']}:{grant['practice_type']}"


def _practice_grants(request):
    grants = dict(request.session.get(PRACTICE_GRANTS_KEY) or {})
    legacy = request.session.get(PRACTICE_DELEGATION_KEY) or {}
    if legacy.get("codename") and legacy.get("practice_type"):
        key = _practice_grant_key(legacy)
        if key not in grants:
            grants[key] = legacy
    return grants


def _save_practice_grants(request, grants):
    if grants:
        request.session[PRACTICE_GRANTS_KEY] = grants
        request.session[PRACTICE_DELEGATION_KEY] = list(grants.values())[-1]
    else:
        request.session.pop(PRACTICE_GRANTS_KEY, None)
        request.session.pop(PRACTICE_DELEGATION_KEY, None)
    request.session.modified = True


def _selected_practice_key(request, grants=None):
    if grants is None:
        grants = _practice_grants(request)
    selected = request.session.get(PRACTICE_SELECTED_KEY)
    if selected == "self" or selected in grants:
        return selected
    return list(grants)[-1] if grants else "self"


def _remove_practice_grant(request, key):
    grants = _practice_grants(request)
    grants.pop(key, None)
    _save_practice_grants(request, grants)
    if request.session.get(PRACTICE_SELECTED_KEY) == key:
        # A revoked authorization never silently switches the next shot to someone else.
        request.session[PRACTICE_SELECTED_KEY] = "self"
        request.session.modified = True


def _valid_practice_grant_session(grant):
    if not grant.get("session_id"):
        return None
    return PracticeSession.objects.filter(
        pk=grant["session_id"], player_codename=grant["codename"],
        practice_type=grant["practice_type"], is_active=True,
    ).first()


def _practice_owner_codename(request, practice_type=None):
    """Recipient explicitly selected by the operator, not by the current page."""
    grants = _practice_grants(request)
    selected = _selected_practice_key(request, grants)
    if selected != "self":
        grant = grants[selected]
        if practice_type and grant.get("practice_type") != practice_type:
            return None
        if grant.get("session_id") and not _valid_practice_grant_session(grant):
            _remove_practice_grant(request, selected)
            return None
        return grant["codename"]
    return CodenameSessionManager.get_logged_in_codename(request)


def _practice_active_session(request, practice_type=None, session_id=None):
    """Fail closed on expired grants and cross-player or cross-session requests."""
    grants = _practice_grants(request)
    selected = _selected_practice_key(request, grants)
    if selected != "self":
        grant = grants[selected]
        active = _valid_practice_grant_session(grant)
        if active is None:
            if grant.get("session_id"):
                _remove_practice_grant(request, selected)
            return None
        if practice_type and active.practice_type != practice_type:
            return None
        if session_id and str(active.pk) != str(session_id):
            return None
        return active

    own = CodenameSessionManager.get_logged_in_codename(request)
    if not own:
        return None
    query = PracticeSession.objects.filter(player_codename=own, is_active=True)
    if practice_type:
        query = query.filter(practice_type=practice_type)
    if session_id:
        query = query.filter(pk=session_id)
    return query.order_by("-started_at").first()


def _practice_owner_ui_context(request, practice_type):
    """Name chips share the same server-side selection on shooting and pointing."""
    from friendly_games.models import PlayerCodename

    own = CodenameSessionManager.get_logged_in_codename(request)
    grants = _practice_grants(request)
    for key, grant in list(grants.items()):
        if grant.get("session_id") and not _valid_practice_grant_session(grant):
            _remove_practice_grant(request, key)
    grants = _practice_grants(request)
    selected = _selected_practice_key(request, grants)

    codes = ([own] if own else []) + [g["codename"] for g in grants.values()]
    profiles = PlayerCodename.objects.select_related("player").filter(
        codename__in=codes
    ) if codes else []
    names = {p.codename: p.player.name for p in profiles}
    options = []
    if own:
        options.append({
            "key": "self", "name": names.get(own, own),
            "practice_type": practice_type, "is_delegated": False,
        })
    for key, grant in grants.items():
        options.append({
            "key": key, "name": names.get(grant["codename"], grant["codename"]),
            "practice_type": grant["practice_type"], "is_delegated": True,
        })
    current = next((c for c in options if c["key"] == selected), None)
    return {
        "practice_owner_choices": options,
        "practice_mode": practice_type,
        "practice_selected_key": selected,
        "recording_player_name": current["name"] if current else own,
        "is_practice_delegated": bool(current and current["is_delegated"]),
    }


def _requested_practice_session_id(request):
    try:
        return json.loads(request.body or b"{}").get("session_id")
    except (TypeError, ValueError):
        return None


@require_http_methods(["POST"])
def select_practice_owner(request):
    """Switch between own and previously QR-authorised players without re-scan."""
    from django.urls import reverse

    try:
        payload = json.loads(request.body)
    except (TypeError, ValueError):
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    key = payload.get("owner")
    grants = _practice_grants(request)
    if key == "self":
        if not CodenameSessionManager.is_logged_in(request):
            return JsonResponse({"error": "Player login required"}, status=401)
        # Resume the most recent personal practice, not an arbitrary mode.
        own_codename = CodenameSessionManager.get_logged_in_codename(request)
        own_active = PracticeSession.objects.filter(
            player_codename=own_codename, is_active=True
        ).order_by("-started_at").first()
        target_type = own_active.practice_type if own_active else payload.get("practice_type")
        if target_type not in ("shooting", "pointing"):
            target_type = "shooting"
    elif key in grants:
        grant = grants[key]
        if grant.get("session_id") and not _valid_practice_grant_session(grant):
            _remove_practice_grant(request, key)
            return JsonResponse({"error": "Authorised practice is no longer active"}, status=409)
        target_type = grant["practice_type"]
    else:
        return JsonResponse({"error": "No QR authorization for this player"}, status=403)

    request.session[PRACTICE_SELECTED_KEY] = key
    request.session.modified = True
    destination = ("practice:shooting_practice" if target_type == "shooting"
                   else "practice:pointing_practice")
    return JsonResponse({"success": True, "next_url": reverse(destination)})


@csrf_exempt
@require_http_methods(["POST"])
def authorize_practice_qr(request):
    """Consume the existing QR resolver proof to delegate one active session."""
    from friendly_games.models import PlayerCodename
    qr_codename = request.session.pop("qr_resolved_codename", None)
    request.session.modified = True
    if not qr_codename:
        return JsonResponse({"error": "Scan the player's QR again"}, status=403)
    if not PlayerCodename.objects.filter(codename=qr_codename).exists():
        return JsonResponse({"error": "Unknown player QR"}, status=403)
    try:
        practice_type = json.loads(request.body).get("practice_type")
    except (ValueError, TypeError):
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    if practice_type not in ("shooting", "pointing"):
        return JsonResponse({"error": "Invalid practice type"}, status=400)
    active = PracticeSession.objects.filter(
        player_codename=qr_codename, practice_type=practice_type,
        is_active=True,
    ).first()
    grant = {
        "session_id": str(active.pk) if active else None,
        "codename": qr_codename, "practice_type": practice_type,
    }
    grants = _practice_grants(request)
    key = _practice_grant_key(grant)
    grants.pop(key, None)
    grants[key] = grant
    _save_practice_grants(request, grants)
    request.session[PRACTICE_SELECTED_KEY] = key
    request.session.modified = True
    return JsonResponse({"success": True, "practice_type": practice_type,
                         "session_id": str(active.pk) if active else None})


@csrf_exempt
@require_http_methods(["POST"])
def leave_delegated_practice(request):
    selected = _selected_practice_key(request)
    if selected != "self":
        _remove_practice_grant(request, selected)
    return JsonResponse({"success": True})


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
    if not CodenameSessionManager.is_logged_in(request) and not getattr(request, "session", {}).get(PRACTICE_DELEGATION_KEY):
        messages.error(request, "Please log in with your codename to start practice.")
        return redirect('practice:practice_home')

    session_context = SessionManager.get_session_context(request)
    selected_key = _selected_practice_key(request)
    if selected_key != "self":
        grant = _practice_grants(request).get(selected_key)
        if grant and grant.get("practice_type") == "pointing":
            return redirect("practice:pointing_practice")
    codename = _practice_owner_codename(request, 'shooting')

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

    # Build Tactical atelier info for the template
    from .tactical_scenarios import TACTICAL_ATELIERS
    tactical_ateliers = TACTICAL_ATELIERS

    # Build Sequence Drill atelier info for the template
    from .sequence_scenarios import SEQUENCE_ATELIERS
    sequence_ateliers = SEQUENCE_ATELIERS

    # Build Hidden Target atelier info for the template
    from .hidden_target_scenarios import HIDDEN_TARGET_ATELIERS
    hidden_target_ateliers = HIDDEN_TARGET_ATELIERS

    # Pre-populate all TdP/Tactical/Sequence/HiddenTarget shots for the JS state machine (prevents desync on reload)
    import json as _json
    initial_shots_json = '[]'

    # Serialize Hidden Target ateliers to JSON for JS injection (after _json import)
    hidden_target_ateliers_json = _json.dumps([
        {
            'number': a['number'],
            'label': a['label'],
            'short': a['short'],
            'desc': a['description'],
            'legend': a['legend'],
            'svg': a['svg'],
            'pts': a['pts'],
        }
        for a in HIDDEN_TARGET_ATELIERS
    ])
    if active_session and active_session.drill_type in ('tir_de_precision', 'tactical', 'sequence', 'hidden_target'):
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

    grant = getattr(request, 'session', {}).get(PRACTICE_DELEGATION_KEY) or {}
    delegated_name = None
    if grant.get('codename') == codename and grant.get('practice_type') == 'shooting':
        from friendly_games.models import PlayerCodename
        pc = PlayerCodename.objects.select_related('player').filter(codename=codename).first()
        delegated_name = pc.player.name if pc else 'Player'

    context = {
        **session_context,
        **_practice_owner_ui_context(request, 'shooting'),
        'delegated_practice_name': delegated_name,
        'active_session': active_session,
        'recent_sessions': recent_sessions,
        'court_complexes': court_complexes,
        'tdp_ateliers': tdp_ateliers,
        'tdp_distances': tdp_distances,
        'tactical_ateliers': tactical_ateliers,
        'sequence_ateliers': sequence_ateliers,
        'hidden_target_ateliers': hidden_target_ateliers,
        'hidden_target_ateliers_json': hidden_target_ateliers_json,
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
    selected_key = _selected_practice_key(request)
    if selected_key != "self":
        grant = _practice_grants(request).get(selected_key)
        if grant and grant.get("practice_type") == "shooting":
            return redirect("practice:shooting_practice")
    codename = _practice_owner_codename(request, 'pointing')

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

    grant = getattr(request, 'session', {}).get(PRACTICE_DELEGATION_KEY) or {}
    delegated_name = None
    if grant.get('codename') == codename and grant.get('practice_type') == 'pointing':
        from friendly_games.models import PlayerCodename
        pc = PlayerCodename.objects.select_related('player').filter(codename=codename).first()
        delegated_name = pc.player.name if pc else 'Player'

    context = {
        **session_context,
        **_practice_owner_ui_context(request, 'pointing'),
        'delegated_practice_name': delegated_name,
        'active_session': active_session,
        'recent_sessions': recent_sessions,
        'page_title': 'Pointing Practice',
    }

    return render(request, 'practice/pointing_practice.html', context)


@csrf_exempt
@require_http_methods(["POST"])
def start_session(request):
    """Start a new practice session."""
    if not CodenameSessionManager.is_logged_in(request) and not getattr(request, "session", {}).get(PRACTICE_DELEGATION_KEY):
        return JsonResponse({'error': 'Authentication required'}, status=401)

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

    grants = _practice_grants(request)
    chosen = _selected_practice_key(request, grants)
    grant = grants.get(chosen) if chosen != "self" else None
    if grant and grant.get('practice_type') != practice_type:
        return JsonResponse({'error': 'QR authorization is for a different practice type'}, status=403)
    codename = _practice_owner_codename(request, practice_type)
    if not codename:
        return JsonResponse({'error': 'Choose an authorised practice first'}, status=409)

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

    # Tir de Précision, Tactical, Sequence, and Hidden Target always use sequence tracking
    if drill_type in ('tir_de_precision', 'tactical', 'sequence', 'hidden_target'):
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
        if grant and not grant.get("session_id"):
            grant = {**grant, "session_id": str(session.pk)}
            grants[chosen] = grant
            _save_practice_grants(request, grants)
        if court_complex_obj:
            response['court_complex_name'] = court_complex_obj.name

        return JsonResponse(response)

    except Exception as e:
        return JsonResponse({'error': 'Failed to start session'}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def record_shot(request):
    """Record a shot in the active session."""
    if not CodenameSessionManager.is_logged_in(request) and not request.session.get(PRACTICE_DELEGATION_KEY):
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

        requested_id = data.get("session_id")
        session = _practice_active_session(request, session_id=requested_id)

        if not session:
            return JsonResponse({'error': 'Practice selection changed or session ended'}, status=409 if requested_id else 404)

        # Validate TdP-specific fields (also used for Tactical, Sequence, and Hidden Target)
        if session.drill_type in ('tir_de_precision', 'tactical', 'sequence', 'hidden_target'):
            if atelier is None or int(atelier) not in range(1, 6):
                return JsonResponse({'error': 'atelier (1-5) required for this drill type'}, status=400)
            if shot_distance not in Shot.TDP_DISTANCES:
                return JsonResponse({'error': 'shot_distance (6m/7m/8m/9m) required for this drill type'}, status=400)

        with transaction.atomic():
            shot_kwargs = {
                'session': session,
                'outcome': outcome,
            }
            if session.drill_type in ('tir_de_precision', 'tactical', 'sequence', 'hidden_target'):
                shot_kwargs['atelier'] = int(atelier)
                shot_kwargs['shot_distance'] = shot_distance

            shot = Shot.objects.create(**shot_kwargs)

            session.refresh_from_db()

            recent_shots = list(session.shots.order_by('-sequence_number')[:10].values(
                'sequence_number', 'outcome', 'timestamp', 'atelier', 'shot_distance'
            ))

            current_streak = 0
            success_outcomes = SHOOTING_SUCCESS_OUTCOMES | POINTING_SUCCESS_OUTCOMES
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
            if session.drill_type in ('tir_de_precision', 'tactical', 'sequence', 'hidden_target'):
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
                    (session.successful_shots / total * 100)
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
    if not CodenameSessionManager.is_logged_in(request) and not request.session.get(PRACTICE_DELEGATION_KEY):
        return JsonResponse({'error': 'Authentication required'}, status=401)

    requested_id = _requested_practice_session_id(request)
    session = _practice_active_session(request, session_id=requested_id)
    codename = session.player_codename if session else None

    if not session:
        return JsonResponse({'error': 'Practice selection changed or session ended'}, status=409 if requested_id else 404)

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
            success_outcomes = (
                POINTING_SUCCESS_OUTCOMES if session.practice_type == 'pointing'
                else SHOOTING_SUCCESS_OUTCOMES
            )
            for shot_data in session.shots.order_by('-sequence_number'):
                if shot_data.outcome in success_outcomes:
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
        if session.practice_type == 'pointing':
            # Pointing UI needs all four counts after Undo, not shooting-only fields.
            response['session_stats'].update({
                'perfects': session.perfects,
                'petit_perfects': session.petit_perfects,
                'goods': session.goods,
                'fairs': session.fairs,
                'fars': session.fars,
                'success_percentage': round(session.hit_percentage, 1),
            })
        if session.drill_type in ('tir_de_precision', 'tactical', 'sequence', 'hidden_target'):
            response['session_stats']['tdp_score'] = session.tdp_score

        return JsonResponse(response)

    except Exception as e:
        return JsonResponse({'error': 'Failed to undo shot'}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def end_session(request):
    """End the active practice session."""
    if not CodenameSessionManager.is_logged_in(request) and not request.session.get(PRACTICE_DELEGATION_KEY):
        return JsonResponse({'error': 'Authentication required'}, status=401)

    requested_id = _requested_practice_session_id(request)
    session = _practice_active_session(request, session_id=requested_id)
    codename = session.player_codename if session else None

    if not session:
        return JsonResponse({'error': 'Practice selection changed or session ended'}, status=409 if requested_id else 404)

    try:
        with transaction.atomic():
            session.end_session()
            grants = _practice_grants(request)
            selected = _selected_practice_key(request, grants)
            grant = grants.get(selected) if selected != "self" else None
            if (grant and grant.get('session_id') == str(session.pk)
                    and grant.get('codename') == session.player_codename):
                request.session[PRACTICE_SUMMARY_GRANT_KEY] = {
                    'session_id': str(session.pk),
                    'codename': session.player_codename,
                    'issued_at': int(timezone.now().timestamp()),
                }
                _remove_practice_grant(request, selected)
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

    own_codename = session_context.get('session_codename')
    is_owner = bool(
        session_context['player_logged_in'] and own_codename
        and session.player_codename.upper() == own_codename.upper()
    )

    # QR delegates may inspect only the active session they were authorized for,
    # or its completed summary for 15 minutes immediately after finishing.
    active_delegate = session.is_active and any(
        grant.get("session_id") == str(session.pk)
        and grant.get("codename") == session.player_codename
        for grant in _practice_grants(request).values()
    )
    summary_grant = request.session.get(PRACTICE_SUMMARY_GRANT_KEY) or {}
    try:
        seconds_since_issue = (
            int(timezone.now().timestamp()) - int(summary_grant.get('issued_at'))
        )
    except (TypeError, ValueError):
        seconds_since_issue = PRACTICE_SUMMARY_GRANT_SECONDS + 1
    recent_delegate = (
        summary_grant.get('session_id') == str(session.pk)
        and summary_grant.get('codename') == session.player_codename
        and 0 <= seconds_since_issue <= PRACTICE_SUMMARY_GRANT_SECONDS
    )

    if not (is_owner or active_delegate or recent_delegate):
        return HttpResponseForbidden('Practice session details are private.')

    summary = calculate_session_summary(session)
    shots = session.shots.order_by('sequence_number')

    # For TdP and Tactical sessions, build a structured atelier breakdown
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
    elif session.drill_type == 'tactical':
        from .tactical_scenarios import TACTICAL_ATELIERS
        tdp_breakdown = []
        for atelier_info in TACTICAL_ATELIERS:
            a_num = atelier_info['number']
            a_shots = [s for s in shots if s.atelier == a_num]
            a_score = sum(s.tdp_points for s in a_shots)
            tdp_breakdown.append({
                'atelier': atelier_info,
                'shots': a_shots,
                'score': a_score,
                'max_score': 20,  # 4 shots × 5 pts max
            })
    elif session.drill_type == 'sequence':
        from .sequence_scenarios import SEQUENCE_ATELIERS
        tdp_breakdown = []
        for atelier_info in SEQUENCE_ATELIERS:
            a_num = atelier_info['number']
            a_shots = [s for s in shots if s.atelier == a_num]
            a_score = sum(s.tdp_points for s in a_shots)
            tdp_breakdown.append({
                'atelier': atelier_info,
                'shots': a_shots,
                'score': a_score,
                'max_score': 20,  # 4 shots × 5 pts max
            })
    elif session.drill_type == 'hidden_target':
        from .hidden_target_scenarios import HIDDEN_TARGET_ATELIERS
        tdp_breakdown = []
        for atelier_info in HIDDEN_TARGET_ATELIERS:
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


@require_http_methods(['GET'])
def session_summary_pdf(request, session_id):
    """Download the actual practice report as PDF for native file sharing."""
    if not CodenameSessionManager.is_logged_in(request):
        return HttpResponseForbidden('Player login is required to export practice data.')

    session = get_object_or_404(PracticeSession, id=session_id)
    codename = CodenameSessionManager.get_logged_in_codename(request)
    if not codename or session.player_codename != codename:
        return HttpResponseForbidden('You can only export your own practice session.')

    from .pdf_reports import render_practice_summary_pdf
    pdf_bytes = render_practice_summary_pdf(session)
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    filename = f'PFC_Practice_{session.practice_type}_{session.started_at:%Y%m%d}_{str(session.id)[:8]}.pdf'
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


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

    # Reuse the exact same read-only snapshot for the list and longitudinal
    # progress; never write to a session when opening the history page.
    session_list = list(sessions)
    from .history_progress import summarize_accuracy_views
    progress_groups = summarize_accuracy_views(session_list)
    progress = progress_groups['all']

    sessions_with_summary = []
    for session in session_list:
        summary = calculate_session_summary(session)
        sessions_with_summary.append({
            'session': session,
            'summary': summary,
        })

    context = {
        **session_context,
        'sessions': sessions_with_summary,
        'total_sessions': len(session_list),
        'progress': progress,
        'progress_groups': progress_groups,
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
