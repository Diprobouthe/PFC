"""Compatibility synchronization for legacy Mêlée assignment state.

P4 uses exact ``MeleeRoundAssignment`` rows and this helper becomes a no-op.
Only a persisted pre-P4 ``legacy_transferred`` tournament may still repair its
old mutable Player.team projection from historic partnership data.
"""

import logging
from collections import defaultdict

from django.db import transaction

logger = logging.getLogger("tournaments")


def sync_team_assignments_with_partnerships(tournament, round_number):
    """Synchronize a legacy Mêlée projection; skip P4 immutable assignments.

    Partnership records have only a numeric round identifier, so this remains a
    conservative compatibility hook. It updates only a registered Player whose
    partnership Team name resolves to a unique enrolled temporary Team. P4's
    concrete Round roster remains the authoritative reader source.
    """
    from tournaments.models import MeleePlayer, TournamentTeam
    from tournaments.partnership_models import MeleePartnership
    from pfc_core.session_refresh import refresh_legacy_player_team_session

    if not tournament.is_melee:
        return {
            "success": False,
            "players_moved": 0,
            "teams_fixed": 0,
            "message": "Tournament is not in Mêlée mode",
        }
    if tournament.melee_roster_mode == tournament.MELEE_ROSTER_MODE_ASSIGNMENT:
        # Exact MeleeRoundAssignment rows are immutable P4 history; a lossy
        # partnership display record must never rewrite current assignment.
        return {
            "success": True,
            "players_moved": 0,
            "teams_fixed": 0,
            "assignment_updates": 0,
            "message": "P4 Mêlée uses exact round assignments; partnership synchronization skipped.",
        }

    try:
        with transaction.atomic():
            partnerships = list(
                MeleePartnership.objects.filter(
                    tournament=tournament,
                    round_number=round_number,
                ).select_related("player1", "player2")
            )
            if not partnerships:
                return {
                    "success": False,
                    "players_moved": 0,
                    "teams_fixed": 0,
                    "message": f"No partnerships found for round {round_number}",
                }

            teams_by_name = {}
            duplicate_names = set()
            for tournament_team in TournamentTeam.objects.filter(
                tournament=tournament,
                team__is_tournament_temp=True,
            ).select_related("team"):
                name = tournament_team.team.name
                if name in teams_by_name:
                    duplicate_names.add(name)
                else:
                    teams_by_name[name] = tournament_team.team

            player_team_by_id = {}
            for partnership in partnerships:
                if partnership.team_name in duplicate_names:
                    logger.warning(
                        "Cannot synchronize ambiguous Mêlée Team name %s in tournament %s.",
                        partnership.team_name,
                        tournament.id,
                    )
                    continue
                team = teams_by_name.get(partnership.team_name)
                if team is None:
                    continue
                for player in (partnership.player1, partnership.player2):
                    existing = player_team_by_id.get(player.id)
                    if existing is not None and existing.id != team.id:
                        logger.warning(
                            "Player %s has conflicting partnership Teams for round %s; "
                            "leaving tournament assignment unchanged.",
                            player.id,
                            round_number,
                        )
                        player_team_by_id[player.id] = None
                    elif existing is None and player.id not in player_team_by_id:
                        player_team_by_id[player.id] = team

            updates = 0
            affected_team_ids = set()
            registrations = MeleePlayer.objects.select_for_update().select_related(
                "player"
            ).filter(
                tournament=tournament,
                player_id__in=player_team_by_id,
            )
            for registration in registrations:
                assigned_team = player_team_by_id.get(registration.player_id)
                if assigned_team is None:
                    continue
                if registration.assigned_team_id != assigned_team.id:
                    registration.assigned_team = assigned_team
                    registration.save(update_fields=["assigned_team"])
                    updates += 1
                    affected_team_ids.add(assigned_team.id)
                if registration.player.team_id != assigned_team.id:
                    # The mode marker is the required compatibility boundary.
                    # This branch must never execute for P4 tournaments.
                    registration.player.team = assigned_team
                    registration.player.save(update_fields=["team"])
                    refresh_legacy_player_team_session(
                        registration.player,
                        assigned_team,
                        in_melee_assignment=True,
                    )
                    affected_team_ids.add(assigned_team.id)

            return {
                "success": True,
                # Key retained for compatibility with existing callers.
                "players_moved": 0,
                "teams_fixed": len(affected_team_ids),
                "assignment_updates": updates,
                "message": (
                    f"Synchronized {updates} tournament assignment records across "
                    f"{len(affected_team_ids)} legacy teams for round {round_number}"
                ),
            }
    except Exception as exc:
        logger.error("Error synchronizing Mêlée assignments: %s", exc)
        return {
            "success": False,
            "players_moved": 0,
            "teams_fixed": 0,
            "message": f"Error: {exc}",
        }


def sync_all_rounds(tournament):
    """Run conservative compatibility synchronization across partnership rounds."""
    from tournaments.partnership_models import MeleePartnership

    round_numbers = (
        MeleePartnership.objects.filter(tournament=tournament)
        .values_list("round_number", flat=True)
        .distinct()
        .order_by("round_number")
    )
    results = [
        sync_team_assignments_with_partnerships(tournament, round_number)
        for round_number in round_numbers
    ]
    successful = [result for result in results if result["success"]]
    return {
        "success": True,
        "rounds_synced": len(successful),
        "players_moved": 0,
        "teams_fixed": sum(result["teams_fixed"] for result in successful),
        "assignment_updates": sum(
            result.get("assignment_updates", 0) for result in successful
        ),
        "message": f"Synchronized {len(successful)} legacy Mêlée assignment rounds",
    }
