"""Transactional tournament Match lifecycle coordination.

This module is the sole owner of live tournament Match state transitions.  It
keeps Court reservation, Match status, official result state, and post-result
tournament follow-up inside small PostgreSQL lock scopes.  Friendly Games do
not use this service.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable

from django.db import transaction
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

from courts.models import Court
from courts.timezone_utils import get_court_local_now
from .models import Match, MatchLifecycleTransition, MatchResult

logger = logging.getLogger(__name__)

LIVE_COURT_STATUSES = ("active", "waiting_validation")


class MatchLifecycleError(Exception):
    """A stable domain error returned by a guarded lifecycle transition."""


@dataclass(frozen=True)
class CourtActivationOutcome:
    match_id: int
    state: str
    court_id: int | None = None

    @property
    def activated(self) -> bool:
        return self.state == "activated"


@dataclass(frozen=True)
class ResultOutcome:
    match_id: int
    state: str


@dataclass(frozen=True)
class CourtReleaseOutcome:
    """Result of an operational Court release, requeue, or reconciliation."""

    match_id: int | None
    court_id: int
    state: str
    promoted_match_id: int | None = None


def _locked_match(match_id: int) -> Match:
    """Return the base Match row under the lifecycle decision lock.

    Nullable Court and starting-team relationships deliberately remain outside
    ``select_related`` here so PostgreSQL locks only the Match row.
    """

    return (
        Match.objects.select_for_update(of=("self",))
        .select_related("tournament", "team1", "team2")
        .get(pk=match_id)
    )


def _court_now(court: Court | None):
    if not court:
        return timezone.now()
    prefetched = getattr(court, "_prefetched_objects_cache", {}).get("courtcomplex_set")
    complex_obj = prefetched[0] if prefetched else court.courtcomplex_set.first()
    return get_court_local_now(complex_obj) if complex_obj else timezone.now()


def _eligible_court_ids(match: Match) -> list[int] | None:
    """Return the permitted Court IDs, or ``None`` for the global fallback.

    The established pool priority is retained: Poule courts, tournament courts,
    then the normal global available-court pool.
    """

    if match.poule_id:
        ids = list(match.poule.courts.values_list("id", flat=True))
        if ids:
            return ids

    ids = list(match.tournament.tournamentcourt_set.values_list("court_id", flat=True))
    return ids or None


def _court_is_eligible_for_match(court: Court, match: Match) -> bool:
    eligible_ids = _eligible_court_ids(match)
    return eligible_ids is None or court.id in eligible_ids


def _court_has_other_live_match(court_id: int, match_id: int) -> bool:
    return Match.objects.filter(
        court_id=court_id,
        status__in=LIVE_COURT_STATUSES,
    ).exclude(pk=match_id).exists()


def _claim_court_locked(match: Match, *, requested_court_id: int | None = None) -> Court | None:
    """Claim one Court for an already locked Match.

    Candidate Court rows are locked with ``SKIP LOCKED`` and rechecked while
    locked.  The partial unique Match constraint remains the database backstop
    if an external writer ever bypasses this service.
    """

    if match.court_id:
        court = Court.objects.select_for_update(of=("self",)).get(pk=match.court_id)
        if not _court_is_eligible_for_match(court, match):
            raise MatchLifecycleError("The pre-assigned court is not valid for this match.")
        if _court_has_other_live_match(court.id, match.id):
            raise MatchLifecycleError("The pre-assigned court is already occupied.")
        if court.is_available:
            court.is_available = False
            court.save(update_fields=["is_available"])
        return court

    if requested_court_id is not None:
        candidates = Court.objects.filter(pk=requested_court_id, is_available=True)
    else:
        eligible_ids = _eligible_court_ids(match)
        candidates = Court.objects.filter(is_available=True)
        if eligible_ids is not None:
            candidates = candidates.filter(pk__in=eligible_ids)

    candidates = (
        candidates.exclude(
            pk__in=Match.objects.filter(
                status__in=LIVE_COURT_STATUSES,
                court__isnull=False,
            ).exclude(pk=match.pk).values("court_id")
        )
        .select_for_update(skip_locked=True, of=("self",))
        .order_by("pk")
    )

    court = candidates.first()
    if court is None:
        return None
    if not _court_is_eligible_for_match(court, match):
        return None
    if _court_has_other_live_match(court.id, match.id):
        return None

    match.court = court
    match.save(update_fields=["court", "updated_at"])
    court.is_available = False
    court.save(update_fields=["is_available"])
    return court


def _next_waiting_match_for_court_locked(
    court: Court,
    *,
    exclude_match_ids: Iterable[int] = (),
) -> Match | None:
    """Lock one Court-compatible queued Match directly in SQL.

    This avoids iterating every pending Match in Python each time a Court is
    released. A Match may use a Poule Court, a configured Tournament Court, or
    the established global fallback when its Tournament has no Court pool.
    """
    from tournaments.models import TournamentCourt
    from tournaments.poule_models import Poule

    has_tournament_pool = TournamentCourt.objects.filter(
        tournament_id=OuterRef("tournament_id")
    )
    poule_has_court = Poule.courts.through.objects.filter(
        poule_id=OuterRef("poule_id"),
        court_id=court.id,
    )
    eligible = (
        Exists(poule_has_court)
        | Exists(TournamentCourt.objects.filter(
            tournament_id=OuterRef("tournament_id"),
            court_id=court.id,
        ))
        | ~Exists(has_tournament_pool)
    )
    candidates = (
        Match.objects.filter(
            status="pending_verification",
            waiting_for_court=True,
        )
        .filter(Q(court__isnull=True) | Q(court_id=court.id))
        .filter(eligible)
        .select_for_update(skip_locked=True, of=("self",))
        .select_related("tournament", "team1", "team2")
        .order_by("created_at", "pk")
    )
    excluded_ids = list(exclude_match_ids)
    if excluded_ids:
        candidates = candidates.exclude(pk__in=excluded_ids)
    return candidates.first()


def _schedule_match_activated(match_id: int) -> None:
    """Run non-authoritative notifications/presence after the committed state."""

    def deliver() -> None:
        try:
            from .starting_team import announce_match_starting_team
            from .views import auto_register_players_to_billboard
            from pfc_events.signals import notify_match_state_changed

            match = Match.objects.select_related("court").get(pk=match_id)
            announce_match_starting_team(match)
            notify_match_state_changed(match.id, match.status)
            auto_register_players_to_billboard(match)
        except Exception:
            logger.exception("Post-commit activation delivery failed for Match %s", match_id)

    transaction.on_commit(deliver)


def _schedule_match_state_changed(match_id: int, status: str) -> None:
    """Deliver a state event only after the corresponding database commit."""

    def deliver() -> None:
        try:
            from pfc_events.signals import notify_match_state_changed

            notify_match_state_changed(match_id, status)
        except Exception:
            logger.exception("Post-commit state delivery failed for Match %s", match_id)

    transaction.on_commit(deliver)


def _make_court_available_locked(
    court: Court,
    *,
    promote_waiting: bool,
    exclude_match_ids: Iterable[int] = (),
) -> None:
    """Release a locked Court without bypassing the lifecycle queue.

    The normal Court post-save signal promotes waiting Matches after ordinary
    availability changes. Lifecycle-controlled releases schedule exactly one
    equivalent promotion themselves, avoiding a duplicate callback while the
    Match/Court decision is still protected by the current transaction.
    """

    if not court.is_available:
        court.is_available = True
        court._lifecycle_skip_auto_promotion = True
        court.save(update_fields=["is_available"])

    if promote_waiting:
        excluded_ids = tuple(exclude_match_ids)
        transaction.on_commit(
            lambda court_id=court.id, excluded_ids=excluded_ids: promote_one_waiting_match(
                preferred_court_id=court_id,
                exclude_match_ids=excluded_ids,
            )
        )


def _start_locked_match(match: Match, court: Court) -> CourtActivationOutcome:
    """Promote an eligible Match after a Court has been safely claimed."""

    if match.status not in ("pending_verification", "active"):
        raise MatchLifecycleError("This match is not ready to start.")

    if match.status != "active":
        match.status = "active"
        match.start_time = _court_now(court)
        match.waiting_for_court = False
        match.save(update_fields=["status", "start_time", "waiting_for_court", "updated_at"])
    _schedule_match_activated(match.id)
    return CourtActivationOutcome(match_id=match.id, state="activated", court_id=court.id)


def activate_verified_match(match_id: int, *, requested_court_id: int | None = None) -> CourtActivationOutcome:
    """Claim a Court and activate a two-sided verified Match, or queue it safely."""

    with transaction.atomic():
        match = _locked_match(match_id)
        if match.status == "active":
            return CourtActivationOutcome(match_id=match.id, state="already_active", court_id=match.court_id)
        if match.status != "pending_verification":
            raise MatchLifecycleError("This match is not waiting for activation.")

        court = _claim_court_locked(match, requested_court_id=requested_court_id)
        if court is None:
            if not match.waiting_for_court:
                match.waiting_for_court = True
                match.save(update_fields=["waiting_for_court", "updated_at"])
            _schedule_match_state_changed(match.id, match.status)
            return CourtActivationOutcome(match_id=match.id, state="waiting_for_court")
        return _start_locked_match(match, court)


def mark_match_verified(match_id: int) -> None:
    """Move a fully rostered Match into the verified activation state."""

    with transaction.atomic():
        match = _locked_match(match_id)
        if match.status == "pending":
            match.status = "pending_verification"
            match.save(update_fields=["status", "updated_at"])
        elif match.status != "pending_verification":
            raise MatchLifecycleError("This match cannot enter the verified activation state.")


def allocate_ready_matches(match_ids: Iterable[int]) -> list[CourtActivationOutcome]:
    """Allocate a newly frozen Round with one roster of Courts and Matches.

    The whole method is still transactional and locks only the concrete base
    Match/Court rows. Unlike the old loop, it loads the Round's eligible Court
    pools once and uses a deterministic in-memory assignment, then publishes
    activation events only after the short commit.
    """
    ids = list(dict.fromkeys(match_ids))
    if not ids:
        return []
    with transaction.atomic():
        matches = list(
            Match.objects.select_for_update(of=("self",))
            .select_related("tournament", "team1", "team2", "poule")
            .filter(pk__in=ids, status="pending_verification")
            .order_by("created_at", "pk")
        )
        if not matches:
            return []
        tournament_ids = {match.tournament_id for match in matches}
        from tournaments.models import TournamentCourt
        from tournaments.poule_models import Poule

        tournament_courts: dict[int, list[int]] = defaultdict(list)
        for tournament_id, court_id in TournamentCourt.objects.filter(
            tournament_id__in=tournament_ids
        ).values_list("tournament_id", "court_id"):
            tournament_courts[tournament_id].append(court_id)
        poule_courts: dict[int, list[int]] = defaultdict(list)
        poule_ids = {match.poule_id for match in matches if match.poule_id}
        if poule_ids:
            for poule_id, court_id in Poule.courts.through.objects.filter(
                poule_id__in=poule_ids
            ).values_list("poule_id", "court_id"):
                poule_courts[poule_id].append(court_id)

        all_pool_ids = {court_id for values in tournament_courts.values() for court_id in values}
        all_pool_ids.update(court_id for values in poule_courts.values() for court_id in values)
        # Include global-fallback Courts only when a Match has no configured pool.
        has_global_fallback = any(
            not (poule_courts.get(match.poule_id) if match.poule_id else tournament_courts.get(match.tournament_id))
            for match in matches
        )
        court_filter = Q(is_available=True)
        if all_pool_ids and not has_global_fallback:
            court_filter &= Q(pk__in=all_pool_ids)
        courts = list(
            Court.objects.filter(court_filter)
            .select_for_update(skip_locked=True, of=("self",))
            .prefetch_related("courtcomplex_set")
            .order_by("pk")
        )
        live_court_ids = set(
            Match.objects.filter(status__in=LIVE_COURT_STATUSES, court__isnull=False)
            .values_list("court_id", flat=True)
        )
        available_courts = [court for court in courts if court.id not in live_court_ids]
        claimed_court_ids: set[int] = set()
        activated: list[tuple[Match, Court]] = []
        waiting: list[Match] = []
        for match in matches:
            eligible_ids = poule_courts.get(match.poule_id) if match.poule_id else None
            if not eligible_ids:
                eligible_ids = tournament_courts.get(match.tournament_id)
            court = next(
                (
                    candidate for candidate in available_courts
                    if candidate.id not in claimed_court_ids
                    and (not eligible_ids or candidate.id in eligible_ids)
                ),
                None,
            )
            if court is None:
                match.waiting_for_court = True
                waiting.append(match)
                continue
            claimed_court_ids.add(court.id)
            match.court = court
            match.status = "active"
            match.start_time = _court_now(court)
            match.waiting_for_court = False
            activated.append((match, court))

        if activated or waiting:
            Match.objects.bulk_update(
                [match for match, _court in activated] + waiting,
                ["court", "status", "start_time", "waiting_for_court", "updated_at"],
                batch_size=250,
            )
        if claimed_court_ids:
            Court.objects.filter(pk__in=claimed_court_ids).update(is_available=False)
        # A large Round shares one ready/Court transition. Deliver direct page
        # refresh events only; the normal per-player activation path remains
        # available for individual Court hand-offs and legacy callers.
        for match, _court in activated:
            transaction.on_commit(
                lambda match_id=match.id, tournament_id=match.tournament_id: _schedule_round_batch_state_event(
                    match_id, "active", tournament_id
                )
            )
        for match in waiting:
            transaction.on_commit(
                lambda match_id=match.id, tournament_id=match.tournament_id: _schedule_round_batch_state_event(
                    match_id, "pending_verification", tournament_id
                )
            )

        return [
            CourtActivationOutcome(
                match_id=match.id,
                state="activated" if match.id in {item.id for item, _court in activated} else "waiting_for_court",
                court_id=match.court_id,
            )
            for match in matches
        ]


def _schedule_round_batch_state_event(match_id: int, status: str, tournament_id: int) -> None:
    """Finalize activation-side effects, then publish the shared Round event."""
    # Batch Court allocation bypasses _start_locked_match(), so it must
    # explicitly reuse the same persisted starting-side draw before the
    # browser receives the shared ACTIVE event. The helper is idempotent:
    # retries retain the first stored draw.
    if status == "active":
        try:
            from .starting_team import announce_match_starting_team

            match = Match.objects.get(pk=match_id)
            announce_match_starting_team(match)
        except Exception:
            # A presentation/notification-side failure must not suppress the
            # authoritative shared Match state event.
            logger.exception("Batch starting-side draw failed for Match %s", match_id)

    try:
        from pfc_events.signals import notify_match_shared_state_changed

        notify_match_shared_state_changed(
            match_id,
            status,
            tournament_id=tournament_id,
        )
    except Exception:
        logger.exception("Round batch state delivery failed for Match %s", match_id)


def assign_staff_court_and_activate(match_id: int, court_id: int) -> CourtActivationOutcome:
    """Staff-safe Court selection using the same lifecycle claim as players."""

    return activate_verified_match(match_id, requested_court_id=court_id)


def promote_one_waiting_match(
    *,
    preferred_court_id: int | None = None,
    exclude_match_ids: Iterable[int] = (),
) -> CourtActivationOutcome | None:
    """Give one unlocked available Court to the oldest compatible queued Match."""

    with transaction.atomic():
        courts = Court.objects.filter(is_available=True)
        if preferred_court_id is not None:
            courts = courts.filter(pk=preferred_court_id)
        court = courts.select_for_update(skip_locked=True, of=("self",)).order_by("pk").first()
        if court is None:
            return None

        match = _next_waiting_match_for_court_locked(
            court,
            exclude_match_ids=exclude_match_ids,
        )
        if match and _court_is_eligible_for_match(court, match) and not _court_has_other_live_match(court.id, match.id):
            match.court = court
            match.status = "active"
            match.start_time = _court_now(court)
            match.waiting_for_court = False
            match.save(update_fields=["court", "status", "start_time", "waiting_for_court", "updated_at"])
            court.is_available = False
            court.save(update_fields=["is_available"])
            _schedule_match_activated(match.id)
            return CourtActivationOutcome(match_id=match.id, state="activated", court_id=court.id)

        return None


def _release_or_promote_locked(match: Match) -> CourtActivationOutcome | None:
    """Keep a completed Match's historical Court FK and safely hand off play."""

    if not match.court_id:
        return None

    court = Court.objects.select_for_update(of=("self",)).get(pk=match.court_id)
    waiting_match = _next_waiting_match_for_court_locked(court)
    if waiting_match and _court_is_eligible_for_match(court, waiting_match) and not _court_has_other_live_match(court.id, waiting_match.id):
        waiting_match.court = court
        waiting_match.status = "active"
        waiting_match.start_time = _court_now(court)
        waiting_match.waiting_for_court = False
        waiting_match.save(update_fields=["court", "status", "start_time", "waiting_for_court", "updated_at"])
        court.is_available = False
        court.save(update_fields=["is_available"])
        _schedule_match_activated(waiting_match.id)
        return CourtActivationOutcome(match_id=waiting_match.id, state="activated", court_id=court.id)

    _make_court_available_locked(court, promote_waiting=False)
    return None


