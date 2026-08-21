"""
invites/views.py
================
HTTP views for the PFC invitation system.

Endpoints:
    GET  /invites/                          — invite hub (send + inbox)
    POST /invites/send/                     — send play or team-build invite
    POST /invites/<token>/accept/           — accept an invite
    POST /invites/<token>/reject/           — reject an invite
    GET  /invites/inbox/                    — JSON: pending invites for current player
    GET  /invites/session/<token>/          — JSON: team build session status
    GET  /invites/players/search/           — JSON: player search (name/codename)

Session auth: uses the existing codename session (session['player_codename']).
"""
import json
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404
from django.views.decorators.http import require_POST, require_GET
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from django.db.models import Q

from friendly_games.models import PlayerCodename
from teams.models import Player
from courts.models import CourtComplex
from tournaments.models import Tournament
from tournaments.registration_services import TournamentRegistrationEligibilityError

from .models import Invitation, TeamBuildSession


# ── Auth helper ───────────────────────────────────────────────────────────────

def _register_completed_tournament_build(session, team):
    """Register a completed build through the same Team eligibility service."""
    if not (session.is_tournament_type and session.tournament_id):
        return False, None

    from signin.services import activate_team_tournament_signin

    try:
        registration = activate_team_tournament_signin(
            team=team,
            tournament=session.tournament,
            voucher_code=session.registration_voucher_code,
        )
    except TournamentRegistrationEligibilityError as exc:
        return False, ' '.join(exc.messages)

    # An existing TournamentTeam is still a successful tournament registration.
    return bool(registration.get('tournament_team')), None


def _get_current_player(request):
    """
    Return the Player for the currently logged-in codename session.
    Returns None if not authenticated.
    """
    codename = request.session.get("player_codename")
    if not codename:
        return None
    try:
        pc = PlayerCodename.objects.select_related("player").get(
            codename=codename.upper()
        )
        return pc.player
    except PlayerCodename.DoesNotExist:
        return None


def _push(group, event_type, payload):
    """Broadcast a channel-layer event to a group (sync wrapper)."""
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        group,
        {"type": event_type, **payload},
    )


# ── Hub page ──────────────────────────────────────────────────────────────────

def invite_hub(request):
    """
    Main invite page — shows send form and inbox.
    Requires player to be logged in via codename session.
    """
    player = _get_current_player(request)
    courts = CourtComplex.objects.all().order_by("name")
    tournaments = Tournament.objects.filter(
        is_active=True
    ).order_by("name")

    context = {
        "player": player,
        "courts": courts,
        "tournaments": tournaments,
    }
    return render(request, "invites/invite_hub.html", context)


# ── Send invite ───────────────────────────────────────────────────────────────

