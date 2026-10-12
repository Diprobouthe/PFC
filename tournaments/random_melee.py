"""Random Super Melee roster planning with teammate-diversity priority.

This module is intentionally scoped to the canonical random algorithm.
Snake Draft doubles owns a separate winner/loser planner and must not pass
through this code.

The Random goal is:
1. keep complete team sizes,
2. rotate unavoidable unassigned remainders fairly,
3. avoid repeated teammate pairs whenever a zero-repeat roster exists,
4. otherwise minimise repeated partnerships, and
5. retain randomness among equally good solutions.
"""

from __future__ import annotations

from collections import Counter
from itertools import combinations
import random as _random

from tournaments.models import MeleeRoundAssignment
from tournaments.partnership_models import MeleePartnership


ZERO_REPEAT_NODE_LIMIT = 250_000
HEURISTIC_RESTARTS = 192


def _team_size(tournament):
    if tournament.melee_format == "tete_a_tete":
        return 1
    if tournament.melee_format == "triplets":
        return 3
    return 2


def _partnership_counts(tournament):
    counts = Counter()
    for first_player_id, second_player_id in MeleePartnership.objects.filter(
        tournament=tournament,
    ).values_list("player1_id", "player2_id"):
        counts[tuple(sorted((first_player_id, second_player_id)))] += 1
    return counts


def _missed_round_counts(tournament):
    counts = Counter()
    for player_id in MeleeRoundAssignment.objects.filter(
        tournament=tournament,
        state__in=(
            MeleeRoundAssignment.WAITLISTED,
            MeleeRoundAssignment.BYE,
        ),
    ).values_list("player_id", flat=True):
        counts[player_id] += 1
    return counts


def _previous_nonplaying_ids(tournament, completed_round):
    if completed_round is None:
        return set()
    return set(
        MeleeRoundAssignment.objects.filter(
            tournament=tournament,
            round=completed_round,
            state__in=(
                MeleeRoundAssignment.WAITLISTED,
                MeleeRoundAssignment.BYE,
            ),
        ).values_list("player_id", flat=True)
    )


def _choose_fair_sitouts(
    *,
    player_ids,
    sitout_count,
    missed_counts,
    previous_nonplaying_ids,
    rng,
):
    if sitout_count <= 0:
        return set()
    if sitout_count >= len(player_ids):
        return set(player_ids)

    candidates = list(combinations(sorted(player_ids), sitout_count))
    rng.shuffle(candidates)

    best_key = None
    best = None
    for recipient_ids in candidates:
        recipient_ids = set(recipient_ids)
        after = [
            missed_counts[player_id] + (1 if player_id in recipient_ids else 0)
            for player_id in player_ids
        ]
        key = (
            max(after) - min(after),
            sum(value * value for value in after),
            sum(player_id in previous_nonplaying_ids for player_id in recipient_ids),
            sum(missed_counts[player_id] for player_id in recipient_ids),
        )
        if best_key is None or key < best_key:
            best_key = key
            best = recipient_ids
    return set(best or ())


def _group_pair_keys(group):
    return [
        tuple(sorted(pair))
        for pair in combinations(group, 2)
    ]


def _group_cost(group, partnership_counts):
    counts = [partnership_counts[pair] for pair in _group_pair_keys(group)]
    return (
        sum(count > 0 for count in counts),
        sum(counts),
        max(counts, default=0),
    )


def _partition_score(groups, partnership_counts):
    repeated_pairs = 0
    weighted_repeats = 0
    max_pair_history = 0
    per_player_repeat_load = Counter()

    for group in groups:
        for first_player_id, second_player_id in combinations(group, 2):
            pair = tuple(sorted((first_player_id, second_player_id)))
            count = partnership_counts[pair]
            if count:
                repeated_pairs += 1
                weighted_repeats += count
                max_pair_history = max(max_pair_history, count)
                per_player_repeat_load[first_player_id] += count
                per_player_repeat_load[second_player_id] += count

    return (
        repeated_pairs,
        weighted_repeats,
        max_pair_history,
        max(per_player_repeat_load.values(), default=0),
    )


