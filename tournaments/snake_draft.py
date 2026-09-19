"""Result-backed Super Mêlée Snake Draft pairing for assignment-based doubles.

Round 1 Snake Draft remains rating based in ``Tournament.generate_melee_teams``.
This module applies only from Round 2 onward. It builds the whole next-round
roster from the exact immediately preceding Round: winners, losers, and prior
BYE players are resolved from immutable historical data before any assignment
is written.

For every population, the scheduler first selects exactly ``N % 4`` individual
BYE recipients, then constructs every playable doubles partnership as one
decision. A two-player BYE is represented by the existing temporary Team BYE;
one additional player, when required, is an explicit ``MeleeRoundAssignment``
``BYE`` state. Individual BYE fairness is intentionally more important than
winner/loser composition and partnership-repeat avoidance.
"""

from collections import Counter, defaultdict
from itertools import combinations

from tournaments.models import MeleeRoundAssignment


# ``26 choose 2`` is 325, so normal Super Mêlée events use exhaustive,
# deterministic candidate evaluation. The cap keeps pathological tournament
# sizes bounded without changing the primary fairness ordering of candidates
# evaluated first.
MAX_BYE_PAIR_CANDIDATES = 4096


def build_winner_loser_doubles_plan(*, tournament, completed_round, melee_players, teams):
    """Return one complete next-round Snake Draft doubles plan or a safe failure.

    The caller owns all writes. In particular, this function never updates a
    Player, existing Round assignment, Match, result, or rating. A returned
    ``planned_bye_team`` is the exact temporary Team which must receive the
    next Round's team BYE when the downstream Swiss match generator runs.
    """
    from matches.models import Match, MatchPlayer
    from tournaments.partnership_models import MeleePartnership

    registration_by_player_id = {
        registration.player_id: registration for registration in melee_players
    }
    previous_assignments = list(
        MeleeRoundAssignment.objects.select_for_update()
        .filter(tournament=tournament, round=completed_round)
        .select_related("player", "team")
        .order_by("player_id")
    )
    assignment_by_player_id = {
        assignment.player_id: assignment for assignment in previous_assignments
    }
    registered_ids = set(registration_by_player_id)
    if set(assignment_by_player_id) != registered_ids:
        return _failure(
            "The completed Round does not contain one exact assignment state for every registered player."
        )

    assigned_player_ids = {
        assignment.player_id
        for assignment in previous_assignments
        if assignment.state == MeleeRoundAssignment.ASSIGNED
    }
    explicit_bye_player_ids = {
        assignment.player_id
        for assignment in previous_assignments
        if assignment.state == MeleeRoundAssignment.BYE
    }
    (
        previous_team_bye_ids,
        completed_round_bye_team_id,
        bye_error,
    ) = _team_bye_player_ids_for_round(
        tournament=tournament,
        round_obj=completed_round,
        assignments=previous_assignments,
    )
    if bye_error:
        return _failure(bye_error)

    # A team BYE is stored as a normal historical assigned roster because the
    # Players really were that Round's temporary Team. It is neutral for the
    # next Snake Draft result pairing, not a missing result.
    assigned_player_ids.difference_update(previous_team_bye_ids)
    previous_bye_player_ids = explicit_bye_player_ids | previous_team_bye_ids
    eligible_player_ids = assigned_player_ids | previous_bye_player_ids
    if not eligible_player_ids:
        return _failure("The completed Round has no eligible doubles players to pair.")
    bye_count = len(eligible_player_ids) % 4
    expected_team_count = (
        (len(eligible_player_ids) - bye_count) // 2
        + (1 if bye_count >= 2 else 0)
    )
    if len(teams) != expected_team_count:
        return _failure(
            "The temporary doubles team count does not match the completed Round eligible roster."
        )

    matches = list(
        Match.objects.select_for_update()
        .filter(tournament=tournament, round=completed_round)
        .select_related("winner", "loser", "team1", "team2")
        .order_by("id")
    )
    if any(match.status != "completed" for match in matches):
        return _failure("The completed Round still has incomplete matches.")
    if assigned_player_ids and not matches:
        return _failure("Assigned doubles players have no completed Match results.")

    assignment_players_by_team = defaultdict(set)
    for assignment in previous_assignments:
        if assignment.state == MeleeRoundAssignment.ASSIGNED and assignment.team_id:
            assignment_players_by_team[assignment.team_id].add(assignment.player_id)

    snapshot_players_by_match_team = defaultdict(set)
    for snapshot in MatchPlayer.objects.filter(match__in=matches).values(
        "match_id", "team_id", "player_id"
    ):
        snapshot_players_by_match_team[(snapshot["match_id"], snapshot["team_id"])].add(
            snapshot["player_id"]
        )

    winners = []
    losers = []
    seen_result_participants = set()
    for match in matches:
        if not match.winner_id or not match.loser_id:
            return _failure(
                f"Match {match.id} has no resolved winner and loser for Snake Draft pairing."
            )
        if {match.winner_id, match.loser_id} != {match.team1_id, match.team2_id}:
            return _failure(
                f"Match {match.id} has a winner/loser outside its recorded sides."
            )

        winner_ids = _exact_side_roster(
            match_id=match.id,
            team_id=match.winner_id,
            snapshots=snapshot_players_by_match_team,
            assignments=assignment_players_by_team,
        )
        loser_ids = _exact_side_roster(
            match_id=match.id,
            team_id=match.loser_id,
            snapshots=snapshot_players_by_match_team,
            assignments=assignment_players_by_team,
        )
        if winner_ids is None or loser_ids is None:
            return _failure(
                f"Match {match.id} does not have a complete exact historical doubles roster."
            )
        if len(winner_ids) != 2 or len(loser_ids) != 2:
            return _failure(
                f"Match {match.id} is not a complete doubles result for Snake Draft pairing."
            )
        if set(winner_ids) & set(loser_ids):
            return _failure(f"Match {match.id} has overlapping winner and loser rosters.")
        match_player_ids = set(winner_ids) | set(loser_ids)
        if not match_player_ids.issubset(assigned_player_ids):
            return _failure(
                f"Match {match.id} references a player outside the completed Round assignment roster."
            )
        if seen_result_participants.intersection(match_player_ids):
            return _failure(
                "A player appears in more than one completed Match in the Round."
            )
        seen_result_participants.update(match_player_ids)
        winners.extend(winner_ids)
        losers.extend(loser_ids)

    if seen_result_participants != assigned_player_ids:
        return _failure(
            "Every assigned player must have one resolved winner or loser result before Snake Draft pairing."
        )
    if len(winners) != len(losers):
        return _failure("Winner and loser populations are not balanced for doubles pairing.")

    historical_bye_counts, history_error = _historical_individual_bye_counts(
        tournament=tournament,
        through_round=completed_round,
    )
    if history_error:
        return _failure(history_error)

    partnership_counts = Counter()
    for first_player_id, second_player_id in MeleePartnership.objects.filter(
        tournament=tournament,
    ).values_list("player1_id", "player2_id"):
        partnership_counts[tuple(sorted((first_player_id, second_player_id)))] += 1

    winner_ids = set(winners)
    loser_ids = set(losers)
    neutral_ids = set(previous_bye_player_ids)
    if (winner_ids & loser_ids) or (winner_ids & neutral_ids) or (loser_ids & neutral_ids):
        return _failure("The completed Round has overlapping winner, loser, or BYE populations.")
    if winner_ids | loser_ids | neutral_ids != eligible_player_ids:
        return _failure("The completed Round has an unclassified eligible player.")

    next_bye_player_ids = set()
    individual_bye_player_ids = set()
    planned_bye_team = None
    if bye_count:
        bye_choice = _select_next_round_bye_recipients(
            eligible_player_ids=eligible_player_ids,
            winner_ids=winner_ids,
            loser_ids=loser_ids,
            neutral_ids=neutral_ids,
            historical_bye_counts=historical_bye_counts,
            previous_bye_player_ids=previous_bye_player_ids,
            partnership_counts=partnership_counts,
            bye_count=bye_count,
        )
        if bye_choice is None:
            return _failure(
                "No valid fair individual BYE and Snake Draft doubles schedule could be constructed."
            )
        next_bye_player_ids = set(bye_choice["bye_player_ids"])
        playing_pairs = bye_choice["schedule"]["pairs"]
        if bye_count >= 2:
            # A temporary Team container has no fairness identity. Selecting
            # its stable ID is only representation; the *player* recipients
            # above are the fairness decision.
            planned_bye_team = max(teams, key=lambda team: team.id)
            team_bye_player_ids = tuple(sorted(next_bye_player_ids)[:2])
            individual_bye_player_ids = (
                next_bye_player_ids - set(team_bye_player_ids)
            )
            team_pairings = [
                (team, pair)
                for team, pair in zip(
                    [team for team in teams if team.id != planned_bye_team.id],
                    playing_pairs,
                )
            ] + [(planned_bye_team, team_bye_player_ids)]
        else:
            individual_bye_player_ids = set(next_bye_player_ids)
            team_pairings = list(zip(teams, playing_pairs))
    else:
        schedule = _schedule_playing_pairs(
            player_ids=eligible_player_ids,
            winner_ids=winner_ids,
            loser_ids=loser_ids,
            neutral_ids=neutral_ids,
            partnership_counts=partnership_counts,
        )
        if schedule is None:
            return _failure("No valid Snake Draft doubles schedule could be constructed.")
        team_pairings = list(zip(teams, schedule["pairs"]))

    if len(team_pairings) != len(teams):
        return _failure("The next-round doubles plan does not cover every temporary Team.")

    player_team_by_id = {}
    for team, player_pair in team_pairings:
        if len(player_pair) != 2:
            return _failure("A next-round doubles Team does not contain exactly two players.")
        for player_id in player_pair:
            if player_id in player_team_by_id:
                return _failure("A player was selected for more than one next-round Team.")
            player_team_by_id[player_id] = team
    if set(player_team_by_id) | individual_bye_player_ids != eligible_player_ids:
        return _failure(
            "The next-round doubles pairing does not classify every eligible player exactly once."
        )
    if set(player_team_by_id).intersection(individual_bye_player_ids):
        return _failure("A player cannot both receive a BYE and join a next-round Team.")

    player_by_id = {
        registration.player_id: registration.player for registration in melee_players
    }
    assignment_inputs = []
    for player_id in sorted(registered_ids):
        previous = assignment_by_player_id[player_id]
        assigned_team = player_team_by_id.get(player_id)
        if assigned_team is not None:
            assignment_inputs.append(
                {
                    "player": player_by_id[player_id],
                    "team": assigned_team,
                    "state": MeleeRoundAssignment.ASSIGNED,
                }
            )
        elif player_id in individual_bye_player_ids:
            assignment_inputs.append(
                {
                    "player": player_by_id[player_id],
                    "team": None,
                    "state": MeleeRoundAssignment.BYE,
                }
            )
        else:
            # Waitlisted and withdrawn Players retain their explicit eligibility
            # state. They are neither randomized into a Team nor treated as a
            # failure merely because they did not play this Round.
            assignment_inputs.append(
                {
                    "player": player_by_id[player_id],
                    "team": None,
                    "state": previous.state,
                }
            )

    return {
        "success": True,
        "assignment_inputs": assignment_inputs,
        "players_shuffled": len(eligible_player_ids),
        "teams_affected": len(teams),
        "pairings": [pair for _team, pair in team_pairings],
        "completed_round_bye_team_id": completed_round_bye_team_id,
        "planned_bye_player_ids": sorted(next_bye_player_ids),
        "planned_individual_bye_player_ids": sorted(individual_bye_player_ids),
        "planned_bye_team": planned_bye_team,
        "message": (
            f"Prepared {len(team_pairings)} Snake Draft doubles teams from completed "
            f"Round {completed_round.number}."
        ),
    }


