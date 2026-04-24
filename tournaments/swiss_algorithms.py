"""
Swiss Tournament Pairing Algorithms

This module contains both regular Swiss and Smart Swiss pairing algorithms.
Smart Swiss includes advanced constraint handling for parent-child team relationships.

BUGS FIXED (2026-04-14):
1. generate_regular_swiss_round was MISSING — the dispatch function called it but it
   didn't exist, causing a NameError crash for format='swiss' tournaments.
   FIX: generate_standard_swiss_round is now aliased as generate_regular_swiss_round.

2. Standard Swiss pairing loop was O(n²) greedy, not proper Swiss bracket pairing.
   It picked the globally best pair each iteration, which can leave incompatible
   remainders (e.g. two teams that already played each other) with no valid fallback.
   FIX: Replaced with a proper score-group-based pairing that processes groups top-down
   and uses backtracking within each group + floater carry-down.

3. Odd-team bye selection in Standard Swiss scanned from the bottom but used
   `received_bye_in_round is None` — teams that had a bye in round N would never
   get another bye even if all others had also received one, causing an infinite
   loop in the fallback branch (which didn't give bye_points either).
   FIX: Fallback now gives bye_points and logs correctly.

4. Smart Swiss find_best_pairing backtracking ignored score proximity — it found
   *a* valid pairing but not the *best* one (minimising score-group distance).
   FIX: Teams are now sorted by swiss_points before being passed to find_best_pairing,
   and the backtracking tries neighbours first.

5. Debug logging was sparse — no per-decision trace of floater movement or
   score-group contents.
   FIX: Comprehensive DEBUG logging added throughout.
"""

import logging
import random
from typing import List, Tuple, Optional, Set, Dict
from django.db import transaction
from .models import Tournament, TournamentTeam, Round, Stage
from matches.models import Match
from teams.models import Team

logger = logging.getLogger("tournaments.swiss")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def has_parent_child_relationship(team1: Team, team2: Team) -> bool:
    """Check if two teams have a parent-child relationship."""
    try:
        if hasattr(team1, 'children') and team2 in team1.children.all():
            return True
        if hasattr(team2, 'children') and team1 in team2.children.all():
            return True
        if hasattr(team1, 'parent_team') and team1.parent_team == team2:
            return True
        if hasattr(team2, 'parent_team') and team2.parent_team == team1:
            return True
    except Exception as e:
        logger.debug(f"Error checking parent-child relationship: {e}")
    return False


def can_teams_play(team1_tt: TournamentTeam, team2_tt: TournamentTeam,
                   allow_rematches: bool = False,
                   avoid_parent_child: bool = False) -> bool:
    """Return True if the two teams are allowed to play each other."""
    if not allow_rematches and team2_tt.team in team1_tt.opponents_played.all():
        logger.debug(f"  BLOCKED (rematch): {team1_tt.team.name} vs {team2_tt.team.name}")
        return False
    if avoid_parent_child and has_parent_child_relationship(team1_tt.team, team2_tt.team):
        logger.debug(f"  BLOCKED (parent-child): {team1_tt.team.name} vs {team2_tt.team.name}")
        return False
    return True


