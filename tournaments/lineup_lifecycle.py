"""Server-owned Tournament Round lineup windows.

Tournament Matches use the existing MatchPlayer snapshot as their editable lineup
store. The current Round is the only timer owner: one persisted deadline opens
all of its Match lineup forms, and one idempotent database finalization freezes
those snapshots before Court allocation. Friendly Games never call this module.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Iterable

from django.db import transaction
from django.utils import timezone

from matches.models import Match, MatchPlayer
from matches.utils import detect_match_type, validate_match_type
from tournaments.models import Round

logger = logging.getLogger(__name__)


class LineupLifecycleError(Exception):
    """A stable error for an invalid or closed Tournament lineup window."""


@dataclass(frozen=True)
class LineupFreezeOutcome:
    round_id: int
    frozen: bool
    ready_match_ids: tuple[int, ...]
    blocked_match_ids: tuple[int, ...]


def _required_player_count(tournament) -> int | None:
    """Reuse the existing activation form's only safe auto-selection rule."""
    allowed = (tournament.allowed_match_types or {}).get("allowed_match_types", [])
    if len(allowed) == 1:
        return {"tete_a_tete": 1, "doublet": 2, "triplet": 3}.get(allowed[0])
    if not allowed:
        if tournament.has_tete_a_tete and not tournament.has_doublets and not tournament.has_triplets:
            return 1
        if tournament.has_doublets and not tournament.has_triplets:
            return 2
        if tournament.has_triplets and not tournament.has_doublets:
            return 3
        if tournament.is_melee:
            return {"tete_a_tete": 1, "doublets": 2, "triplets": 3}.get(tournament.melee_format)
    return None


def _candidate_players(match: Match, team):
    """Return the immutable side roster, not the latest editable selection.

    ``MatchPlayer`` is the saved lineup snapshot. Once a side edits it, using
    the general Match resolver would make omitted players disappear from the
    next edit form. Mêlée uses its exact Round assignment; ordinary and VS
    Tournament Teams retain the established Team roster source during the
    short lineup window.
    """
    if match.tournament.is_melee and match.round_id:
        from tournaments.melee_roster import MeleeRoundRosterService

        return list(
            MeleeRoundRosterService.players_for_team(
                tournament=match.tournament,
                round=match.round,
                team=team,
            ).select_related("profile").order_by("id")
        )
    return list(team.players.select_related("profile").order_by("id"))


def _default_role(player) -> str:
    try:
        return player.profile.preferred_position or "milieu"
    except Exception:
        return "milieu"


def _existing_lineup(match: Match, team):
    return list(
        MatchPlayer.objects.filter(match=match, team=team)
        .select_related("player")
        .order_by("player_id")
    )


def _materialize_safe_default_lineup(match: Match, team) -> list[MatchPlayer]:
    """Materialize a default only when PFC's existing rule is unambiguous."""
    existing = _existing_lineup(match, team)
    if existing:
        return existing

    required = _required_player_count(match.tournament)
    candidates = _candidate_players(match, team)
    if required is None or len(candidates) != required:
        return []

    MatchPlayer.objects.bulk_create(
        [
            MatchPlayer(match=match, team=team, player=player, role=_default_role(player))
            for player in candidates
        ]
    )
    return _existing_lineup(match, team)


def _lineups_are_valid(match: Match) -> tuple[bool, str | None]:
    # Prove *both* missing sides have a safe automatic selection before
    # materializing either one. A deadline must not leave a half-created lineup
    # simply because the opposing side cannot be inferred safely.
    required = _required_player_count(match.tournament)
    team1_existing = _existing_lineup(match, match.team1)
    team2_existing = _existing_lineup(match, match.team2)
    for team, existing in ((match.team1, team1_existing), (match.team2, team2_existing)):
        if existing and required is not None and len(existing) != required:
            return False, "A submitted lineup has the wrong number of players."
        if not existing and (
            required is None or len(_candidate_players(match, team)) != required
        ):
            return False, "A side has no safe default lineup."

    team1_rows = team1_existing or _materialize_safe_default_lineup(match, match.team1)
    team2_rows = team2_existing or _materialize_safe_default_lineup(match, match.team2)
    if not team1_rows or not team2_rows:
        return False, "A side has no safe default lineup."

    match_type, count1, count2 = detect_match_type(
        [row.player for row in team1_rows],
        [row.player for row in team2_rows],
    )
    is_valid, message = validate_match_type(match_type, count1, count2, match.tournament)
    if not is_valid:
        return False, message

    match.match_type = match_type
    match.team1_player_count = count1
    match.team2_player_count = count2
    match.save(update_fields=["match_type", "team1_player_count", "team2_player_count", "updated_at"])
    MatchPlayer.objects.filter(match=match).update(match_format=match_type)
    return True, None