def submit_official_result(
    match_id: int,
    *,
    submitted_by_id: int,
    team1_score: int,
    team2_score: int,
    photo_evidence=None,
    notes: str | None = None,
) -> ResultOutcome:
    """Persist exactly one submitted official result for an active Match."""

    with transaction.atomic():
        match = _locked_match(match_id)
        if match.status == "waiting_validation":
            return ResultOutcome(match_id=match.id, state="already_submitted")
        if match.status != "active":
            raise MatchLifecycleError("This match is not active.")
        if submitted_by_id not in (match.team1_id, match.team2_id):
            raise MatchLifecycleError("The submitting team is not part of this match.")
        if MatchResult.objects.select_for_update(of=("self",)).filter(match=match).exists():
            return ResultOutcome(match_id=match.id, state="already_submitted")

        MatchResult.objects.create(
            match=match,
            submitted_by_id=submitted_by_id,
            photo_evidence=photo_evidence,
            notes=notes,
        )
        match.team1_score = team1_score
        match.team2_score = team2_score
        match.status = "waiting_validation"
        match.save(update_fields=["team1_score", "team2_score", "status", "updated_at"])

        def deliver() -> None:
            try:
                from .views import _deactivate_match_presence
                from .melee_roster_resolution import players_for_match_team
                from pfc_events.push_notifications import notify_match_action_required
                from pfc_events.signals import notify_match_state_changed

                committed = Match.objects.select_related("team1", "team2").get(pk=match.id)
                notify_match_state_changed(committed.id, committed.status)
                opponent = committed.team2 if submitted_by_id == committed.team1_id else committed.team1
                notify_match_action_required(
                    list(players_for_match_team(committed, opponent)),
                    "result_validation",
                    "match",
                    committed.id,
                )
                _deactivate_match_presence(committed)
            except Exception:
                logger.exception("Post-commit result submission delivery failed for Match %s", match.id)

        transaction.on_commit(deliver)
        return ResultOutcome(match_id=match.id, state="submitted")