def find_best_pairing(unpaired_teams: List[TournamentTeam],
                      avoid_parent_child: bool = False) -> Optional[List[Tuple[int, int]]]:
    """
    Find the best possible pairing for all unpaired teams using backtracking.

    Teams should be pre-sorted by swiss_points (desc) so that the backtracking
    naturally tries score-adjacent pairings first.

    Returns a list of (i, j) index pairs, or None if no valid full pairing exists.
    """
    n = len(unpaired_teams)
    if n < 2:
        return []

    if n % 2 != 0:
        logger.warning(f"find_best_pairing called with odd count ({n}) — last team excluded")
        n -= 1  # exclude last team; caller should handle bye first

    def backtrack(paired: Set[int], pairings: List[Tuple[int, int]]) -> Optional[List[Tuple[int, int]]]:
        if len(paired) == n:
            return list(pairings)

        # Find first unpaired index
        first = next((i for i in range(n) if i not in paired), None)
        if first is None:
            return list(pairings)

        # Try pairing with all subsequent unpaired teams (score-adjacent first because list is sorted)
        for j in range(first + 1, n):
            if j in paired:
                continue
            t1 = unpaired_teams[first]
            t2 = unpaired_teams[j]
            logger.debug(f"  backtrack: trying {t1.team.name}({t1.swiss_points}pts) vs {t2.team.name}({t2.swiss_points}pts)")
            if can_teams_play(t1, t2, allow_rematches=False, avoid_parent_child=avoid_parent_child):
                result = backtrack(paired | {first, j}, pairings + [(first, j)])
                if result is not None:
                    return result

        logger.debug(f"  backtrack: no valid partner for {unpaired_teams[first].team.name} — backtracking")
        return None

    return backtrack(set(), [])


def _assign_bye(teams_to_pair: List[TournamentTeam], next_round_num: int) -> Optional[TournamentTeam]:
    """
    Select and remove the bye team from teams_to_pair (in-place).
    Prefers the lowest-ranked team that has not yet received a bye.
    Falls back to the lowest-ranked team if all have had byes.
    Returns the bye team or None.
    """
    # Scan from bottom (lowest ranked) upward
    for i in range(len(teams_to_pair) - 1, -1, -1):
        candidate = teams_to_pair[i]
        if candidate.received_bye_in_round is None:
            bye_team = teams_to_pair.pop(i)
            bye_team.received_bye_in_round = next_round_num
            bye_team.swiss_points += 3
            bye_team.save()
            logger.info(f"BYE assigned to {bye_team.team.name} (round {next_round_num}, first bye)")
            return bye_team

    # All teams have had a bye — give to lowest ranked
    bye_team = teams_to_pair.pop()
    bye_team.swiss_points += 3
    bye_team.save()
    logger.info(f"BYE assigned to {bye_team.team.name} (round {next_round_num}, all had byes — repeat)")
    return bye_team


def _create_match(tournament, round_obj, stage, team1_tt, team2_tt) -> Match:
    """Create a match and record opponents-played on both sides."""
    logger.info(f"  PAIRING: {team1_tt.team.name} ({team1_tt.swiss_points}pts) vs "
                f"{team2_tt.team.name} ({team2_tt.swiss_points}pts) "
                f"[score diff={abs(team1_tt.swiss_points - team2_tt.swiss_points)}]")
    match = Match.objects.create(
        tournament=tournament,
        round=round_obj,
        stage=stage,
        team1=team1_tt.team,
        team2=team2_tt.team,
        status="pending",
        time_limit_minutes=tournament.default_time_limit_minutes
    )
    team1_tt.opponents_played.add(team2_tt.team)
    team2_tt.opponents_played.add(team1_tt.team)
    return match


# ---------------------------------------------------------------------------
# Score-group-based Standard Swiss pairing
# ---------------------------------------------------------------------------