def _team_bye_player_ids_for_round(*, tournament, round_obj, assignments):
    """Resolve an authoritative two-player team BYE for one historical Round.

    New Snake Draft rounds use ``MeleeRoundTeamBye``. The narrowly scoped
    fallback reads the established generic ``TournamentTeam`` field so events
    already in progress before this model exists can transition safely. It is
    never used as a cumulative fairness counter.
    """
    from tournaments.models import MeleeRoundTeamBye, TournamentTeam

    records = list(
        MeleeRoundTeamBye.objects.select_for_update()
        .filter(tournament=tournament, round=round_obj)
        .order_by("team_id")[:2]
    )
    if len(records) > 1:
        return set(), None, "More than one recorded team BYE exists for a Mêlée Round."

    team_id = records[0].team_id if records else None
    if team_id is None:
        compatible_round_numbers = {round_obj.number}
        if round_obj.number_in_stage is not None:
            compatible_round_numbers.add(round_obj.number_in_stage)
        fallback_query = TournamentTeam.objects.select_for_update().filter(
            tournament=tournament,
            team__is_tournament_temp=True,
            received_bye_in_round__in=compatible_round_numbers,
        )
        if round_obj.stage_id:
            fallback_query = fallback_query.filter(
                current_stage_number=round_obj.stage.stage_number,
            )
        fallback_records = list(fallback_query.order_by("team_id")[:2])
        if len(fallback_records) > 1:
            return set(), None, "More than one legacy team BYE is recorded for a Mêlée Round."
        if fallback_records:
            team_id = fallback_records[0].team_id

    if team_id is None:
        return set(), None, None

    team_assignments = [
        assignment
        for assignment in assignments
        if assignment.team_id == team_id
    ]
    if (
        len(team_assignments) != 2
        or any(
            assignment.state != MeleeRoundAssignment.ASSIGNED
            for assignment in team_assignments
        )
    ):
        return (
            set(),
            None,
            "The recorded team BYE does not have one complete doubles assignment roster.",
        )
    return {assignment.player_id for assignment in team_assignments}, team_id, None