def validate_official_result(match_id: int, *, validating_team_id: int, agree: bool) -> ResultOutcome:
    """Accept or reject an official result through one locked state transition."""

    with transaction.atomic():
        match = _locked_match(match_id)
        if match.status != "waiting_validation":
            return ResultOutcome(match_id=match.id, state="not_waiting_validation")
        try:
            result = MatchResult.objects.select_for_update(of=("self",)).get(match=match)
        except MatchResult.DoesNotExist:
            raise MatchLifecycleError("The submitted result no longer exists.")

        if validating_team_id not in (match.team1_id, match.team2_id):
            raise MatchLifecycleError("The validating team is not part of this match.")
        if validating_team_id == result.submitted_by_id:
            raise MatchLifecycleError("The submitting team cannot validate its own result.")

        if not agree:
            result.delete()
            match.status = "active"
            match.team1_score = None
            match.team2_score = None
            match.save(update_fields=["status", "team1_score", "team2_score", "updated_at"])

            def deliver_reopened() -> None:
                try:
                    from .views import auto_register_players_to_billboard
                    from .melee_roster_resolution import players_for_match_team
                    from pfc_events.push_notifications import notify_match_action_required
                    from pfc_events.signals import notify_match_state_changed

                    committed = Match.objects.select_related("team1", "team2").get(pk=match.id)
                    notify_match_state_changed(committed.id, committed.status)
                    notify_match_action_required(
                        list(players_for_match_team(committed, committed.team1))
                        + list(players_for_match_team(committed, committed.team2)),
                        "reopened",
                        "match",
                        committed.id,
                    )
                    auto_register_players_to_billboard(committed)
                except Exception:
                    logger.exception("Post-commit result reopening delivery failed for Match %s", match.id)

            transaction.on_commit(deliver_reopened)
            return ResultOutcome(match_id=match.id, state="reopened")

        now = _court_now(match.court)
        result.validated_by_id = validating_team_id
        result.validated_at = now
        result.save(update_fields=["validated_by", "validated_at"])
        match.status = "completed"
        match.end_time = now
        match.duration = now - match.start_time if match.start_time else None
        if match.team1_score > match.team2_score:
            match.winner_id, match.loser_id = match.team1_id, match.team2_id
        elif match.team2_score > match.team1_score:
            match.winner_id, match.loser_id = match.team2_id, match.team1_id
        else:
            match.winner_id = match.loser_id = None
        match.save(update_fields=[
            "status", "end_time", "duration", "winner", "loser", "updated_at",
        ])
        MatchLifecycleTransition.objects.get_or_create(
            match=match,
            defaults={"tournament_id": match.tournament_id},
        )
        _release_or_promote_locked(match)

        def deliver_completed() -> None:
            try:
                from .views import _deactivate_match_presence
                from match_tracking.services import end_tracking_sessions
                from pfc_events.signals import notify_match_state_changed

                committed = Match.objects.get(pk=match.id)
                notify_match_state_changed(committed.id, committed.status)
                end_tracking_sessions("match", committed.id, "match_completed")
                _deactivate_match_presence(committed)
            except Exception:
                logger.exception("Post-commit completion delivery failed for Match %s", match.id)
            process_tournament_transition(match.id)

        transaction.on_commit(deliver_completed)
        return ResultOutcome(match_id=match.id, state="completed")


