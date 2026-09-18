"""Match-scoped Mêlée roster and side resolution for P3.

P4 keeps Mêlée readers and writers assignment-based. Player.team remains a
Player's normal affiliation; it is only a compatibility fallback for genuine
pre-P2 historical Match data. The helpers here always apply this precedence
for one concrete Match:

1. MatchPlayer: immutable player-side snapshot for this Match;
2. MeleeRoundAssignment: exact Tournament + Round assignment for an
   unactivated/pre-snapshot Mêlée Match;
3. Player.team / Team.players: explicit compatibility fallback only when this
   Match has no P2 assignment dataset.

Never resolve a Mêlée Round from a numeric value or current_round_number.
"""

import logging

from teams.models import Player
from tournaments.melee_roster import MeleeRoundRosterService
from tournaments.models import MeleeRoundAssignment

from .models import MatchPlayer

logger = logging.getLogger(__name__)


ASSIGNED = MeleeRoundAssignment.ASSIGNED


def _match_side_ids(match):
    """Return valid non-null Team IDs for a Match."""
    return {team_id for team_id in (match.team1_id, match.team2_id) if team_id}


def is_melee_assignment_match(match):
    """Whether this Match has a concrete P3 Mêlée round context."""
    return bool(
        match
        and match.tournament_id
        and match.round_id
        and getattr(match.tournament, "is_melee", False)
    )


def has_round_assignment_dataset(match):
    """Return whether P2 data exists for the Match's exact Mêlée Round.

    This matters because an explicit non-assignment (or a missing row in an
    otherwise written assignment dataset) must not revive a Player through the
    mutable legacy projection.  A truly pre-P2 / legacy Match still receives
    the final compatibility fallback.
    """
    if not is_melee_assignment_match(match):
        return False
    return MeleeRoundAssignment.objects.filter(
        tournament_id=match.tournament_id,
        round_id=match.round_id,
    ).exists()


def resolve_player_match_side(match, player):
    """Resolve *player*'s side for one Match using P3 precedence.

    ``None`` means that the player has no actionable side for this Match.  In
    particular, an explicit bye/waitlisted/withdrawn assignment or an invalid
    snapshot is fail-closed; it never falls through to Player.team.
    """
    if not match or not player:
        return None

    side_ids = _match_side_ids(match)
    if not side_ids:
        return None

    match_player = (
        MatchPlayer.objects.filter(match_id=match.id, player_id=player.id)
        .select_related("team")
        .first()
    )
    if match_player is not None:
        if match_player.team_id in side_ids:
            return match_player.team
        logger.warning(
            "MatchPlayer %s has Team %s outside Match %s sides; refusing side fallback.",
            match_player.id,
            match_player.team_id,
            match.id,
        )
        return None

    if is_melee_assignment_match(match):
        assignment = MeleeRoundRosterService.assignment_for_player(
            tournament=match.tournament,
            round=match.round,
            player=player,
        )
        if assignment is not None:
            if assignment.state == ASSIGNED and assignment.team_id in side_ids:
                return assignment.team
            # This is explicit Mêlée state. Do not reinterpret it through the
            # current global Player.team compatibility projection.
            return None
        if has_round_assignment_dataset(match):
            logger.warning(
                "Mêlée Match %s has assignment data but no row for Player %s; "
                "refusing Player.team fallback.",
                match.id,
                player.id,
            )
            return None

    # P3 final compatibility fallback: non-Mêlée Matches and Mêlée Matches
    # created before P2 data existed continue to behave exactly as before.
    if player.team_id in side_ids:
        return player.team
    return None


def players_for_match_team(match, team):
    """Return the roster for exactly one Match side as a Player queryset.

    A side can have MatchPlayer snapshots while its opponent is still pending.
    Resolution is therefore intentionally per-side, rather than merely asking
    whether the Match has any MatchPlayer rows.
    """
    if not match or not team or team.id not in _match_side_ids(match):
        return Player.objects.none()

    snapshot_player_ids = MatchPlayer.objects.filter(
        match_id=match.id,
        team_id=team.id,
    ).values_list("player_id", flat=True)
    if snapshot_player_ids.exists():
        return Player.objects.filter(pk__in=snapshot_player_ids).order_by("name", "id")

    if is_melee_assignment_match(match):
        if has_round_assignment_dataset(match):
            return MeleeRoundRosterService.players_for_team(
                tournament=match.tournament,
                round=match.round,
                team=team,
            )

    # No snapshot and no P2 dataset: preserve legacy Team roster behavior.
    return Player.objects.filter(team_id=team.id).order_by("name", "id")


def players_for_match(match):
    """Return all resolved side rosters with Player IDs de-duplicated."""
    players_by_id = {}
    for team in (match.team1, match.team2):
        if team is None:
            continue
        for player in players_for_match_team(match, team):
            players_by_id[player.id] = player
    return list(players_by_id.values())