def _historical_individual_bye_counts(*, tournament, through_round):
    """Reconstruct individual BYEs from immutable rounds and their team BYEs."""
    from tournaments.models import Round

    rounds = list(
        Round.objects.select_for_update()
        .filter(tournament=tournament, number__lte=through_round.number)
        .order_by("number", "id")
    )
    assignments_by_round_id = defaultdict(list)
    for assignment in (
        MeleeRoundAssignment.objects.select_for_update()
        .filter(tournament=tournament, round_id__in=[round_obj.id for round_obj in rounds])
        .select_related("team")
        .order_by("round_id", "player_id")
    ):
        assignments_by_round_id[assignment.round_id].append(assignment)

    counts = Counter()
    for round_obj in rounds:
        assignments = assignments_by_round_id[round_obj.id]
        explicit_byes = {
            assignment.player_id
            for assignment in assignments
            if assignment.state == MeleeRoundAssignment.BYE
        }
        team_byes, _team_id, bye_error = _team_bye_player_ids_for_round(
            tournament=tournament,
            round_obj=round_obj,
            assignments=assignments,
        )
        if bye_error:
            return Counter(), bye_error
        for player_id in explicit_byes | team_byes:
            counts[player_id] += 1
    return counts, None


def _select_next_round_bye_recipients(
    *,
    eligible_player_ids,
    winner_ids,
    loser_ids,
    neutral_ids,
    historical_bye_counts,
    previous_bye_player_ids,
    partnership_counts,
    bye_count,
):
    """Choose ``bye_count`` recipients and all playable pairs atomically."""
    if bye_count not in {1, 2, 3}:
        return None
    candidates = list(combinations(sorted(eligible_player_ids), bye_count))
    candidates.sort(
        key=lambda recipient_ids: _bye_fairness_key(
            recipient_ids=recipient_ids,
            eligible_player_ids=eligible_player_ids,
            historical_bye_counts=historical_bye_counts,
        )
    )

    best = None
    for bye_player_ids in candidates[:MAX_BYE_PAIR_CANDIDATES]:
        remaining_player_ids = set(eligible_player_ids) - set(bye_player_ids)
        schedule = _schedule_playing_pairs(
            player_ids=remaining_player_ids,
            winner_ids=set(winner_ids) - set(bye_player_ids),
            loser_ids=set(loser_ids) - set(bye_player_ids),
            neutral_ids=set(neutral_ids) - set(bye_player_ids),
            partnership_counts=partnership_counts,
        )
        if schedule is None:
            continue
        key = (
            *_bye_fairness_key(
                recipient_ids=bye_player_ids,
                eligible_player_ids=eligible_player_ids,
                historical_bye_counts=historical_bye_counts,
            ),
            # Only after cumulative fairness does the scheduler avoid a
            # consecutive individual BYE where another fair choice exists.
            sum(player_id in previous_bye_player_ids for player_id in bye_player_ids),
            # Then maximize real winner-loser partnerships before partnership
            # history. A negative value gives the largest count priority.
            -schedule["winner_loser_pairs"],
            schedule["repeat_cost"],
            bye_player_ids,
        )
        if best is None or key < best["key"]:
            best = {
                "key": key,
                "bye_player_ids": bye_player_ids,
                "schedule": schedule,
            }
    return best


