"""Lifecycle helpers for match-scoped Match Tracking authorization and sessions."""

from django.db import transaction

from .models import MatchTrackingSession, TrackingAuthorization, TrackingPracticeSession


BROWSER_DELEGATIONS_SESSION_KEY = "match_tracking_browser_delegations"


def _delegation_scope_key(match_type, match_pk):
    return f"{match_type}:{int(match_pk)}"


def _session_delegations(request):
    value = request.session.get(BROWSER_DELEGATIONS_SESSION_KEY, {})
    return dict(value) if isinstance(value, dict) else {}


def remember_browser_delegation(request, tracking_session, authorization):
    """Bind one active TrackingAuthorization to the browser that obtained it."""
    scope = _delegation_scope_key(tracking_session.match_type, tracking_session.match_pk)
    delegations = _session_delegations(request)
    current = delegations.get(scope) or {}
    if current.get("tracking_session_id") != tracking_session.id:
        current = {
            "tracking_session_id": tracking_session.id,
            "player_ids": [],
            "score_actor_player_id": None,
        }

    player_ids = []
    for raw_id in current.get("player_ids", []):
        try:
            player_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        if player_id not in player_ids:
            player_ids.append(player_id)
    if authorization.player_id not in player_ids:
        player_ids.append(authorization.player_id)

    current["player_ids"] = player_ids
    if current.get("score_actor_player_id") not in player_ids:
        # Preserve current semantics: the first authorized participant is the
        # delegated score actor for this browser and tracking period.
        current["score_actor_player_id"] = authorization.player_id

    delegations[scope] = current
    request.session[BROWSER_DELEGATIONS_SESSION_KEY] = delegations
    request.session.modified = True
    return current


def clear_browser_delegation(request, match_type, match_pk):
    """Remove this browser's delegation for one match/game only."""
    scope = _delegation_scope_key(match_type, match_pk)
    delegations = _session_delegations(request)
    if scope in delegations:
        delegations.pop(scope, None)
        request.session[BROWSER_DELEGATIONS_SESSION_KEY] = delegations
        request.session.modified = True


def browser_delegated_authorizations(request, match_type, match_pk, tracking_session=None):
    """Return active authorizations delegated to this exact browser session."""
    tracking_session = tracking_session or get_active_tracking_session(match_type, match_pk, create=False)
    if not tracking_session:
        clear_browser_delegation(request, match_type, match_pk)
        return []

    scope = _delegation_scope_key(match_type, match_pk)
    delegations = _session_delegations(request)
    current = delegations.get(scope) or {}
    if current.get("tracking_session_id") != tracking_session.id:
        clear_browser_delegation(request, match_type, match_pk)
        return []

    ordered_ids = []
    for raw_id in current.get("player_ids", []):
        try:
            player_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        if player_id not in ordered_ids:
            ordered_ids.append(player_id)
    if not ordered_ids:
        clear_browser_delegation(request, match_type, match_pk)
        return []

    active_by_player = {
        authorization.player_id: authorization
        for authorization in tracking_session.authorizations.filter(
            player_id__in=ordered_ids,
            is_active=True,
        ).select_related("player")
    }
    ordered = [active_by_player[player_id] for player_id in ordered_ids if player_id in active_by_player]

    active_ids = [authorization.player_id for authorization in ordered]
    score_actor_player_id = current.get("score_actor_player_id")
    try:
        score_actor_player_id = int(score_actor_player_id) if score_actor_player_id is not None else None
    except (TypeError, ValueError):
        score_actor_player_id = None
    if score_actor_player_id not in active_ids:
        score_actor_player_id = active_ids[0] if active_ids else None

    if active_ids != ordered_ids or current.get("score_actor_player_id") != score_actor_player_id:
        current["player_ids"] = active_ids
        current["score_actor_player_id"] = score_actor_player_id
        delegations[scope] = current
        request.session[BROWSER_DELEGATIONS_SESSION_KEY] = delegations
        request.session.modified = True

    if not ordered:
        clear_browser_delegation(request, match_type, match_pk)
    return ordered


def browser_authorization(request, match_type, match_pk, player_id):
    """Return this browser's active delegation for one participant, if any."""
    try:
        player_id = int(player_id)
    except (TypeError, ValueError):
        return None
    for authorization in browser_delegated_authorizations(request, match_type, match_pk):
        if authorization.player_id == player_id:
            return authorization
    return None