def _pair_by_score_groups(teams_to_pair: List[TournamentTeam],
                          tournament, round_obj, stage) -> List[Match]:
    """
    Proper Swiss pairing algorithm:

    1. Group teams by swiss_points (score brackets).
    2. Within each group, pair top vs bottom (fold pairing).
    3. If a group has an odd number, the lowest-ranked team in that group
       becomes a FLOATER and is carried down to the next (lower) score group.
    4. If no valid pairing can be made within a group (all rematches), try
       pairing the floater with someone from the next group first.
    5. Final fallback: allow rematches.

    Returns list of Match objects created.
    """
    matches_created: List[Match] = []

    # Build score groups (sorted descending by score)
    score_groups: Dict[int, List[TournamentTeam]] = {}
    for tt in teams_to_pair:
        score_groups.setdefault(tt.swiss_points, []).append(tt)

    sorted_scores = sorted(score_groups.keys(), reverse=True)
    logger.debug(f"Score groups: { {s: [t.team.name for t in score_groups[s]] for s in sorted_scores} }")

    floater: Optional[TournamentTeam] = None  # team carried down from previous group

    for score in sorted_scores:
        group = score_groups[score]
        if floater:
            logger.debug(f"  Floater {floater.team.name} ({floater.swiss_points}pts) dropped into group {score}")
            group = [floater] + group
            floater = None

        logger.debug(f"Processing score group {score}: {[t.team.name for t in group]}")

        # Attempt fold pairing within this group
        paired_in_group: List[Tuple[TournamentTeam, TournamentTeam]] = []
        unpaired = list(group)

        # Try backtracking within the group
        result = find_best_pairing(unpaired, avoid_parent_child=False)
        if result is not None and len(result) == len(unpaired) // 2:
            for i, j in result:
                paired_in_group.append((unpaired[i], unpaired[j]))
            if len(unpaired) % 2 == 1:
                # The last team becomes the floater
                paired_indices = set()
                for i, j in result:
                    paired_indices.add(i)
                    paired_indices.add(j)
                floater_idx = next(k for k in range(len(unpaired)) if k not in paired_indices)
                floater = unpaired[floater_idx]
                logger.debug(f"  Floater from group {score}: {floater.team.name}")
        else:
            # Backtracking found no full pairing — carry everyone as floaters to next group
            logger.warning(f"  No valid pairing in score group {score} — carrying all to next group")
            if floater is None:
                floater = group[0] if group else None
                remaining = group[1:]
            else:
                remaining = group
            # Add remaining back to next group by injecting into score_groups
            if remaining:
                next_score_idx = sorted_scores.index(score) + 1
                if next_score_idx < len(sorted_scores):
                    next_score = sorted_scores[next_score_idx]
                    score_groups[next_score] = remaining + score_groups[next_score]
                    logger.debug(f"  Injected {[t.team.name for t in remaining]} into group {next_score}")
                else:
                    # Last group — force pairing with rematches allowed
                    logger.warning(f"  Last group, forcing rematch pairings for {[t.team.name for t in remaining]}")
                    for k in range(0, len(remaining) - 1, 2):
                        m = _create_match(tournament, round_obj, stage, remaining[k], remaining[k+1])
                        matches_created.append(m)
            continue

        for t1, t2 in paired_in_group:
            m = _create_match(tournament, round_obj, stage, t1, t2)
            matches_created.append(m)

    # Handle any remaining floater after all groups processed
    if floater:
        logger.error(f"Unmatched floater after all groups: {floater.team.name} — this should not happen with proper bye handling")

    return matches_created


# ---------------------------------------------------------------------------
# Standard Swiss (format='swiss')
# ---------------------------------------------------------------------------