def open_round_lineup_window(round_id: int) -> Round:
    """Persist exactly one deadline for every newly generated Tournament Round."""
    with transaction.atomic():
        round_obj = (
            Round.objects.select_for_update(of=("self",))
            .select_related("tournament")
            .get(pk=round_id)
        )
        if round_obj.lineup_deadline_at is None:
            round_obj.lineup_deadline_at = timezone.now() + timedelta(
                seconds=round_obj.tournament.lineup_selection_seconds
            )
            round_obj.save(update_fields=["lineup_deadline_at"])
        return round_obj


def save_match_lineup(
    *,
    match_id: int,
    acting_team_id: int,
    player_ids: Iterable[int],
    roles_by_player_id: dict[int, str],
) -> None:
    """Save one side's latest valid selection while its Round window is open."""
    requested_ids = {int(player_id) for player_id in player_ids}
    with transaction.atomic():
        match = (
            Match.objects.select_for_update(of=("self",))
            .select_related("tournament", "round", "team1", "team2")
            .get(pk=match_id)
        )
        if match.round_id is None:
            raise LineupLifecycleError("This Match does not use a Round lineup window.")
        if acting_team_id not in (match.team1_id, match.team2_id):
            raise LineupLifecycleError("This team is not part of the Match.")
        round_obj = Round.objects.select_for_update(of=("self",)).get(pk=match.round_id)
        if round_obj.lineups_frozen_at is not None or (
            round_obj.lineup_deadline_at is not None and timezone.now() >= round_obj.lineup_deadline_at
        ):
            raise LineupLifecycleError("The lineup selection window has closed.")
        if match.status != "pending":
            raise LineupLifecycleError("This Match lineup can no longer be edited.")

        team = match.team1 if acting_team_id == match.team1_id else match.team2
        candidates = {player.id: player for player in _candidate_players(match, team)}
        if not requested_ids or not requested_ids.issubset(candidates):
            raise LineupLifecycleError("Select only players assigned to this Match side.")

        required = _required_player_count(match.tournament)
        if required is not None and len(requested_ids) != required:
            raise LineupLifecycleError(f"This Match requires exactly {required} player(s) for this side.")

        allowed_roles = {choice for choice, _label in MatchPlayer.ROLE_CHOICES}
        MatchPlayer.objects.filter(match=match, team=team).delete()
        rows = []
        for player_id in sorted(requested_ids):
            player = candidates[player_id]
            role = roles_by_player_id.get(player_id, _default_role(player))
            rows.append(MatchPlayer(
                match=match,
                team=team,
                player=player,
                role=role if role in allowed_roles else "flex",
            ))
        MatchPlayer.objects.bulk_create(rows)


def _batch_candidate_players(matches: list[Match]):
    """Load every immutable side roster needed by one Round in bounded queries."""
    from teams.models import Player

    candidates: dict[tuple[int, int], list] = {}
    normal_matches = [match for match in matches if not match.tournament.is_melee]
    normal_team_ids = {
        team_id
        for match in normal_matches
        for team_id in (match.team1_id, match.team2_id)
    }
    if normal_team_ids:
        by_team: dict[int, list] = {team_id: [] for team_id in normal_team_ids}
        for player in Player.objects.filter(team_id__in=normal_team_ids).select_related("profile").order_by("id"):
            by_team[player.team_id].append(player)
        for match in normal_matches:
            candidates[(match.id, match.team1_id)] = by_team.get(match.team1_id, [])
            candidates[(match.id, match.team2_id)] = by_team.get(match.team2_id, [])

    # Mêlée's immutable P4 roster is assignment-scoped rather than Team.players.
    melee_matches = [match for match in matches if match.tournament.is_melee]
    if melee_matches:
        from tournaments.models import MeleeRoundAssignment

        keys = {(match.tournament_id, match.round_id, team_id)
                for match in melee_matches
                for team_id in (match.team1_id, match.team2_id)}
        by_key = {key: [] for key in keys}
        assignment_rows = MeleeRoundAssignment.objects.filter(
            round_id__in={match.round_id for match in melee_matches},
            state=MeleeRoundAssignment.ASSIGNED,
        ).select_related("player__profile").order_by("player_id")
        for assignment in assignment_rows:
            key = (assignment.tournament_id, assignment.round_id, assignment.team_id)
            if key in by_key:
                by_key[key].append(assignment.player)
        for match in melee_matches:
            candidates[(match.id, match.team1_id)] = by_key.get(
                (match.tournament_id, match.round_id, match.team1_id), []
            )
            candidates[(match.id, match.team2_id)] = by_key.get(
                (match.tournament_id, match.round_id, match.team2_id), []
            )
    return candidates


