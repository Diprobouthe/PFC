"""Utilities for assignment-based Super Mêlée player shuffling."""

import logging
import random

from django.db import transaction

logger = logging.getLogger("tournaments")


def prepare_automatic_super_melee_transition(*, tournament, completed_round):
    """Prepare the next Super Mêlée roster before generic round generation.

    This is the single automatic transition entry point. It runs from the
    completion signal, after the final Match has been saved as completed and
    before generic tournament automation creates the next Match rows.

    The final configured Round has no successor to prepare. That is a normal
    terminal condition and lets generic automation complete the stage instead.
    """
    if not (
        tournament.is_melee
        and tournament.shuffle_players_after_round
        and completed_round is not None
    ):
        return {
            "applicable": False,
            "success": True,
            "next_round_prepared": False,
            "message": "Automatic Super Mêlée shuffle is not configured.",
        }

    if not check_if_specific_round_complete(tournament, completed_round):
        return {
            "applicable": True,
            "success": False,
            "next_round_prepared": False,
            "message": "The completed Round is not ready for a Super Mêlée transition.",
        }

    if (
        completed_round.stage_id
        and completed_round.number_in_stage >= completed_round.stage.num_rounds_in_stage
    ):
        return {
            "applicable": True,
            "success": True,
            "next_round_prepared": False,
            "final_round": True,
            "message": "The final configured Super Mêlée Round requires no next roster.",
        }

    result = shuffle_melee_players(
        tournament=tournament,
        shuffle_type="automatic",
        shuffled_by=None,
        completed_round=completed_round,
    )
    result["applicable"] = True
    result["next_round_prepared"] = result["success"]
    return result


