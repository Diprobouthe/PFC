"""
VS Mode utility functions for the PFC petanque platform.

VS is isolated from all other tournament flows.  A VS tournament registers
exactly two teams, then creates a configurable number of pending matches.
Each match receives its actual format and VS point value only when both teams
have selected equal-sized lineups at match start.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.db import transaction

if TYPE_CHECKING:
    from tournaments.models import VSEncounter

logger = logging.getLogger("tournaments.vs_mode")


# ---------------------------------------------------------------------------
# VS configuration and format scoring
# ---------------------------------------------------------------------------

DEFAULT_VS_NUM_MATCHES = 11

# Match.MATCH_TYPE_CHOICES value -> VS leaderboard points awarded to a win.
VS_POINTS_BY_MATCH_TYPE = {
    "tete_a_tete": 2,
    "doublet": 3,
    "triplet": 5,
}


def is_vs_tournament(tournament) -> bool:
    """Return whether a tournament uses the VS Independent Games flow.

    The explicit format is authoritative for new records. The JSON marker is
    retained only so historical VS tournaments remain compatible after upgrade.
    """
    if getattr(tournament, "format", None) == "independent_games":
        return True
    config = getattr(tournament, "allowed_match_types", None) or {}
    return bool(config.get("vs_mode"))


def get_vs_num_matches(tournament, default: int = DEFAULT_VS_NUM_MATCHES) -> int:
    """Read a validated pending-match count from the tournament's VS config."""
    config = getattr(tournament, "allowed_match_types", None) or {}
    try:
        num_matches = int(config.get("vs_num_matches", default))
    except (TypeError, ValueError):
        return default
    return num_matches if num_matches >= 1 else default


def get_vs_points_for_match_type(match_type: str | None) -> int | None:
    """Return the VS point value for a completed match format, if supported."""
    return VS_POINTS_BY_MATCH_TYPE.get(match_type)


def apply_vs_match_format(match, match_type: str, team1_count: int, team2_count: int) -> None:
    """Set a VS match's final format and point value after lineup validation.

    VS accepts only equal 1v1, 2v2, or 3v3 lineups.  The caller is responsible
    for saving the ``Match`` alongside any other activation state.
    """
    if not getattr(match, "vs_encounter_id", None):
        return
    if team1_count != team2_count:
        raise ValueError("VS matches require the same number of players on both teams.")
    points_value = get_vs_points_for_match_type(match_type)
    if points_value is None:
        raise ValueError("VS matches must be 1v1, 2v2, or 3v3.")
    match.vs_points_value = points_value


# ---------------------------------------------------------------------------
# Pending-match generation
# ---------------------------------------------------------------------------

@transaction.atomic
def generate_vs_pending_matches(
    encounter: "VSEncounter", num_matches: int | None = None
) -> list:
    """Create the open-format pending matches for a VS encounter.

    The generator intentionally does not preselect ``match_type`` or
    ``vs_points_value``.  Those fields are populated at match activation once
    equal 1v1, 2v2, or 3v3 lineups are known.  Repeated calls are idempotent:
    an encounter that already has matches is returned unchanged.
    """
    from matches.models import Match  # local import to avoid circular deps

    if num_matches is None:
        num_matches = get_vs_num_matches(encounter.tournament)
    try:
        num_matches = int(num_matches)
    except (TypeError, ValueError) as exc:
        raise ValueError("The VS number of matches must be a positive integer.") from exc
    if num_matches < 1:
        raise ValueError("The VS number of matches must be at least 1.")

    existing_matches = list(
        Match.objects.select_for_update()
        .filter(vs_encounter=encounter)
        .order_by("id")
    )
    if existing_matches:
        return existing_matches

    created_matches: list[Match] = []
    for _ in range(num_matches):
        match = Match.objects.create(
            tournament=encounter.tournament,
            team1=encounter.team1,
            team2=encounter.team2,
            status="pending",
            match_type=None,
            vs_encounter=encounter,
            vs_points_value=None,
            vs_lineup_team1_locked=False,
            vs_lineup_team2_locked=False,
            time_limit_minutes=getattr(encounter.tournament, "default_time_limit_minutes", None),
        )
        created_matches.append(match)

    logger.info(
        "Created %d open-format VS matches: encounter_id=%s %s vs %s",
        len(created_matches),
        encounter.pk,
        encounter.team1.name,
        encounter.team2.name,
    )
    return created_matches


# Compatibility wrapper for historical code paths.  It now creates the
# tournament's configurable open-format VS matches rather than a fixed mix.
def generate_vs_sub_games(encounter: "VSEncounter") -> list:
    return generate_vs_pending_matches(encounter)


# ---------------------------------------------------------------------------
# Point accumulation
# ---------------------------------------------------------------------------

@transaction.atomic
def update_vs_encounter_points(encounter: "VSEncounter") -> None:
    """Recalculate the two teams' VS totals from completed encounter matches.

    A pending open-format match has a null ``vs_points_value`` and therefore
    contributes nothing.  At activation, its format is determined and its
    value is set to 2, 3, or 5.  This function consequently remains safe for
    both live encounters and historical completed VS matches.
    """
    from matches.models import Match

    sub_games = Match.objects.filter(vs_encounter=encounter)

    team1_pts = 0
    team2_pts = 0
    all_complete = True

    for match in sub_games:
        if match.status != "completed":
            all_complete = False
            continue
        pts_value = match.vs_points_value or 0
        if match.winner_id == encounter.team1_id:
            team1_pts += pts_value
        elif match.winner_id == encounter.team2_id:
            team2_pts += pts_value
        # Draws award no VS points.

    encounter.team1_points = team1_pts
    encounter.team2_points = team2_pts
    encounter.is_complete = all_complete
    encounter.save(update_fields=["team1_points", "team2_points", "is_complete", "updated_at"])

    logger.info(
        "VSEncounter %s updated: team1=%s (%d pts) team2=%s (%d pts) complete=%s",
        encounter.pk,
        encounter.team1.name,
        team1_pts,
        encounter.team2.name,
        team2_pts,
        all_complete,
    )

    # Propagate to TournamentTeam.vs_points for both teams.
    _update_tournament_team_vs_points(encounter.tournament, encounter.team1)
    _update_tournament_team_vs_points(encounter.tournament, encounter.team2)


def _update_tournament_team_vs_points(tournament, team) -> None:
    """Recompute one registered team's VS total across its encounters."""
    from tournaments.models import TournamentTeam, VSEncounter

    total = 0
    encounters = VSEncounter.objects.filter(tournament=tournament).filter(
        models_Q(team1=team) | models_Q(team2=team)
    )
    for enc in encounters:
        if enc.team1_id == team.pk:
            total += enc.team1_points
        else:
            total += enc.team2_points

    TournamentTeam.objects.filter(tournament=tournament, team=team).update(
        vs_points=total
    )
    logger.debug(
        "TournamentTeam vs_points updated: tournament=%s team=%s total=%d",
        tournament.pk,
        team.name,
        total,
    )


# ---------------------------------------------------------------------------
# Lazy Q import (avoids a module-level circular import)
# ---------------------------------------------------------------------------

def models_Q(*args, **kwargs):
    from django.db.models import Q
    return Q(*args, **kwargs)