def _zero_repeat_partition(
    *,
    player_ids,
    team_size,
    partnership_counts,
    rng,
    node_limit=ZERO_REPEAT_NODE_LIMIT,
):
    """Find a zero-repeat partition by bounded exact backtracking."""
    if team_size == 1:
        return [(player_id,) for player_id in player_ids]

    nodes = 0

    def compatible(group):
        return all(
            partnership_counts[tuple(sorted(pair))] == 0
            for pair in combinations(group, 2)
        )

    def candidate_groups_for_pivot(pivot, remaining):
        others = [player_id for player_id in remaining if player_id != pivot]
        groups = []
        for partners in combinations(others, team_size - 1):
            group = (pivot, *partners)
            if compatible(group):
                groups.append(group)
        rng.shuffle(groups)
        return groups

    def search(remaining):
        nonlocal nodes
        nodes += 1
        if nodes > node_limit:
            return None
        if not remaining:
            return []

        pivots = list(remaining)
        rng.shuffle(pivots)
        pivot_options = []
        for pivot in pivots:
            groups = candidate_groups_for_pivot(pivot, remaining)
            if not groups:
                return None
            pivot_options.append((len(groups), pivot, groups))
        _, _pivot, groups = min(pivot_options, key=lambda item: item[0])

        for group in groups:
            next_remaining = tuple(
                player_id
                for player_id in remaining
                if player_id not in group
            )
            result = search(next_remaining)
            if result is not None:
                return [tuple(group), *result]
        return None

    player_ids = tuple(player_ids)
    if len(player_ids) % team_size:
        return None
    return search(player_ids)


def _greedy_partition(*, player_ids, team_size, partnership_counts, rng):
    """Build one low-repeat complete partition with random tie-breaking."""
    remaining = list(player_ids)
    groups = []

    while remaining:
        rng.shuffle(remaining)

        def clean_option_count(player_id):
            others = [candidate for candidate in remaining if candidate != player_id]
            count = 0
            for partners in combinations(others, team_size - 1):
                if _group_cost((player_id, *partners), partnership_counts)[0] == 0:
                    count += 1
            return count

        pivot = min(remaining, key=clean_option_count)
        others = [candidate for candidate in remaining if candidate != pivot]
        candidates = list(combinations(others, team_size - 1))
        rng.shuffle(candidates)
        best_cost = None
        best_partners = None
        for partners in candidates:
            cost = _group_cost((pivot, *partners), partnership_counts)
            if best_cost is None or cost < best_cost:
                best_cost = cost
                best_partners = partners

        group = (pivot, *best_partners)
        groups.append(group)
        used = set(group)
        remaining = [player_id for player_id in remaining if player_id not in used]

    return groups


def _improve_by_swaps(groups, partnership_counts, rng):
    """Swap Players between Teams whenever the full partition score improves."""
    groups = [list(group) for group in groups]
    current_score = _partition_score(groups, partnership_counts)

    improved = True
    while improved:
        improved = False
        swaps = []
        for first_group_index in range(len(groups)):
            for second_group_index in range(first_group_index + 1, len(groups)):
                for first_slot in range(len(groups[first_group_index])):
                    for second_slot in range(len(groups[second_group_index])):
                        swaps.append(
                            (
                                first_group_index,
                                second_group_index,
                                first_slot,
                                second_slot,
                            )
                        )
        rng.shuffle(swaps)

        best_score = current_score
        best_swap = None
        for first_group_index, second_group_index, first_slot, second_slot in swaps:
            candidate = [list(group) for group in groups]
            (
                candidate[first_group_index][first_slot],
                candidate[second_group_index][second_slot],
            ) = (
                candidate[second_group_index][second_slot],
                candidate[first_group_index][first_slot],
            )
            score = _partition_score(candidate, partnership_counts)
            if score < best_score:
                best_score = score
                best_swap = (
                    first_group_index,
                    second_group_index,
                    first_slot,
                    second_slot,
                )

        if best_swap is not None:
            first_group_index, second_group_index, first_slot, second_slot = best_swap
            (
                groups[first_group_index][first_slot],
                groups[second_group_index][second_slot],
            ) = (
                groups[second_group_index][second_slot],
                groups[first_group_index][first_slot],
            )
            current_score = best_score
            improved = True

    return [tuple(group) for group in groups]