def shuffle_melee_players(
    tournament,
    shuffle_type="manual",
    shuffled_by=None,
    round_number=None,
    completed_round=None,
):
    """Redistribute registered Mêlée Players without changing ``Player.team``.

    P4 reads the active tournament population from ``MeleePlayer`` and writes a
    complete immutable roster for the concrete next Round. ``assigned_team`` is
    updated as current tournament state only. Existing temporary Teams remain
    competition containers; no Team.players membership is used. The persisted
    pre-P4 legacy mode retains its narrowly scoped Player.team projection until
    restoration so already-started tournaments remain operable.
    """
    from tournaments.melee_assignments import (
        MeleeRoundAssignmentInput,
        MeleeRoundAssignmentWriter,
    )
    from tournaments.models import MeleePlayer, Round, Tournament, TournamentTeam
    from tournaments.partnership_models import MeleePartnership, MeleeShuffleHistory
    from pfc_core.session_refresh import (
        refresh_legacy_player_team_session,
    )

    if not tournament.is_melee:
        return {
            "success": False,
            "players_shuffled": 0,
            "teams_affected": 0,
            "message": "Tournament is not in Mêlée mode",
        }
    if not tournament.melee_teams_generated:
        return {
            "success": False,
            "players_shuffled": 0,
            "teams_affected": 0,
            "message": "Mêlée teams have not been generated yet",
        }

    try:
        with transaction.atomic():
            tournament = Tournament.objects.select_for_update().get(pk=tournament.pk)
            tournament_teams = list(
                TournamentTeam.objects.filter(
                    tournament=tournament,
                    team__is_tournament_temp=True,
                )
                .select_related("team")
                .order_by("team__name", "team_id")
            )
            teams = [registration.team for registration in tournament_teams]
            if not teams:
                return {
                    "success": False,
                    "players_shuffled": 0,
                    "teams_affected": 0,
                    "message": "No Mêlée teams found",
                }

            # P4 source of truth: tournament registration, not Team.players.
            melee_players = list(
                MeleePlayer.objects.select_for_update()
                .filter(tournament=tournament)
                .select_related("player")
                .order_by("player_id")
            )
            all_players = [registration.player for registration in melee_players]
            if not all_players:
                return {
                    "success": False,
                    "players_shuffled": 0,
                    "teams_affected": 0,
                    "message": "No players registered in this Mêlée tournament",
                }

            completed_round_obj = completed_round
            completed_round_number = (
                completed_round_obj.number
                if completed_round_obj is not None
                else (
                    round_number
                    if round_number is not None
                    else (tournament.current_round_number or 1)
                )
            )
            if completed_round_obj is None:
                candidate_rounds = list(
                    Round.objects.filter(
                        tournament=tournament,
                        number=completed_round_number,
                    ).order_by("id")[:2]
                )
                if len(candidate_rounds) != 1:
                    return {
                        "success": False,
                        "players_shuffled": 0,
                        "teams_affected": 0,
                        "message": (
                            "An exact completed Round is required for this Mêlée shuffle."
                        ),
                    }
                completed_round_obj = candidate_rounds[0]
            completed_round_obj = Round.objects.select_for_update().get(
                pk=completed_round_obj.pk,
            )

            if completed_round_obj.tournament_id != tournament.id:
                return {
                    "success": False,
                    "players_shuffled": 0,
                    "teams_affected": 0,
                    "message": "The completed Round does not belong to this tournament.",
                }

            history = MeleeShuffleHistory.objects.select_for_update().filter(
                tournament=tournament,
            )
            if tournament.melee_roster_mode == tournament.MELEE_ROSTER_MODE_ASSIGNMENT:
                already_shuffled = history.filter(round=completed_round_obj).exists()
            else:
                already_shuffled = history.filter(
                    round_number=completed_round_number,
                ).exists()
            if already_shuffled:
                return {
                    "success": True,
                    "already_processed": True,
                    "players_shuffled": 0,
                    "teams_affected": 0,
                    "message": "This completed Mêlée Round was already shuffled.",
                }

            snake_winner_loser = (
                tournament.melee_team_algorithm
                == tournament.MELEE_TEAM_ALGORITHM_SNAKE_DRAFT
                and tournament.melee_format == "doublets"
            )
            snake_plan = None
            if snake_winner_loser:
                from tournaments.snake_draft import build_winner_loser_doubles_plan

                # Validate every completed result and construct the entire
                # winner-loser plan before creating a next Round or changing a
                # current assignment. A failed plan leaves no partial roster.
                snake_plan = build_winner_loser_doubles_plan(
                    tournament=tournament,
                    completed_round=completed_round_obj,
                    melee_players=melee_players,
                    teams=teams,
                )
                if not snake_plan["success"]:
                    return {
                        "success": False,
                        "players_shuffled": 0,
                        "teams_affected": 0,
                        "message": snake_plan["message"],
                    }

            next_round_number = completed_round_number + 1
            next_round_obj = MeleeRoundAssignmentWriter.next_round_for_shuffle(
                tournament=tournament,
                completed_round=completed_round_obj,
                completed_round_number=completed_round_number,
            )
            if next_round_obj is None:
                return {
                    "success": False,
                    "players_shuffled": 0,
                    "teams_affected": 0,
                    "message": (
                        "No unambiguous next Round is available for this Mêlée shuffle."
                    ),
                }

            from matches.models import Match

            if Match.objects.filter(round=next_round_obj).exists():
                return {
                    "success": False,
                    "players_shuffled": 0,
                    "teams_affected": 0,
                    "message": (
                        "The next Mêlée Round already has Matches and cannot be reshuffled."
                    ),
                }

            planned_bye_team = None
            completed_round_bye_team_id = None
            if snake_winner_loser:
                assignment_inputs = [
                    MeleeRoundAssignmentInput(**input_data)
                    for input_data in snake_plan["assignment_inputs"]
                ]
                players_shuffled = snake_plan["players_shuffled"]
                teams_affected = snake_plan["teams_affected"]
                planned_bye_team = snake_plan.get("planned_bye_team")
                completed_round_bye_team_id = snake_plan.get(
                    "completed_round_bye_team_id"
                )
                shuffle_description = (
                    "Snake Draft winner-loser doubles assignment"
                )
            else:
                # Preserve the existing random Super Mêlée behavior for every
                # non-Snake algorithm and all non-doubles formats.
                random.shuffle(all_players)
                team_size = len(all_players) // len(teams)
                assignments_by_player_id = {}
                player_index = 0
                for team in teams:
                    for _ in range(team_size):
                        if player_index >= len(all_players):
                            break
                        player = all_players[player_index]
                        assignments_by_player_id[player.id] = team
                        player_index += 1

                # Preserve historic distribution behavior for remainders.
                for team in teams:
                    if player_index >= len(all_players):
                        break
                    player = all_players[player_index]
                    assignments_by_player_id[player.id] = team
                    player_index += 1

                assignment_inputs = []
                for melee_player in melee_players:
                    assigned_team = assignments_by_player_id.get(melee_player.player_id)
                    assignment_inputs.append(
                        MeleeRoundAssignmentInput(
                            player=melee_player.player,
                            team=assigned_team,
                            state="assigned" if assigned_team else "waitlisted",
                        )
                    )
                players_shuffled = len(all_players)
                teams_affected = len(teams)
                shuffle_description = "Assignment-based random shuffle"

            if planned_bye_team is not None or completed_round_bye_team_id is not None:
                from tournaments.models import MeleeRoundTeamBye

                if completed_round_bye_team_id is not None:
                    completed_bye = (
                        MeleeRoundTeamBye.objects.select_for_update()
                        .filter(tournament=tournament, round=completed_round_obj)
                        .first()
                    )
                    if (
                        completed_bye
                        and completed_bye.team_id != completed_round_bye_team_id
                    ):
                        return {
                            "success": False,
                            "players_shuffled": 0,
                            "teams_affected": 0,
                            "message": (
                                "The completed Snake Draft Round has conflicting team BYE history."
                            ),
                        }

            if planned_bye_team is not None:
                existing_bye = (
                    MeleeRoundTeamBye.objects.select_for_update()
                    .filter(tournament=tournament, round=next_round_obj)
                    .first()
                )
                if existing_bye and existing_bye.team_id != planned_bye_team.id:
                    return {
                        "success": False,
                        "players_shuffled": 0,
                        "teams_affected": 0,
                        "message": (
                            "The next Snake Draft Round already has a different planned team BYE."
                        ),
                    }

            legacy_projection = (
                tournament.melee_roster_mode
                == tournament.MELEE_ROSTER_MODE_LEGACY
            )
            assignment_input_by_player_id = {
                input_data.player.id: input_data
                for input_data in assignment_inputs
            }
            for melee_player in melee_players:
                input_data = assignment_input_by_player_id[melee_player.player_id]
                assigned_team = input_data.team
                melee_player.assigned_team = assigned_team
                melee_player.save(update_fields=["assigned_team"])
                if assigned_team is not None and legacy_projection:
                    # Existing pre-P4 events retain their old mutable
                    # projection until safe legacy restoration.
                    melee_player.player.team = assigned_team
                    melee_player.player.save(update_fields=["team"])
                    refresh_legacy_player_team_session(
                        melee_player.player,
                        assigned_team,
                        in_melee_assignment=True,
                    )

            assignment_rows = MeleeRoundAssignmentWriter.write_complete_round(
                tournament=tournament,
                round=next_round_obj,
                assignments=assignment_inputs,
            )

            if completed_round_bye_team_id is not None:
                MeleeRoundTeamBye.objects.get_or_create(
                    tournament=tournament,
                    round=completed_round_obj,
                    defaults={"team_id": completed_round_bye_team_id},
                )
            if planned_bye_team is not None:
                MeleeRoundTeamBye.objects.get_or_create(
                    tournament=tournament,
                    round=next_round_obj,
                    defaults={"team": planned_bye_team},
                )

            partnerships_created = MeleePartnership.record_partnerships_for_round(
                tournament,
                round_obj=next_round_obj,
            )
            shuffle_record = MeleeShuffleHistory.objects.create(
                tournament=tournament,
                round_number=completed_round_number,
                round=completed_round_obj,
                shuffle_type=shuffle_type,
                shuffled_by=shuffled_by,
                players_shuffled=players_shuffled,
                notes=(
                    f"{shuffle_description} of {players_shuffled} players across "
                    f"{teams_affected} teams after round {completed_round_number}, ready "
                    f"for round {next_round_number}."
                ),
            )
            logger.info(
                "%s shuffled %s registered Mêlée Players across %s Teams; wrote %s "
                "assignments for Round %s and %s partnership rows%s.",
                "Legacy-compatible Mêlée" if legacy_projection else "P4",
                players_shuffled,
                teams_affected,
                len(assignment_rows),
                next_round_obj.id,
                partnerships_created,
                " with its retained Player.team projection" if legacy_projection else " without Player.team writes",
            )
            return {
                "success": True,
                "players_shuffled": players_shuffled,
                "teams_affected": teams_affected,
                "message": (
                    f"Successfully shuffled {players_shuffled} players across {teams_affected} teams"
                ),
                "shuffle_record_id": shuffle_record.id,
                "round_id": next_round_obj.id,
            }
    except Exception as exc:
        logger.error("Error shuffling Mêlée players for tournament %s: %s", tournament.id, exc)
        return {
            "success": False,
            "players_shuffled": 0,
            "teams_affected": 0,
            "message": f"Error: {exc}",
        }


def check_if_specific_round_complete(tournament, round_obj):
    """Return whether every Match for one concrete Round is completed."""
    from matches.models import Match

    try:
        matches = Match.objects.filter(round=round_obj)
        return matches.exists() and not matches.exclude(status="completed").exists()
    except Exception as exc:
        logger.error("Error checking round completion: %s", exc)
        return False
