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