def _best_effort_partition(
    *,
    player_ids,
    team_size,
    partnership_counts,
    rng,
):
    best_groups = None
    best_score = None

    for _ in range(HEURISTIC_RESTARTS):
        groups = _greedy_partition(
            player_ids=player_ids,
            team_size=team_size,
            partnership_counts=partnership_counts,
            rng=rng,
        )
        groups = _improve_by_swaps(groups, partnership_counts, rng)
        score = _partition_score(groups, partnership_counts)
        if best_score is None or score < best_score:
            best_groups = groups
            best_score = score
        elif score == best_score and rng.random() < 0.5:
            best_groups = groups

        if best_score and best_score[0] == 0:
            break

    return best_groups, best_score


def build_random_diversity_plan(
    *,
    tournament,
    melee_players,
    teams,
    completed_round=None,
    rng=None,
):
    """Return a complete Random assignment plan with teammate-diversity priority."""
    rng = rng or _random
    team_size = _team_size(tournament)
    player_ids = [melee_player.player_id for melee_player in melee_players]
    if not player_ids:
        return {
            "success": False,
            "message": "No players are registered for Random Super Melee.",
        }

    required_team_count = (
        len(player_ids)
        if team_size == 1
        else len(player_ids) // team_size
    )
    if len(teams) != required_team_count:
        return {
            "success": False,
            "message": (
                "Random Super Melee requires exactly "
                f"{required_team_count} temporary Teams for {len(player_ids)} "
                f"players at team size {team_size}; found {len(teams)}."
            ),
        }

    playing_slots = len(teams) * team_size
    sitout_count = len(player_ids) - playing_slots
    missed_counts = _missed_round_counts(tournament)
    previous_nonplaying_ids = _previous_nonplaying_ids(
        tournament,
        completed_round,
    )
    sitout_ids = _choose_fair_sitouts(
        player_ids=player_ids,
        sitout_count=sitout_count,
        missed_counts=missed_counts,
        previous_nonplaying_ids=previous_nonplaying_ids,
        rng=rng,
    )
    active_player_ids = [
        player_id for player_id in player_ids if player_id not in sitout_ids
    ]
    rng.shuffle(active_player_ids)

    partnership_counts = _partnership_counts(tournament)
    groups = _zero_repeat_partition(
        player_ids=active_player_ids,
        team_size=team_size,
        partnership_counts=partnership_counts,
        rng=rng,
    )
    zero_repeat_found = groups is not None

    if groups is None:
        groups, score = _best_effort_partition(
            player_ids=active_player_ids,
            team_size=team_size,
            partnership_counts=partnership_counts,
            rng=rng,
        )
    else:
        score = _partition_score(groups, partnership_counts)

    if groups is None or len(groups) != len(teams):
        return {
            "success": False,
            "message": "Could not construct a complete Random Super Melee roster.",
        }

    team_order = list(teams)
    group_order = list(groups)
    rng.shuffle(team_order)
    rng.shuffle(group_order)

    assignments = {player_id: None for player_id in player_ids}
    for team, group in zip(team_order, group_order):
        if len(group) != team_size:
            return {
                "success": False,
                "message": "Random Super Melee produced an incomplete Team.",
            }
        for player_id in group:
            assignments[player_id] = team

    return {
        "success": True,
        "assignments": assignments,
        "sitout_player_ids": set(sitout_ids),
        "team_size": team_size,
        "teams_affected": len(teams),
        "players_shuffled": len(player_ids),
        "diversity_score": score,
        "zero_repeat_found": zero_repeat_found,
    }