@csrf_exempt
@require_POST
def send_invite(request):
    """
    POST /invites/send/
    Body (JSON):
        invite_type      : "play" | "team_build"
        recipient_ids    : [int, ...]          — Player PKs
        message          : str (max 200 chars, optional)

        # play invite extras
        play_time        : "YYYY-MM-DDTHH:MM"  (optional)
        play_court_id    : int                  (optional)
        play_notes       : str                  (optional)

        # team build extras
        target_size      : int (2–6)
        build_type       : "normal" | "tournament"
        tournament_id    : int (optional, for tournament builds)
        proposed_name    : str (optional)
    """
    sender = _get_current_player(request)
    if not sender:
        return JsonResponse({"error": "Not authenticated"}, status=401)

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    invite_type   = data.get("invite_type", "play")
    recipient_ids = data.get("recipient_ids", [])
    message       = str(data.get("message", ""))[:200]

    if not recipient_ids:
        return JsonResponse({"error": "No recipients specified"}, status=400)

    recipients = Player.objects.filter(pk__in=recipient_ids)
    if not recipients.exists():
        return JsonResponse({"error": "No valid recipients found"}, status=400)

    # ── PLAY INVITE ───────────────────────────────────────────────────────────
    if invite_type == Invitation.INVITE_TYPE_PLAY:
        play_time = None
        raw_time  = data.get("play_time")
        if raw_time:
            try:
                from django.utils.dateparse import parse_datetime
                play_time = parse_datetime(raw_time)
            except Exception:
                pass

        court = None
        court_id = data.get("play_court_id")
        if court_id:
            court = CourtComplex.objects.filter(pk=court_id).first()

        play_notes = str(data.get("play_notes", ""))[:200]

        created_invites = []
        for recipient in recipients:
            if recipient.pk == sender.pk:
                continue
            inv = Invitation.objects.create(
                invite_type=Invitation.INVITE_TYPE_PLAY,
                sender=sender,
                recipient=recipient,
                message=message,
                play_time=play_time,
                play_court=court,
                play_notes=play_notes,
            )
            created_invites.append(inv)
            # Push realtime event to recipient
            _push(
                f"player_{recipient.pk}",
                "invite.received",
                {
                    "invite_id":   inv.pk,
                    "token":       str(inv.token),
                    "invite_type": inv.invite_type,
                    "sender_name": sender.name,
                    "message":     message,
                    "play_time":   play_time.isoformat() if play_time else None,
                    "play_court":  court.name if court else None,
                },
            )

        return JsonResponse({
            "ok": True,
            "invite_type": "play",
            "count": len(created_invites),
        })

    # ── TEAM BUILD INVITE ─────────────────────────────────────────────────────
    elif invite_type == Invitation.INVITE_TYPE_TEAM:
        target_size   = int(data.get("target_size", 3))
        build_type    = data.get("build_type", TeamBuildSession.BUILD_TYPE_NORMAL)
        tournament_id = data.get("tournament_id")
        proposed_name = str(data.get("proposed_name", ""))[:100]
        registration_voucher_code = str(data.get("registration_voucher_code", ""))[:40].strip().upper()

        tournament = None
        if tournament_id:
            tournament = Tournament.objects.filter(pk=tournament_id).first()

        session = TeamBuildSession.objects.create(
            creator=sender,
            build_type=build_type,
            target_size=target_size,
            tournament=tournament,
            registration_voucher_code=registration_voucher_code,
            proposed_team_name=proposed_name,
        )

        created_invites = []
        for recipient in recipients:
            if recipient.pk == sender.pk:
                continue
            inv = Invitation.objects.create(
                invite_type=Invitation.INVITE_TYPE_TEAM,
                sender=sender,
                recipient=recipient,
                message=message,
                session=session,
            )
            created_invites.append(inv)
            # Push realtime event to recipient
            _push(
                f"player_{recipient.pk}",
                "invite.received",
                {
                    "invite_id":   inv.pk,
                    "token":       str(inv.token),
                    "invite_type": inv.invite_type,
                    "sender_name": sender.name,
                    "message":     message,
                    "session_id":  session.pk,
                    "target_size": target_size,
                },
            )

        return JsonResponse({
            "ok": True,
            "invite_type": "team_build",
            "session_id": session.pk,
            "session_token": str(session.token),
            "count": len(created_invites),
        })

    return JsonResponse({"error": "Unknown invite_type"}, status=400)


# ── Accept / Reject ───────────────────────────────────────────────────────────

