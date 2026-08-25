"""Lifecycle helpers for match-scoped Match Tracking authorization and sessions."""

from django.db import transaction

from .models import MatchTrackingSession, TrackingAuthorization, TrackingPracticeSession


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
    return LiveScoreboard.objects.filter(**lookup).first()


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

    broadcast_tracking_feed(scoreboard.id, current_end_actions_for_scoreboard(scoreboard))


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
        scoreboard.id,
        {
            "id": str(shot.id),
            "player_name": authorization.player.name,
            "outcome": shot.outcome,
            "side": side,
        },
    )
