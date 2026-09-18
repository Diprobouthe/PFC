"""Lifecycle helpers for the assignment-based Mêlée P4 cutover.

A new P4 tournament represents temporary competitive rosters exclusively with
``MeleeRoundAssignment`` and ``MeleePlayer.assigned_team``. ``Player.team``
remains the Player's normal affiliation and is never changed by these helpers.

A persisted Tournament roster-mode marker distinguishes genuine old transfers
from P4 records. Existing tournaments default to ``legacy_transferred`` in the
P4 migration; only newly generated P4 tournaments are ``assignment_based``.
"""

from django.db.models import Q


def temporary_team_ids(tournament):
    """Return temporary Team IDs enrolled in one Tournament."""
    from tournaments.models import TournamentTeam

    return set(
        TournamentTeam.objects.filter(
            tournament=tournament,
            team__is_tournament_temp=True,
        ).values_list("team_id", flat=True)
    )


def is_legacy_transferred_melee_tournament(tournament):
    """Whether a legacy Mêlée Player is still physically on a temp Team."""
    if not tournament or not tournament.is_melee:
        return False
    if getattr(tournament, "melee_roster_mode", None) != "legacy_transferred":
        return False

    temp_ids = temporary_team_ids(tournament)
    if not temp_ids:
        return False

    from tournaments.models import MeleePlayer

    return MeleePlayer.objects.filter(
        tournament=tournament,
        player__team_id__in=temp_ids,
    ).exists()


def assignment_inputs_from_melee_players(tournament):
    """Classify every registration from current tournament assignment state."""
    from tournaments.melee_assignments import MeleeRoundAssignmentInput
    from tournaments.models import MeleeRoundAssignment

    inputs = []
    for melee_player in tournament.melee_players.select_related(
        "player", "assigned_team"
    ).order_by("player_id"):
        if melee_player.assigned_team_id:
            inputs.append(
                MeleeRoundAssignmentInput(
                    player=melee_player.player,
                    team=melee_player.assigned_team,
                    state=MeleeRoundAssignment.ASSIGNED,
                )
            )
        else:
            inputs.append(
                MeleeRoundAssignmentInput(
                    player=melee_player.player,
                    team=None,
                    state=MeleeRoundAssignment.WAITLISTED,
                )
            )
    return inputs


def restore_legacy_transferred_melee_players(tournament):
    """Restore only Players physically transferred by a legacy tournament."""
    if not is_legacy_transferred_melee_tournament(tournament):
        return 0

    from pfc_core.session_refresh import refresh_legacy_player_team_session
    from tournaments.models import MeleePlayer

    temp_ids = temporary_team_ids(tournament)
    restored_count = 0
    for melee_player in MeleePlayer.objects.select_related(
        "player", "original_team"
    ).filter(tournament=tournament, player__team_id__in=temp_ids):
        if not melee_player.original_team_id:
            continue
        player = melee_player.player
        player.team = melee_player.original_team
        player.save(update_fields=["team"])
        refresh_legacy_player_team_session(
            player,
            melee_player.original_team,
            in_melee_assignment=False,
        )
        restored_count += 1
    return restored_count


def clear_assignment_context_sessions(players):
    """Stop Mêlée fast polling without replacing normal Team-session identity."""
    from pfc_core.session_refresh import clear_player_melee_assignment_session

    return sum(clear_player_melee_assignment_session(player) for player in players)


def team_has_competition_history(team):
    """Whether deleting a temporary Team would erase or detach PFC history."""
    from matches.models import Match, MatchActivation, MatchPlayer, MatchResult
    from tournaments.models import MeleeRoundAssignment

    return (
        team.players.exists()
        or Match.objects.filter(Q(team1=team) | Q(team2=team)).exists()
        or MatchActivation.objects.filter(team=team).exists()
        or MatchPlayer.objects.filter(team=team).exists()
        or MatchResult.objects.filter(Q(submitted_by=team) | Q(validated_by=team)).exists()
        or MeleeRoundAssignment.objects.filter(team=team).exists()
    )


def delete_unreferenced_temporary_teams(tournament):
    """Delete only provably unreferenced temporary Teams for one Tournament.

    Zero ``Team.players`` is not proof of safety under P4. This helper retains
    all Teams referenced by Matches, assignment history, activation snapshots,
    or result history. It returns `(deleted_count, retained_count)`.
    """
    from tournaments.models import TournamentTeam

    deleted_count = 0
    retained_count = 0
    for tournament_team in TournamentTeam.objects.filter(
        tournament=tournament,
        team__is_tournament_temp=True,
    ).select_related("team"):
        team = tournament_team.team
        if team_has_competition_history(team):
            retained_count += 1
            continue
        tournament_team.delete()
        team.delete()
        deleted_count += 1
    return deleted_count, retained_count