def _bye_fairness_key(
    *, recipient_ids, eligible_player_ids, historical_bye_counts
):
    """Primary deterministic fairness ordering for candidate BYE recipients."""
    after_counts = [
        historical_bye_counts[player_id] + (1 if player_id in recipient_ids else 0)
        for player_id in sorted(eligible_player_ids)
    ]
    return (
        max(after_counts) - min(after_counts),
        sum(count * count for count in after_counts),
        tuple(sorted(after_counts, reverse=True)),
        sum(historical_bye_counts[player_id] for player_id in recipient_ids),
    )


def _schedule_playing_pairs(
    *, player_ids, winner_ids, loser_ids, neutral_ids, partnership_counts
):
    """Construct a complete doubles schedule with bounded deterministic matching.

    Winner-loser pairs are maximized first. Any remaining prior-BYE Players are
    neutral and buffer winner/loser imbalance. If a fair next BYE choice leaves
    an unavoidable same-result pair, that pair is allowed rather than rejecting
    the fair schedule.
    """
    player_ids = set(player_ids)
    winner_ids = set(winner_ids)
    loser_ids = set(loser_ids)
    neutral_ids = set(neutral_ids)
    if len(player_ids) % 2:
        return None
    if (
        (winner_ids & loser_ids)
        or (winner_ids & neutral_ids)
        or (loser_ids & neutral_ids)
        or winner_ids | loser_ids | neutral_ids != player_ids
    ):
        return None

    pairs = []
    if len(winner_ids) <= len(loser_ids):
        winner_loser_pairs = _pair_categories(
            left_ids=winner_ids,
            right_ids=loser_ids,
            partnership_counts=partnership_counts,
        )
    else:
        winner_loser_pairs = _pair_categories(
            left_ids=loser_ids,
            right_ids=winner_ids,
            partnership_counts=partnership_counts,
        )
    if winner_loser_pairs is None:
        return None
    pairs.extend(winner_loser_pairs)

    used_ids = {player_id for pair in pairs for player_id in pair}
    remaining_neutral_ids = neutral_ids - used_ids
    remaining_result_ids = (winner_ids | loser_ids) - used_ids

    if remaining_neutral_ids and remaining_result_ids:
        if len(remaining_neutral_ids) <= len(remaining_result_ids):
            bridge_pairs = _pair_categories(
                left_ids=remaining_neutral_ids,
                right_ids=remaining_result_ids,
                partnership_counts=partnership_counts,
            )
        else:
            bridge_pairs = _pair_categories(
                left_ids=remaining_result_ids,
                right_ids=remaining_neutral_ids,
                partnership_counts=partnership_counts,
            )
        if bridge_pairs is None:
            return None
        pairs.extend(bridge_pairs)
        used_ids.update(player_id for pair in bridge_pairs for player_id in pair)

    remaining_ids = player_ids - used_ids
    tail_pairs = _pair_any_players(
        player_ids=remaining_ids,
        partnership_counts=partnership_counts,
    )
    if tail_pairs is None:
        return None
    pairs.extend(tail_pairs)

    if {player_id for pair in pairs for player_id in pair} != player_ids:
        return None
    winner_loser_pair_count = sum(
        (first_player_id in winner_ids and second_player_id in loser_ids)
        or (first_player_id in loser_ids and second_player_id in winner_ids)
        for first_player_id, second_player_id in pairs
    )
    repeat_cost = sum(
        partnership_counts[tuple(sorted(pair))] for pair in pairs
    )
    return {
        "pairs": [tuple(sorted(pair)) for pair in pairs],
        "winner_loser_pairs": winner_loser_pair_count,
        "repeat_cost": repeat_cost,
    }