@csrf_exempt
@require_POST
def accept_invite(request, token):
    """POST /invites/<token>/accept/"""
    player = _get_current_player(request)
    if not player:
        return JsonResponse({"error": "Not authenticated"}, status=401)

    inv = get_object_or_404(Invitation, token=token)

    if inv.recipient_id != player.pk:
        return JsonResponse({"error": "Not your invite"}, status=403)

    if not inv.is_pending:
        return JsonResponse({"error": "Invite already responded to"}, status=400)

    inv.accept()

    # Notify sender
    _push(
        f"player_{inv.sender_id}",
        "invite.accepted",
        {
            "invite_id":      inv.pk,
            "token":          str(inv.token),
            "recipient_name": player.name,
            "session_id":     inv.session_id,
            "accepted_count": inv.session.accepted_count if inv.session else None,
            "target_size":    inv.session.target_size if inv.session else None,
        },
    )

    result = {"ok": True, "status": "accepted"}

    # ── Team build: add to session and check quorum ───────────────────────────
    if inv.session:
        session = inv.session
        session.accepted_players.add(player)

        # Notify session creator of progress
        _push(
            f"player_{session.creator_id}",
            "session.update",
            {
                "session_id":     session.pk,
                "accepted_count": session.accepted_count,
                "target_size":    session.target_size,
            },
        )

        if session.is_ready and session.status == TeamBuildSession.SESSION_OPEN:
            team = session.create_team()
            if team:
                # Tournament builds use the same centralized capacity and
                # voucher eligibility service as every other Team registration.
                tournament_registered, registration_error = _register_completed_tournament_build(session, team)

                # Notify all accepted players + creator
                all_pids = list(
                    session.accepted_players.values_list("pk", flat=True)
                ) + [session.creator_id]
                for pid in set(all_pids):
                    _push(
                        f"player_{pid}",
                        "session.ready",
                        {
                            "session_id":            session.pk,
                            "team_id":               team.pk,
                            "team_name":             team.name,
                            "team_pin":              team.pin,
                            "tournament_registered": tournament_registered,
                            "tournament_registration_error": registration_error,
                        },
                    )
                result["team_created"]          = True
                result["team_id"]               = team.pk
                result["team_name"]             = team.name
                result["team_pin"]              = team.pin
                result["tournament_registered"] = tournament_registered
                result["tournament_registration_error"] = registration_error

    return JsonResponse(result)


@csrf_exempt
@require_POST
def reject_invite(request, token):
    """POST /invites/<token>/reject/"""
    player = _get_current_player(request)
    if not player:
        return JsonResponse({"error": "Not authenticated"}, status=401)

    inv = get_object_or_404(Invitation, token=token)

    if inv.recipient_id != player.pk:
        return JsonResponse({"error": "Not your invite"}, status=403)

    if not inv.is_pending:
        return JsonResponse({"error": "Invite already responded to"}, status=400)

    inv.reject()

    # Notify sender
    _push(
        f"player_{inv.sender_id}",
        "invite.rejected",
        {
            "invite_id":      inv.pk,
            "token":          str(inv.token),
            "recipient_name": player.name,
        },
    )

    return JsonResponse({"ok": True, "status": "rejected"})


# ── Inbox (JSON) ──────────────────────────────────────────────────────────────

@require_GET
def inbox(request):
    """GET /invites/inbox/ — pending actions plus accepted Invitation history."""
    player = _get_current_player(request)
    if not player:
        return JsonResponse({"error": "Not authenticated"}, status=401)

    # Accepted rows retain their original fields in the existing Invitation
    # model. Keep them in the recipient's Inbox as read-only history, while
    # declined/expired rows retain the current hidden behavior.
    invites = (
        Invitation.objects
        .filter(
            recipient=player,
            status__in=[Invitation.STATUS_PENDING, Invitation.STATUS_ACCEPTED],
        )
        .select_related("sender", "play_court", "session")
        .order_by("-created_at")[:50]
    )
    pending_count = sum(1 for invite in invites if invite.status == Invitation.STATUS_PENDING)

    data = []
    for inv in invites:
        data.append({
            "id":          inv.pk,
            "token":       str(inv.token),
            "invite_type": inv.invite_type,
            "sender_name": inv.sender.name,
            "message":     inv.message,
            "play_notes":  inv.play_notes,
            "status":      inv.status,
            "responded_at": inv.responded_at.isoformat() if inv.responded_at else None,
            "play_time":   inv.play_time.isoformat() if inv.play_time else None,
            "play_court":  inv.play_court.name if inv.play_court else None,
            "session_id":  inv.session_id,
            "target_size": inv.session.target_size if inv.session else None,
            "created_at":  inv.created_at.isoformat(),
        })

    return JsonResponse({"invites": data, "pending_count": pending_count})


# ── Session status (JSON) ─────────────────────────────────────────────────────