def browser_score_authorization(request, match_type, match_pk):
    """Return the first delegated score actor for this browser and match."""
    authorizations = browser_delegated_authorizations(request, match_type, match_pk)
    if not authorizations:
        return None
    scope = _delegation_scope_key(match_type, match_pk)
    current = _session_delegations(request).get(scope) or {}
    try:
        actor_id = int(current.get("score_actor_player_id"))
    except (TypeError, ValueError):
        actor_id = None
    for authorization in authorizations:
        if authorization.player_id == actor_id:
            return authorization
    return authorizations[0]


def get_active_tracking_session(match_type, match_pk, create=False):
    """Return the current active tracking period for one match/game."""
    session = (
        MatchTrackingSession.objects.filter(
            match_type=match_type,
            match_pk=match_pk,
            status=MatchTrackingSession.STATUS_ACTIVE,
        )
        .order_by("-started_at")
        .first()
    )
    if session or not create:
        return session
    return MatchTrackingSession.objects.create(match_type=match_type, match_pk=match_pk)


def authorize_player(match_type, match_pk, player, codename):
    """Persist QR authorization for a participant in this tracking period."""
    with transaction.atomic():
        tracking_session = get_active_tracking_session(match_type, match_pk, create=True)
        authorization, _ = TrackingAuthorization.objects.update_or_create(
            tracking_session=tracking_session,
            player=player,
            defaults={"codename": codename, "is_active": True},
        )
    return tracking_session, authorization


def active_authorization(match_type, match_pk, player_id, codename=None):
    """Return the active authorization for a player within this exact match/game."""
    qs = TrackingAuthorization.objects.select_related("tracking_session", "player").filter(
        tracking_session__match_type=match_type,
        tracking_session__match_pk=match_pk,
        tracking_session__status=MatchTrackingSession.STATUS_ACTIVE,
        player_id=player_id,
        is_active=True,
    )
    if codename:
        qs = qs.filter(codename=codename)
    return qs.order_by("-authorized_at").first()


def get_or_create_tracking_practice_session(tracking_session, player, codename, practice_type):
    """Return the PracticeSession owned by this match-tracking period only."""
    link = (
        TrackingPracticeSession.objects.select_related("practice_session")
        .filter(
            tracking_session=tracking_session,
            player=player,
            practice_type=practice_type,
        )
        .first()
    )
    if link:
        return link.practice_session

    from practice.models import PracticeSession

    practice_session = PracticeSession.objects.create(
        player_codename=codename,
        practice_type=practice_type,
        distance="ing",
        drill_type="",  # Existing open-ended/OpenShots session convention.
    )
    TrackingPracticeSession.objects.create(
        tracking_session=tracking_session,
        player=player,
        practice_session=practice_session,
        practice_type=practice_type,
    )
    return practice_session


def tracking_practice_session(match_type, match_pk, player_id, practice_type):
    """Return active-period stats first, otherwise the latest read-only period for history."""
    base = TrackingPracticeSession.objects.select_related("practice_session").filter(
        tracking_session__match_type=match_type,
        tracking_session__match_pk=match_pk,
        player_id=player_id,
        practice_type=practice_type,
    )
    link = base.filter(
        tracking_session__status=MatchTrackingSession.STATUS_ACTIVE,
    ).order_by("-created_at").first()
    if not link:
        link = base.order_by("-created_at").first()
    return link.practice_session if link else None


def end_tracking_sessions(match_type, match_pk, reason):
    """Idempotently finalize every active tracking period for a match/game."""
    sessions = list(
        MatchTrackingSession.objects.filter(
            match_type=match_type,
            match_pk=match_pk,
            status=MatchTrackingSession.STATUS_ACTIVE,
        ).order_by("started_at")
    )
    for session in sessions:
        session.end(reason)
    return len(sessions)


def scoreboard_for_tracking(match_type, match_pk):
    """Resolve the existing LiveScoreboard for one tracked match/game, if present."""
    from matches.models import LiveScoreboard

    lookup = {"tournament_match_id": match_pk} if match_type == "match" else {"friendly_game_id": match_pk}
    return LiveScoreboard.objects.select_related("tournament_match").filter(**lookup).first()