def cancel_stale_match(match_id: int) -> ResultOutcome:
    """Cancel an eligible pre-live or live Match without bypassing lifecycle.

    Pending Matches are retained as auditable records.  This transition neither
    creates nor removes MatchResult rows and never invokes Match-completion
    projections.  After commit, its existing Round is checked through the
    authoritative Round transition because a cancelled Match is terminal for
    Round completion only.  A Court handoff is attempted only when this Match
    has a Court FK and no other live Match already owns that Court.
    """

    with transaction.atomic():
        match = _locked_match(match_id)
        cancellable_statuses = (*LIVE_COURT_STATUSES, "pending", "pending_verification")
        if match.status not in cancellable_statuses:
            return ResultOutcome(match_id=match.id, state="not_cancellable")
        match.status = "cancelled"
        match.waiting_for_court = False
        match.save(update_fields=["status", "waiting_for_court", "updated_at"])
        round_id = match.round_id

        if match.court_id:
            court = Court.objects.select_for_update(of=("self",)).get(pk=match.court_id)
            if not _court_has_other_live_match(court.id, match.id):
                _release_or_promote_locked(match)
        _schedule_match_state_changed(match.id, match.status)
        if round_id:
            transaction.on_commit(
                lambda round_id=round_id: process_round_transition(round_id)
            )
        return ResultOutcome(match_id=match.id, state="cancelled")