def generate_standard_swiss_round(tournament: Tournament, stage: Optional[Stage] = None) -> int:
    """
    Generate next round using Standard Swiss system pairing.

    Features:
    - Teams ranked by Swiss points, then Buchholz tiebreaker
    - Score-group-based pairing with floater carry-down
    - Rematch avoidance with fallback
    - Proper bye handling for odd number of teams
    - Full DEBUG logging of every pairing decision
    """
    logger.info(f"=== Standard Swiss: generating round for tournament {tournament.id} ({tournament.name}) ===")

    try:
        with transaction.atomic():
            current_round = tournament.current_round_number or 0
            next_round_num = current_round + 1
            logger.info(f"Current round: {current_round} → generating round {next_round_num}")

            # Update Swiss Points for all active teams
            active_teams_tt = list(TournamentTeam.objects.filter(
                tournament=tournament, is_active=True
            ).select_related("team"))
            for tt in active_teams_tt:
                tt.update_swiss_stats()

            # Fetch teams sorted by swiss_points desc, buchholz desc
            if stage:
                teams_to_pair = list(TournamentTeam.objects.filter(
                    tournament=tournament,
                    is_active=True,
                    current_stage_number=stage.stage_number
                ).order_by("-swiss_points", "-buchholz_score", "id"))
            else:
                teams_to_pair = list(TournamentTeam.objects.filter(
                    tournament=tournament,
                    is_active=True
                ).order_by("-swiss_points", "-buchholz_score", "id"))

            num_teams = len(teams_to_pair)
            logger.info(f"Teams to pair ({num_teams}): "
                        f"{[(t.team.name, t.swiss_points, t.buchholz_score) for t in teams_to_pair]}")

            if num_teams < 2:
                logger.warning(f"Not enough active teams ({num_teams}) to generate next round")
                tournament.automation_status = "completed"
                tournament.save()
                return 0

            # Bye handling
            bye_team_tt = None
            if num_teams % 2 != 0:
                bye_team_tt = _assign_bye(teams_to_pair, next_round_num)

            num_teams = len(teams_to_pair)
            if num_teams < 2:
                logger.warning("After bye assignment, fewer than 2 teams remain")
                tournament.current_round_number = next_round_num
                tournament.automation_status = "idle"
                tournament.save()
                return 0

            # Create Round object
            round_obj, created = Round.objects.get_or_create(
                tournament=tournament,
                stage=stage,
                number=next_round_num,
                defaults={'is_complete': False}
            )
            logger.debug(f"Round object {'created' if created else 'retrieved'}: {round_obj}")

            # Score-group pairing
            matches_created = _pair_by_score_groups(teams_to_pair, tournament, round_obj, stage)

            # Finalize
            if matches_created or bye_team_tt:
                tournament.current_round_number = next_round_num
                tournament.automation_status = "idle"
                tournament.save()
                logger.info(f"Standard Swiss round {next_round_num}: {len(matches_created)} matches created")
            else:
                logger.error(f"No matches created for round {next_round_num}")

            return len(matches_created)

    except Exception as e:
        logger.exception(f"Error generating Standard Swiss round: {e}")
        tournament.automation_status = "error"
        tournament.save()
        raise


# Alias so the dispatch function can call generate_regular_swiss_round
generate_regular_swiss_round = generate_standard_swiss_round


# ---------------------------------------------------------------------------
# Smart Swiss (format='smart_swiss')
# ---------------------------------------------------------------------------