def _pair_categories(*, left_ids, right_ids, partnership_counts):
    """Pair every member of the smaller category, avoiding repeats where possible."""
    left_ids = sorted(left_ids)
    right_ids = sorted(right_ids)
    if len(left_ids) > len(right_ids):
        return None
    zero_repeat = _zero_repeat_matching(
        left_ids=left_ids,
        right_ids=right_ids,
        partnership_counts=partnership_counts,
    )
    if zero_repeat is not None:
        return zero_repeat

    remaining_right_ids = set(right_ids)
    pairs = []
    for left_id in left_ids:
        if not remaining_right_ids:
            return None
        right_id = min(
            remaining_right_ids,
            key=lambda candidate: (
                partnership_counts[tuple(sorted((left_id, candidate)))],
                candidate,
            ),
        )
        remaining_right_ids.remove(right_id)
        pairs.append((left_id, right_id))
    return pairs


def _pair_any_players(*, player_ids, partnership_counts):
    """Pair the final same-category or neutral remainder with minimal repeats."""
    remaining_ids = set(player_ids)
    if len(remaining_ids) % 2:
        return None
    pairs = []
    while remaining_ids:
        first_player_id = min(remaining_ids)
        remaining_ids.remove(first_player_id)
        second_player_id = min(
            remaining_ids,
            key=lambda candidate: (
                partnership_counts[tuple(sorted((first_player_id, candidate)))],
                candidate,
            ),
        )
        remaining_ids.remove(second_player_id)
        pairs.append((first_player_id, second_player_id))
    return pairs