def release_court_and_requeue_match(match_id: int) -> CourtReleaseOutcome:
    """Release one active Match's Court and return the Match to the queue.

    This is an explicit staff-recovery transition, not a generic edit. It is
    intentionally limited to an active Match: a Match in result validation has
    durable submitted-result evidence and cannot be safely requeued without a
    separate result-resolution decision.
    """

    with transaction.atomic():
        match = _locked_match(match_id)
        if match.status != "active":
            raise MatchLifecycleError(
                "Only an active match may be released and requeued."
            )
        if not match.court_id:
            raise MatchLifecycleError("This active match does not own a court.")

        court = Court.objects.select_for_update(of=("self",)).get(pk=match.court_id)
        if _court_has_other_live_match(court.id, match.id):
            raise MatchLifecycleError(
                "This court has another live match and cannot be reconciled here."
            )

        match.court = None
        match.proposed_court = court
        match.status = "pending_verification"
        match.waiting_for_court = True
        match.start_time = None
        match.save(
            update_fields=[
                "court",
                "proposed_court",
                "status",
                "waiting_for_court",
                "start_time",
                "updated_at",
            ]
        )
        _make_court_available_locked(
            court,
            promote_waiting=True,
            exclude_match_ids=(match.id,),
        )
        _schedule_match_state_changed(match.id, match.status)
        return CourtReleaseOutcome(
            match_id=match.id,
            court_id=court.id,
            state="requeued",
        )


