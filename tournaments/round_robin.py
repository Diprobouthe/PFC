"""Deterministic, Round-scoped Round Robin scheduling.

A persisted :class:`tournaments.models.Round` is one real playing round.  This
module owns the deterministic circle-method schedule and materializes only the
requested Round.  Court availability is intentionally outside this module:
new Matches enter the existing Round lineup/court allocation lifecycle after
their logical Round has been created.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from django.db import transaction

from matches.models import Match

from .models import Round, Tournament, TournamentTeam


class RoundRobinConfigurationError(ValueError):
    """Raised when a Round Robin configuration cannot form a valid schedule."""


@dataclass(frozen=True)
class RoundRobinRound:
    """One deterministic playing round of TournamentTeam pairings."""

    pairs: tuple[tuple[TournamentTeam, TournamentTeam], ...]


@dataclass(frozen=True)
class MaterializedRoundRobinRound:
    """The durable result of materializing one logical Round Robin round."""

    round: Round
    match_count: int
    created_matches: bool


def stable_stage_participants(stage) -> list[TournamentTeam]:
    """Return the immutable scheduling order for a Stage's active entrants.

    TournamentTeam primary keys and Team primary keys do not change when
    standings do.  They are therefore safe circle-method inputs, unlike Swiss
    ranking order, which intentionally changes after every completed round.
    """

    return list(
        TournamentTeam.objects.filter(
            tournament=stage.tournament,
            current_stage_number=stage.stage_number,
            is_active=True,
        )
        .select_related("team", "team__parent_team")
        .order_by("team_id", "pk")
    )


def _circle_rounds(teams: Sequence[TournamentTeam]) -> list[RoundRobinRound]:
    """Build the complete, deterministic circle-method schedule.

    With an odd number of Teams a ``None`` dummy is inserted.  Pairings against
    that dummy are BYEs and therefore do not create Match rows.  Every real
    Team occurs at most once in each returned playing round.
    """

    rotation: list[TournamentTeam | None] = list(teams)
    if len(rotation) < 2:
        return []
    if len(rotation) % 2:
        rotation.append(None)

    rounds: list[RoundRobinRound] = []
    for _round_index in range(len(rotation) - 1):
        pairs: list[tuple[TournamentTeam, TournamentTeam]] = []
        for index in range(len(rotation) // 2):
            first = rotation[index]
            second = rotation[-1 - index]
            if first is not None and second is not None:
                pairs.append((first, second))
        rounds.append(RoundRobinRound(pairs=tuple(pairs)))
        rotation = [rotation[0], rotation[-1], *rotation[1:-1]]
    return rounds


def _pairing_penalty(first: TournamentTeam, second: TournamentTeam) -> int:
    """Prefer unrelated subteams when that does not change RR guarantees."""

    first_parent = first.team.parent_team_id or first.team_id
    second_parent = second.team.parent_team_id or second.team_id
    return int(first_parent == second_parent)


def _partial_even_schedule(
    full_schedule: Sequence[RoundRobinRound],
    matches_per_team: int,
) -> list[RoundRobinRound]:
    """Select whole circle rounds for an even-sized partial Round Robin."""

    clean = [
        playing_round
        for playing_round in full_schedule
        if not any(_pairing_penalty(first, second) for first, second in playing_round.pairs)
    ]
    selected = clean[:matches_per_team]
    if len(selected) < matches_per_team:
        selected_ids = {id(playing_round) for playing_round in selected}
        selected.extend(
            playing_round
            for playing_round in full_schedule
            if id(playing_round) not in selected_ids
        )
    return selected[:matches_per_team]


def _partial_odd_schedule(
    teams: Sequence[TournamentTeam],
    full_schedule: Sequence[RoundRobinRound],
    matches_per_team: int,
) -> list[RoundRobinRound]:
    """Build an exact regular partial schedule for an odd-sized entrant set.

    An odd number of Teams can have an exact N-match-per-Team schedule only for
    even N.  Selecting N full circle rounds would give different Teams a BYE,
    so select deterministic distance cycles instead and retain their native
    circle-method playing slots.  Each retained slot is still a matching.
    """

    if matches_per_team % 2:
        raise RoundRobinConfigurationError(
            "An odd number of teams requires an even matches-per-team value for an exact partial Round Robin."
        )

    team_ids = [team.team_id for team in teams]
    index_by_team_id = {team_id: index for index, team_id in enumerate(team_ids)}
    team_by_id = {team.team_id: team for team in teams}
    distances = range(1, len(teams) // 2 + 1)
    distance_penalties: list[tuple[int, int]] = []
    for distance in distances:
        penalty = sum(
            _pairing_penalty(
                team_by_id[team_ids[index]],
                team_by_id[team_ids[(index + distance) % len(teams)]],
            )
            for index in range(len(teams))
        )
        distance_penalties.append((penalty, distance))

    selected_distances = [
        distance
        for _penalty, distance in sorted(distance_penalties)[: matches_per_team // 2]
    ]
    selected_pairs = {
        frozenset((team_ids[index], team_ids[(index + distance) % len(teams)]))
        for distance in selected_distances
        for index in range(len(teams))
    }

    schedule: list[RoundRobinRound] = []
    for playing_round in full_schedule:
        pairs = tuple(
            (first, second)
            for first, second in playing_round.pairs
            if frozenset((first.team_id, second.team_id)) in selected_pairs
        )
        if pairs:
            schedule.append(RoundRobinRound(pairs=pairs))

    expected_pair_count = len(teams) * matches_per_team // 2
    actual_pair_count = sum(len(playing_round.pairs) for playing_round in schedule)
    if actual_pair_count != expected_pair_count:
        raise RoundRobinConfigurationError(
            "The partial Round Robin schedule did not preserve the configured match total."
        )
    return schedule


def round_robin_schedule(
    teams: Sequence[TournamentTeam],
    *,
    matches_per_team: int | None = None,
) -> list[RoundRobinRound]:
    """Return every logical playing round for this stable entrant set.

    ``None`` means a full Round Robin.  A configured value means an exact
    partial schedule: every Team receives that many Matches when the requested
    degree sequence is mathematically possible.
    """

    stable_teams = list(teams)
    team_count = len(stable_teams)
    if team_count < 2:
        return []

    full_schedule = _circle_rounds(stable_teams)
    if matches_per_team is None:
        return full_schedule

    if matches_per_team < 1 or matches_per_team >= team_count:
        raise RoundRobinConfigurationError(
            "Partial Round Robin matches per team must be between 1 and the number of teams minus 1."
        )
    if (team_count * matches_per_team) % 2:
        raise RoundRobinConfigurationError(
            "The requested partial Round Robin has an odd total team-match count."
        )

    if team_count % 2 == 0:
        return _partial_even_schedule(full_schedule, matches_per_team)
    return _partial_odd_schedule(stable_teams, full_schedule, matches_per_team)


def synchronize_round_robin_stage_length(stage, teams: Sequence[TournamentTeam]) -> list[RoundRobinRound]:
    """Persist the derived number of real playing rounds for one RR Stage."""

    schedule = round_robin_schedule(
        teams,
        matches_per_team=stage.num_matches_per_team,
    )
    if not schedule:
        raise RoundRobinConfigurationError("At least two active teams are required for Round Robin.")
    if stage.num_rounds_in_stage != len(schedule):
        stage.num_rounds_in_stage = len(schedule)
        stage.save(update_fields=["num_rounds_in_stage"])
    return schedule


def _next_overall_round_number(tournament: Tournament) -> int:
    latest = Round.objects.filter(tournament=tournament).order_by("-number").first()
    return (latest.number + 1) if latest else 1


def materialize_round_robin_round(
    *,
    tournament: Tournament,
    stage,
    teams: Iterable[TournamentTeam] | None,
    round_number: int,
) -> MaterializedRoundRobinRound:
    """Create exactly one requested Round and its scheduled Match rows.

    The Tournament row is locked even for initial/manual generation.  Existing
    Match rows make the call idempotent; it never deletes or regenerates an
    already materialized Round.
    """

    with transaction.atomic():
        locked_tournament = Tournament.objects.select_for_update(of=("self",)).get(
            pk=tournament.pk
        )
        locked_stage = None
        if stage is not None:
            locked_stage = type(stage).objects.select_for_update(of=("self",)).get(
                pk=stage.pk
            )
            stable_teams = stable_stage_participants(locked_stage)
            schedule = synchronize_round_robin_stage_length(locked_stage, stable_teams)
        else:
            stable_teams = list(teams or [])
            schedule = round_robin_schedule(stable_teams)

        if round_number < 1 or round_number > len(schedule):
            raise RoundRobinConfigurationError(
                f"Round Robin round {round_number} is outside the configured schedule."
            )

        round_obj, _round_created = Round.objects.get_or_create(
            tournament=locked_tournament,
            stage=locked_stage,
            number_in_stage=round_number,
            defaults={
                "number": _next_overall_round_number(locked_tournament),
                "name": f"Round {round_number}",
                "is_complete": False,
            },
        )
        existing_count = Match.objects.filter(
            tournament=locked_tournament,
            round=round_obj,
        ).count()
        if existing_count:
            return MaterializedRoundRobinRound(
                round=round_obj,
                match_count=existing_count,
                created_matches=False,
            )

        pairs = schedule[round_number - 1].pairs
        for first, second in pairs:
            Match.objects.create(
                tournament=locked_tournament,
                stage=locked_stage,
                round=round_obj,
                team1=first.team,
                team2=second.team,
                status="pending",
                time_limit_minutes=locked_tournament.default_time_limit_minutes,
            )
            first.opponents_played.add(second.team)
            second.opponents_played.add(first.team)

        return MaterializedRoundRobinRound(
            round=round_obj,
            match_count=len(pairs),
            created_matches=True,
        )