def finalize_round_lineups(round_id: int) -> LineupFreezeOutcome:
    """Freeze one due Round with one bounded roster/materialization batch.

    The deadline either validates every pending Match and advances the complete
    Round to the Court queue, or leaves the entire Round editable for staff
    correction. It never activates a partial subset merely because another
    Match lacks a safe default.
    """
    with transaction.atomic():
        round_obj = (
            Round.objects.select_for_update(of=("self",))
            .select_related("tournament")
            .get(pk=round_id)
        )
        if round_obj.lineups_frozen_at is not None:
            return LineupFreezeOutcome(round_obj.id, True, (), ())
        if round_obj.lineup_deadline_at is None or round_obj.lineup_deadline_at > timezone.now():
            return LineupFreezeOutcome(round_obj.id, False, (), ())

        matches = list(
            Match.objects.select_for_update(of=("self",))
            .select_related("team1", "team2", "tournament")
            .filter(round=round_obj, status="pending")
            .order_by("id")
        )
        if not matches:
            round_obj.lineups_frozen_at = timezone.now()
            round_obj.save(update_fields=["lineups_frozen_at"])
            return LineupFreezeOutcome(round_obj.id, True, (), ())

        existing_by_side: dict[tuple[int, int], list[MatchPlayer]] = {}
        for row in MatchPlayer.objects.filter(match_id__in=[match.id for match in matches]).select_related("player"):
            existing_by_side.setdefault((row.match_id, row.team_id), []).append(row)
        candidates = _batch_candidate_players(matches)

        blocked_ids: list[int] = []
        planned_rows: list[MatchPlayer] = []
        planned_matches: list[Match] = []
        match_formats: dict[int, str] = {}
        for match in matches:
            required = _required_player_count(match.tournament)
            side_rows = {}
            for team in (match.team1, match.team2):
                key = (match.id, team.id)
                existing = existing_by_side.get(key, [])
                if existing:
                    if required is not None and len(existing) != required:
                        blocked_ids.append(match.id)
                        break
                    side_rows[team.id] = existing
                    continue
                side_candidates = candidates.get(key, [])
                if required is None or len(side_candidates) != required:
                    blocked_ids.append(match.id)
                    break
                rows = [
                    MatchPlayer(
                        match=match,
                        team=team,
                        player=player,
                        role=_default_role(player),
                    )
                    for player in side_candidates
                ]
                planned_rows.extend(rows)
                side_rows[team.id] = rows
            if match.id in blocked_ids:
                logger.warning("Round %s Match %s has no valid default lineup", round_obj.id, match.id)
                continue
            match_type, count1, count2 = detect_match_type(
                [row.player for row in side_rows[match.team1_id]],
                [row.player for row in side_rows[match.team2_id]],
            )
            is_valid, reason = validate_match_type(match_type, count1, count2, match.tournament)
            if not is_valid:
                logger.warning("Round %s Match %s has invalid lineup: %s", round_obj.id, match.id, reason)
                blocked_ids.append(match.id)
                continue
            match.match_type = match_type
            match.team1_player_count = count1
            match.team2_player_count = count2
            match.status = "pending_verification"
            planned_matches.append(match)
            match_formats[match.id] = match_type

        if blocked_ids:
            return LineupFreezeOutcome(round_obj.id, False, (), tuple(sorted(set(blocked_ids))))

        if planned_rows:
            MatchPlayer.objects.bulk_create(planned_rows, batch_size=250)
        if planned_matches:
            Match.objects.bulk_update(
                planned_matches,
                ["match_type", "team1_player_count", "team2_player_count", "status", "updated_at"],
                batch_size=250,
            )
            # ``match_format`` is a denormalized display field for both saved
            # selections and materialized defaults; one query handles the Round.
            for match_type in set(match_formats.values()):
                MatchPlayer.objects.filter(
                    match_id__in=[match_id for match_id, value in match_formats.items() if value == match_type]
                ).update(match_format=match_type)

        round_obj.lineups_frozen_at = timezone.now()
        round_obj.save(update_fields=["lineups_frozen_at"])
        ready_ids = tuple(match.id for match in planned_matches)

    if ready_ids:
        from matches.lifecycle import allocate_ready_matches
        allocate_ready_matches(ready_ids)
    return LineupFreezeOutcome(round_id, True, ready_ids, ())


def finalize_due_lineup_windows(*, limit: int = 100) -> list[LineupFreezeOutcome]:
    """Finalize expired Round windows with bounded database-backed discovery."""
    due_ids = list(
        Round.objects.filter(
            lineup_deadline_at__lte=timezone.now(),
            lineups_frozen_at__isnull=True,
        )
        .order_by("lineup_deadline_at", "id")
        .values_list("id", flat=True)[:limit]
    )
    return [finalize_round_lineups(round_id) for round_id in due_ids]