def reconcile_court_occupancy(court_id: int) -> CourtReleaseOutcome:
    """Repair one Court's availability flag from authoritative live ownership.

    A live Match is authoritative.  The denormalized ``Court.is_available``
    flag is adjusted only after both domains are locked, and any subsequent
    queued-Match handoff remains delegated to the regular lifecycle service.
    """

    with transaction.atomic():
        court = Court.objects.select_for_update(of=("self",)).get(pk=court_id)
        live_matches = list(
            Match.objects.select_for_update(of=("self",))
            .filter(court_id=court.id, status__in=LIVE_COURT_STATUSES)
            .order_by("pk")
        )
        if len(live_matches) > 1:
            raise MatchLifecycleError(
                "This court has conflicting live match ownership and requires investigation."
            )
        if live_matches:
            owner = live_matches[0]
            if court.is_available:
                court.is_available = False
                court._lifecycle_skip_auto_promotion = True
                court.save(update_fields=["is_available"])
            return CourtReleaseOutcome(
                match_id=owner.id,
                court_id=court.id,
                state="owned_by_live_match",
            )

        was_orphaned = not court.is_available
        _make_court_available_locked(court, promote_waiting=True)
        return CourtReleaseOutcome(
            match_id=None,
            court_id=court.id,
            state="reconciled_available" if was_orphaned else "already_available",
        )