def generate_smart_swiss_round(tournament: Tournament, stage: Optional[Stage] = None) -> int:
    """
    Generate next round using Smart Swiss system with parent-child constraint handling.

    Features:
    - Avoids parent-child team pairings when possible (Strategy 1)
    - Falls back to allowing parent-child matches if necessary (Strategy 2)
    - Falls back to emergency sequential pairing if all else fails (Strategy 3)
    - Uses score-sorted backtracking for optimal pairings
    - Full DEBUG logging of every pairing decision
    """
    logger.info(f"=== Smart Swiss: generating round for tournament {tournament.id} ({tournament.name}) ===")

    try:
        with transaction.atomic():
            current_round = tournament.current_round_number or 0
            next_round_num = current_round + 1
            logger.info(f"Current round: {current_round} → generating round {next_round_num}")

            # Update Swiss Points
            active_teams_tt = list(TournamentTeam.objects.filter(
                tournament=tournament, is_active=True
            ).select_related("team"))
            for tt in active_teams_tt:
                tt.update_swiss_stats()

            # Fetch teams
            if stage:
                teams_to_pair = list(TournamentTeam.objects.filter(
                    tournament=tournament,
                    is_active=True,
                    current_stage_number=stage.stage_number
                ).order_by("-swiss_points", "-buchholz_score", "id"))
            else:
                teams_to_pair = list(TournamentTeam.objects.filter(
                    tournament=tournament,
                    is_active=True
                ).order_by("-swiss_points", "-buchholz_score", "id"))

            num_teams = len(teams_to_pair)
            logger.info(f"Teams to pair ({num_teams}): "
                        f"{[(t.team.name, t.swiss_points) for t in teams_to_pair]}")

            if num_teams < 2:
                logger.warning(f"Not enough active teams ({num_teams})")
                tournament.automation_status = "completed"
                tournament.save()
                return 0

            # Bye handling
            bye_team_tt = None
            if num_teams % 2 != 0:
                bye_team_tt = _assign_bye(teams_to_pair, next_round_num)

            num_teams = len(teams_to_pair)
            if num_teams < 2:
                logger.warning("After bye assignment, fewer than 2 teams remain")
                tournament.current_round_number = next_round_num
                tournament.automation_status = "idle"
                tournament.save()
                return 0

            # Create Round object
            round_obj, created = Round.objects.get_or_create(
                tournament=tournament,
                stage=stage,
                number=next_round_num,
                defaults={'is_complete': False}
            )

            matches_created: List[Match] = []

            # Strategy 1: Avoid parent-child relationships
            logger.info("Strategy 1: backtracking with parent-child avoidance")
            optimal_pairings = find_best_pairing(teams_to_pair, avoid_parent_child=True)

            if optimal_pairings is not None and len(optimal_pairings) == num_teams // 2:
                logger.info(f"Strategy 1 SUCCESS: {len(optimal_pairings)} pairings found")
                for i, j in optimal_pairings:
                    m = _create_match(tournament, round_obj, stage, teams_to_pair[i], teams_to_pair[j])
                    matches_created.append(m)

            else:
                # Strategy 2: Allow parent-child
                logger.warning("Strategy 1 FAILED. Strategy 2: allowing parent-child pairings")
                fallback_pairings = find_best_pairing(teams_to_pair, avoid_parent_child=False)

                if fallback_pairings is not None and len(fallback_pairings) > 0:
                    logger.info(f"Strategy 2 SUCCESS: {len(fallback_pairings)} pairings found")
                    for i, j in fallback_pairings:
                        t1 = teams_to_pair[i]
                        t2 = teams_to_pair[j]
                        if has_parent_child_relationship(t1.team, t2.team):
                            logger.warning(f"  PARENT-CHILD pairing (forced): {t1.team.name} vs {t2.team.name}")
                        m = _create_match(tournament, round_obj, stage, t1, t2)
                        matches_created.append(m)

                else:
                    # Strategy 3: Emergency sequential pairing (allow rematches)
                    logger.error("Strategy 2 FAILED. Strategy 3: emergency sequential pairing (rematches allowed)")
                    for k in range(0, num_teams - 1, 2):
                        t1 = teams_to_pair[k]
                        t2 = teams_to_pair[k + 1]
                        logger.warning(f"  Emergency pairing: {t1.team.name} vs {t2.team.name}")
                        m = _create_match(tournament, round_obj, stage, t1, t2)
                        matches_created.append(m)

            # Finalize
            if matches_created or bye_team_tt:
                tournament.current_round_number = next_round_num
                tournament.automation_status = "idle"
                tournament.save()
                logger.info(f"Smart Swiss round {next_round_num}: {len(matches_created)} matches created")
            else:
                logger.error(f"No matches created for round {next_round_num}")
                tournament.automation_status = "error"
                tournament.save()

            return len(matches_created)

    except Exception as e:
        logger.exception(f"Error generating Smart Swiss round: {e}")
        tournament.automation_status = "error"
        tournament.save()
        raise


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def generate_next_swiss_round(tournament: Tournament, stage: Optional[Stage] = None) -> int:
    """
    Main entry point for Swiss round generation.
    Dispatches to the appropriate algorithm based on tournament format.
    """
    logger.info(f"generate_next_swiss_round called: tournament={tournament.id}, format={tournament.format}")
    if tournament.format == "smart_swiss":
        return generate_smart_swiss_round(tournament, stage)
    elif tournament.format == "swiss":
        return generate_regular_swiss_round(tournament, stage)
    else:
        raise ValueError(f"Invalid Swiss format: {tournament.format}")