def _exact_side_roster(*, match_id, team_id, snapshots, assignments):
    """Use MatchPlayer snapshot when present; otherwise exact Round rows."""
    snapshot = snapshots.get((match_id, team_id))
    if snapshot:
        return snapshot
    assignment = assignments.get(team_id)
    return assignment if assignment else None


def _zero_repeat_matching(*, left_ids, right_ids, partnership_counts):
    """Return a complete zero-history bipartite matching when one exists."""
    matched_left_by_right = {}

    def assign(left_id, seen_right_ids):
        candidates = [
            right_id
            for right_id in right_ids
            if partnership_counts[tuple(sorted((left_id, right_id)))] == 0
        ]
        for right_id in sorted(candidates):
            if right_id in seen_right_ids:
                continue
            seen_right_ids.add(right_id)
            current_left = matched_left_by_right.get(right_id)
            if current_left is None or assign(current_left, seen_right_ids):
                matched_left_by_right[right_id] = left_id
                return True
        return False

    for left_id in left_ids:
        if not assign(left_id, set()):
            return None

    right_by_left = {
        left_id: right_id for right_id, left_id in matched_left_by_right.items()
    }
    if len(right_by_left) != len(left_ids):
        return None
    return [(left_id, right_by_left[left_id]) for left_id in left_ids]


def _failure(message):
    return {"success": False, "message": message}