def complete_match_from_legacy_api(match_id: int, *, team1_score: int, team2_score: int) -> ResultOutcome:
    """Compatibility bridge for the old ``Match.complete_match`` API.

    The only safe legacy interpretation is an explicit staff-style finalization:
    store one official result with the opposing side as validator and route it
    through the same locked completion transition.
    """

    with transaction.atomic():
        match = _locked_match(match_id)
        if match.status == "completed":
            return ResultOutcome(match_id=match.id, state="already_completed")
        if match.status != "active":
            raise MatchLifecycleError("Only active matches may be completed through the legacy API.")
        MatchResult.objects.get_or_create(
            match=match,
            defaults={"submitted_by_id": match.team1_id},
        )
        match.team1_score = team1_score
        match.team2_score = team2_score
        match.status = "waiting_validation"
        match.save(update_fields=["team1_score", "team2_score", "status", "updated_at"])
    return validate_official_result(match_id, validating_team_id=match.team2_id, agree=True)


def process_tournament_transition(match_id: int) -> bool:
    """Run only Match-scoped post-completion projections.

    Round-wide standings, Super Mêlée preparation, successor creation, and
    leaderboard publication are intentionally delegated to
    :func:`process_round_transition`. A normal completed Match therefore never
    takes a Tournament lock or recalculates tournament-wide state.
    """
    try:
        with transaction.atomic():
            transition = (
                MatchLifecycleTransition.objects.select_for_update(of=("self",))
                .select_related("match")
                .get(match_id=match_id)
            )
            if transition.status == MatchLifecycleTransition.COMPLETED:
                return True

            match = _locked_match(match_id)
            transition.status = MatchLifecycleTransition.PROCESSING
            transition.attempts += 1
            transition.last_error = ""
            transition.save(update_fields=["status", "attempts", "last_error", "updated_at"])

            # These projections are bounded to this concrete Match.
            from .models_participant import TeamMatchParticipant
            TeamMatchParticipant.create_from_match_players(match)

            if match.vs_encounter_id:
                from tournaments.vs_utils import update_vs_encounter_points
                update_vs_encounter_points(match.vs_encounter)

            from .rating_integration import update_tournament_match_ratings
            update_tournament_match_ratings(match)

            try:
                from cert_ratings.processor import process_match_cert_ratings
                process_match_cert_ratings(match)
            except Exception:
                logger.exception("Certifying-entity rating projection failed for Match %s", match_id)

            if match.tournament.is_melee:
                from tournaments.melee_stats_updater import update_melee_player_stats_from_match
                update_melee_player_stats_from_match(match)

            transition.status = MatchLifecycleTransition.COMPLETED
            transition.processed_at = timezone.now()
            transition.save(update_fields=["status", "processed_at", "updated_at"])
            round_id = match.round_id

        # This cheap predicate locks only the Round if this was the final Match.
        if round_id:
            process_round_transition(round_id)
        return True
    except Exception as exc:
        logger.exception("Match lifecycle projection failed for Match %s", match_id)
        MatchLifecycleTransition.objects.filter(match_id=match_id).update(
            status=MatchLifecycleTransition.FAILED,
            last_error=str(exc)[:4000],
        )
        return False