@require_GET
def session_status(request, token):
    """GET /invites/session/<token>/ — team build session status."""
    player = _get_current_player(request)
    if not player:
        return JsonResponse({"error": "Not authenticated"}, status=401)

    session = get_object_or_404(TeamBuildSession, token=token)

    if session.creator_id != player.pk:
        # Only creator can poll session status
        return JsonResponse({"error": "Forbidden"}, status=403)

    invitations = session.invitations.select_related("recipient").all()
    inv_data = [
        {
            "recipient_name": i.recipient.name,
            "status":         i.status,
        }
        for i in invitations
    ]

    return JsonResponse({
        "session_id":     session.pk,
        "token":          str(session.token),
        "status":         session.status,
        "build_type":     session.build_type,
        "accepted_count": session.accepted_count,
        "target_size":    session.target_size,
        "invitations":    inv_data,
        "team_id":        session.created_team_id,
        "team_name":      session.created_team.name if session.created_team else None,
        "team_pin":       session.created_team.pin  if session.created_team else None,
    })


# ── QR start session (JSON) ────────────────────────────────────────────────────

@csrf_exempt
@require_POST
def qr_start_session(request):
    """
    POST /invites/qr-start-session/

    Body (JSON): { "target_size": int, "proposed_name": str (optional),
                   "include_creator": bool (default true) }

    Creates a TeamBuildSession for the QR direct-build flow (no invites sent).
    Returns the session token so the client can use qr_add_player.
    """
    import json as _json
    creator = _get_current_player(request)
    if not creator:
        return JsonResponse({"error": "Not authenticated"}, status=401)

    try:
        data = _json.loads(request.body)
    except (_json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    target_size     = int(data.get("target_size", 3))
    proposed_name   = str(data.get("proposed_name", ""))[:100]
    include_creator = bool(data.get("include_creator", True))

    if target_size < 2 or target_size > 6:
        return JsonResponse({"error": "target_size must be between 2 and 6"}, status=400)

    session = TeamBuildSession.objects.create(
        creator=creator,
        build_type=TeamBuildSession.BUILD_TYPE_NORMAL,
        target_size=target_size,
        proposed_team_name=proposed_name,
        include_creator=include_creator,
    )

    return JsonResponse({
        "ok": True,
        "session_token": str(session.token),
        "session_id":    session.pk,
        "target_size":   target_size,
        "include_creator": include_creator,
    })


# ── QR add player (JSON) ─────────────────────────────────────────────────────

@csrf_exempt
@require_POST
def qr_add_player(request):
    """
    POST /invites/qr-add-player/

    Body (JSON): { "session_token": "<TeamBuildSession UUID>" }

    Called immediately after a successful QR scan (which stores the resolved
    codename in the session via the existing /matches/api/qr-resolve/ endpoint).

    This is the DIRECT addition path — no invite is created, no acceptance is
    required.  The QR scan itself is the player's authorization to join.

    Two sub-cases:
      A. Team not yet created (session still open):
         → Add the scanned player to session.accepted_players.
         → If quorum is now reached, create_team() is called immediately.
      B. Team already created:
         → Move the scanned player directly onto the existing team
           (player.team = team; player.save()).

    Safeguards:
      - Requester must be the session creator.
      - Scanned player must be a valid existing PFC player.
      - Cannot add yourself.
      - Duplicate check: player already in session / team is rejected.
    """
    import json as _json
    requester = _get_current_player(request)
    if not requester:
        return JsonResponse({"error": "Not authenticated"}, status=401)

    try:
        data = _json.loads(request.body)
    except (_json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    session_token = data.get("session_token", "").strip()
    if not session_token:
        return JsonResponse({"error": "session_token is required"}, status=400)

    session = TeamBuildSession.objects.filter(token=session_token).first()
    if not session:
        return JsonResponse({"error": "Team build session not found"}, status=404)

    # Only the session creator can add players via QR
    if session.creator_id != requester.pk:
        return JsonResponse({"error": "Only the team creator can add players via QR scan"}, status=403)

    if session.status != TeamBuildSession.SESSION_OPEN:
        return JsonResponse({"error": "This team build session is no longer open"}, status=400)

    # Read and pop the QR-resolved codename from the session (cannot be replayed)
    codename = request.session.pop("qr_resolved_codename", None)
    if not codename:
        return JsonResponse(
            {"error": "No QR scan found in session. Please scan a player QR card first."},
            status=400,
        )

    # Resolve the player from the codename (server-side only)
    try:
        from friendly_games.models import PlayerCodename
        pc = PlayerCodename.objects.select_related("player__team").get(
            codename=codename.upper()
        )
    except PlayerCodename.DoesNotExist:
        return JsonResponse({"error": "Player not found"}, status=404)

    player = pc.player

    # Cannot add yourself
    if player.pk == requester.pk:
        return JsonResponse(
            {"error": "You are already the team creator and do not need to be added."},
            status=400,
        )

    # ── Sub-case B: team already exists ─────────────────────────────────────────────────────────────────────────────────
    if session.created_team_id:
        team = session.created_team
        # Duplicate check
        if player.team_id == team.pk:
            return JsonResponse(
                {"error": f"{player.name} is already a member of this team."},
                status=400,
            )
        # Move player onto the existing team (same logic as create_team)
        player.team = team
        player.save(update_fields=["team"])
        return JsonResponse({
            "ok": True,
            "added": True,
            "player_id":   player.pk,
            "player_name": player.name,
            "team_id":     team.pk,
            "team_name":   team.name,
            "team_pin":    team.pin,
            "team_created": False,
        })

    # ── Sub-case A: team not yet created ───────────────────────────────────────────────────────────────────────────────────
    # Duplicate check
    if session.accepted_players.filter(pk=player.pk).exists():
        return JsonResponse(
            {"error": f"{player.name} has already been added to this session."},
            status=400,
        )

    # Add directly to accepted_players (no invite created, no acceptance step)
    session.accepted_players.add(player)

    # Check if quorum is now reached and create the team if so
    team_created = False
    team = None
    tournament_registered = False
    if session.is_ready and session.status == TeamBuildSession.SESSION_OPEN:
        team = session.create_team()
        if team:
            team_created = True
            tournament_registered, registration_error = _register_completed_tournament_build(session, team)
            # Notify all accepted players + creator via channel layer
            all_pids = list(
                session.accepted_players.values_list("pk", flat=True)
            ) + [session.creator_id]
            for pid in set(all_pids):
                _push(
                    f"player_{pid}",
                    "session.ready",
                    {
                        "session_id":            session.pk,
                        "team_id":               team.pk,
                        "team_name":             team.name,
                        "team_pin":              team.pin,
                        "tournament_registered": tournament_registered,
                        "tournament_registration_error": registration_error,
                    },
                )
    else:
        # Notify creator of updated progress
        _push(
            f"player_{session.creator_id}",
            "session.update",
            {
                "session_id":     session.pk,
                "accepted_count": session.accepted_count,
                "target_size":    session.target_size,
            },
        )

    return JsonResponse({
        "ok": True,
        "added": True,
        "player_id":             player.pk,
        "player_name":           player.name,
        "team_id":               team.pk if team else None,
        "team_name":             team.name if team else None,
        "team_pin":              team.pin if team else None,
        "team_created":          team_created,
        "tournament_registered": tournament_registered,
        "accepted_count":        session.accepted_count,
        "target_size":           session.target_size,
    })


# ── Player search (JSON) ──────────────────────────────────────────────────────

@require_GET
def player_search(request):
    """
    GET /invites/players/search/?q=<query>
    Returns up to 20 players matching name or codename.
    Excludes the current player from results.
    """
    player = _get_current_player(request)
    if not player:
        return JsonResponse({"error": "Not authenticated"}, status=401)

    q = request.GET.get("q", "").strip()
    if len(q) < 2:
        return JsonResponse({"players": []})

    # Search by player name
    name_matches = Player.objects.filter(
        name__icontains=q
    ).exclude(pk=player.pk).select_related("team")[:20]

    # Also search by codename
    codename_matches = PlayerCodename.objects.filter(
        codename__icontains=q.upper()
    ).exclude(player_id=player.pk).select_related("player__team")[:20]

    seen = set()
    results = []

    for p in name_matches:
        if p.pk not in seen:
            seen.add(p.pk)
            results.append({
                "id":        p.pk,
                "name":      p.name,
                "team_name": p.team.name if p.team else "",
            })

    for pc in codename_matches:
        p = pc.player
        if p.pk not in seen:
            seen.add(p.pk)
            results.append({
                "id":        p.pk,
                "name":      p.name,
                "team_name": p.team.name if p.team else "",
            })

    return JsonResponse({"players": results[:20]})