def scoreboard_side_for_player(scoreboard, player_id):
    """Return the existing LiveScoreboard side key for one participating player."""
    if scoreboard.tournament_match_id:
        from matches.models import MatchPlayer

        match = scoreboard.tournament_match
        participant = (
            MatchPlayer.objects.filter(match=match, player_id=player_id)
            .values("team_id")
            .first()
        )
        if participant:
            if participant["team_id"] == match.team1_id:
                return "team1"
            if participant["team_id"] == match.team2_id:
                return "team2"
    elif scoreboard.friendly_game_id:
        participant = scoreboard.friendly_game.players.filter(player_id=player_id).values("team").first()
        if participant:
            if participant["team"] == "BLACK":
                return "team1"
            if participant["team"] == "WHITE":
                return "team2"
    return None


def delegated_scorekeeper_codename_for_scoreboard(request, scoreboard):
    """Resolve score authority only from this browser's active tracking delegation."""
    if scoreboard.tournament_match_id:
        match_type = "match"
        match_pk = scoreboard.tournament_match_id
        from matches.models import Match
        if not Match.objects.filter(pk=match_pk, status__in=["active", "ACTIVE"]).exists():
            return None
    elif scoreboard.friendly_game_id:
        match_type = "game"
        match_pk = scoreboard.friendly_game_id
        from friendly_games.models import FriendlyGame
        if not FriendlyGame.objects.filter(
            pk=match_pk,
            status__in=["active", "ACTIVE", "pending_verification", "PENDING_VERIFICATION"],
        ).exists():
            return None
    else:
        return None

    authorization = browser_score_authorization(request, match_type, match_pk)
    if not authorization:
        return None
    if scoreboard_side_for_player(scoreboard, authorization.player_id) is None:
        return None
    return authorization.codename


def current_end_actions_for_scoreboard(scoreboard):
    """Return the public, permitted actions recorded after the latest official score update.

    This is a read-only projection of existing Match Tracking Shot records. It
    never changes the tracking history, statistics, analytics, AI Coach, or PDF
    data. A player must have active match-scoped broadcast consent at query time.
    """
    from practice.models import Shot

    if scoreboard.tournament_match_id:
        match_type, match_pk = "match", scoreboard.tournament_match_id
    elif scoreboard.friendly_game_id:
        match_type, match_pk = "game", scoreboard.friendly_game_id
    else:
        return []

    tracking_session = get_active_tracking_session(match_type, match_pk, create=False)
    if not tracking_session:
        return []

    latest_score_update = scoreboard.score_updates.order_by("-timestamp", "-id").first()
    boundary = latest_score_update.timestamp if latest_score_update else tracking_session.started_at
    permitted_player_ids = list(
        tracking_session.authorizations.filter(
            is_active=True,
            broadcast_permitted=True,
        ).values_list("player_id", flat=True)
    )
    if not permitted_player_ids:
        return []

    shots = (
        Shot.objects.filter(
            session__match_tracking_link__tracking_session=tracking_session,
            session__match_tracking_link__player_id__in=permitted_player_ids,
            timestamp__gt=boundary,
        )
        .select_related("session__match_tracking_link__player")
        .order_by("timestamp", "id")
    )
    actions = []
    for shot in shots:
        player = shot.session.match_tracking_link.player
        side = scoreboard_side_for_player(scoreboard, player.id)
        if not side:
            continue
        actions.append({
            "id": str(shot.id),
            "player_name": player.name,
            "outcome": shot.outcome,
            "side": side,
        })
    return actions


def broadcast_current_end_feed(match_type, match_pk):
    """Replace the spectator feed from existing records after consent or undo changes."""
    scoreboard = scoreboard_for_tracking(match_type, match_pk)
    if not scoreboard:
        return
    from pfc_events.scoreboard_broadcast import broadcast_tracking_feed

    broadcast_tracking_feed(scoreboard, current_end_actions_for_scoreboard(scoreboard))


def broadcast_permitted_action(match_type, match_pk, authorization, shot):
    """Append one permitted existing Shot to the spectator feed after persistence."""
    if not authorization.broadcast_permitted:
        return
    scoreboard = scoreboard_for_tracking(match_type, match_pk)
    if not scoreboard:
        return
    from pfc_events.scoreboard_broadcast import broadcast_tracking_action

    side = scoreboard_side_for_player(scoreboard, authorization.player_id)
    if not side:
        return
    broadcast_tracking_action(
        scoreboard,
        {
            "id": str(shot.id),
            "player_name": authorization.player.name,
            "outcome": shot.outcome,
            "side": side,
        },
    )