def process_round_transition(round_id: int) -> bool:
    """Claim exactly one completed Round transition and publish its successors.

    The completion check is a single indexed ``EXISTS`` query while holding only
    the Round row. Before the last Match arrives it returns immediately. The
    final concurrent Match completion creates/locks one durable Round transition
    record; all expensive tournament-wide work then runs exactly once for that
    Round and remains explicitly retryable after an operational failure.
    """
    from tournaments.models import Round, RoundLifecycleTransition

    try:
        with transaction.atomic():
            round_obj = (
                Round.objects.select_for_update(of=("self",))
                .select_related("tournament")
                .get(pk=round_id)
            )
            unresolved = Match.objects.filter(round_id=round_obj.id).exclude(
                status__in=Match.ROUND_TERMINAL_STATUSES
            ).exists()
            if unresolved:
                return False

            if not round_obj.is_complete:
                round_obj.is_complete = True
                round_obj.save(update_fields=["is_complete"])

            transition, _ = RoundLifecycleTransition.objects.get_or_create(
                round=round_obj,
                defaults={"tournament": round_obj.tournament},
            )
            transition = RoundLifecycleTransition.objects.select_for_update(of=("self",)).get(
                pk=transition.pk
            )
            if transition.status == RoundLifecycleTransition.COMPLETED:
                return True

            transition.status = RoundLifecycleTransition.PROCESSING
            transition.attempts += 1
            transition.last_error = ""
            transition.save(update_fields=["status", "attempts", "last_error", "updated_at"])
            tournament = round_obj.tournament

            # Swiss/Buchholz is a Round publication, never a Match completion
            # side effect. The rewritten ranking service loads all needed data
            # in batches.
            from leaderboards.swiss_ranking import (
                calculate_buchholz_scores,
                is_swiss_tournament,
                update_all_swiss_points,
            )
            if is_swiss_tournament(tournament):
                update_all_swiss_points(tournament)
                calculate_buchholz_scores(tournament)

            if tournament.is_melee and tournament.shuffle_players_after_round:
                from tournaments.shuffle_utils import prepare_automatic_super_melee_transition
                prepared = prepare_automatic_super_melee_transition(
                    tournament=tournament,
                    completed_round=round_obj,
                )
                if not prepared["success"]:
                    raise MatchLifecycleError(prepared["message"])

            # Existing algorithm-specific progression remains intact but is run
            # once, after all results in this Round are durable.
            if tournament.format == "knockout":
                tournament.check_and_advance_knockout_round()
            else:
                from tournaments.automation_engine import TournamentEngine
                if not TournamentEngine(tournament).process_automation():
                    raise MatchLifecycleError("Tournament automation did not complete; the Round transition is retryable.")

            # Publication is write-only here; all public GET paths are readers.
            from leaderboards.views import publish_tournament_leaderboard
            publish_tournament_leaderboard(tournament)

            tournament.refresh_from_db(fields=["automation_status"])
            if tournament.automation_status == "completed":
                from tournaments.player_history import record_finalized_tournament_history
                record_finalized_tournament_history(
                    tournament,
                    include_melee_awards=tournament.is_melee,
                )

            transition.status = RoundLifecycleTransition.COMPLETED
            transition.processed_at = timezone.now()
            transition.save(update_fields=["status", "processed_at", "updated_at"])
            return True
    except Exception as exc:
        logger.exception("Round lifecycle transition failed for Round %s", round_id)
        RoundLifecycleTransition.objects.filter(round_id=round_id).update(
            status=RoundLifecycleTransition.FAILED,
            last_error=str(exc)[:4000],
        )
        return False


def retry_failed_tournament_transitions(*, tournament_id: int | None = None) -> int:
    """Explicitly retry failed Match projections and Round transitions."""
    transitions = MatchLifecycleTransition.objects.filter(
        status__in=(MatchLifecycleTransition.PENDING, MatchLifecycleTransition.FAILED)
    )
    if tournament_id is not None:
        transitions = transitions.filter(tournament_id=tournament_id)
    succeeded = 0
    for match_id in transitions.order_by("created_at").values_list("match_id", flat=True):
        succeeded += int(process_tournament_transition(match_id))

    from tournaments.models import RoundLifecycleTransition
    round_transitions = RoundLifecycleTransition.objects.filter(
        status__in=(RoundLifecycleTransition.PENDING, RoundLifecycleTransition.FAILED)
    )
    if tournament_id is not None:
        round_transitions = round_transitions.filter(tournament_id=tournament_id)
    for round_id in round_transitions.order_by("created_at").values_list("round_id", flat=True):
        succeeded += int(process_round_transition(round_id))
    return succeeded
