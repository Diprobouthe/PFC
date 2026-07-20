"""
VS Mode utility functions for the PFC petanque platform.

This module is the single source of truth for:
  - VS Mode configuration defaults and validation
  - Sub-game generation from a VSEncounter
  - Point accumulation after a sub-game completes
  - TournamentTeam.vs_points update

These utilities are intentionally isolated from all existing Mêlée, Super Mêlée,
Regular Teams, and Friendly Game flows.  Nothing in this file touches those code
paths.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.db import transaction

if TYPE_CHECKING:
    from tournaments.models import VSEncounter

logger = logging.getLogger("tournaments.vs_mode")

# ---------------------------------------------------------------------------
# Default VS Mode configuration
# ---------------------------------------------------------------------------

DEFAULT_VS_CONFIG = {
    "games": [
        {"format": "tete_a_tete", "count": 6, "points_per_win": 2},
        {"format": "doublets",    "count": 3, "points_per_win": 3},
        {"format": "triplets",    "count": 2, "points_per_win": 5},
    ]
}

# Map VS config format names → Match.MATCH_TYPE_CHOICES keys
_FORMAT_TO_MATCH_TYPE = {
    "tete_a_tete": "tete_a_tete",
    "doublets":    "doublet",
    "triplets":    "triplet",
}


# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------

def get_vs_config(scenario) -> dict:
    """
    Return the resolved VS config dict for a TournamentScenario.

    Falls back to DEFAULT_VS_CONFIG if the scenario has no vs_config set or
    if it is set to None / empty.
    """
    if scenario is None:
        return DEFAULT_VS_CONFIG

    cfg = getattr(scenario, "vs_config", None)
    if not cfg or not isinstance(cfg, dict) or "games" not in cfg:
        return DEFAULT_VS_CONFIG

    return cfg


def validate_vs_config(cfg: dict) -> list[str]:
    """
    Validate a VS config dict.  Returns a list of error strings (empty = valid).
    """
    errors: list[str] = []
    if not isinstance(cfg, dict):
        return ["vs_config must be a JSON object"]

    games = cfg.get("games")
    if not isinstance(games, list) or not games:
        errors.append("vs_config.games must be a non-empty list")
        return errors

    valid_formats = set(_FORMAT_TO_MATCH_TYPE.keys())
    for i, entry in enumerate(games):
        if not isinstance(entry, dict):
            errors.append(f"games[{i}] must be an object")
            continue
        fmt = entry.get("format")
        if fmt not in valid_formats:
            errors.append(
                f"games[{i}].format '{fmt}' is not valid; "
                f"must be one of {sorted(valid_formats)}"
            )
        count = entry.get("count")
        if not isinstance(count, int) or count < 1:
            errors.append(f"games[{i}].count must be a positive integer")
        pts = entry.get("points_per_win")
        if not isinstance(pts, int) or pts < 1:
            errors.append(f"games[{i}].points_per_win must be a positive integer")

    return errors


# ---------------------------------------------------------------------------
# Sub-game generation
# ---------------------------------------------------------------------------

@transaction.atomic
def generate_vs_sub_games(encounter: "VSEncounter") -> list:
    """
    Create all Match sub-games for a VSEncounter.

    Sub-games are created in the order defined by vs_config (Tête-à-tête first,
    then Doubles, then Triples).  Each sub-game is linked back to the encounter
    via Match.vs_encounter and carries the point value for that format in
    Match.vs_points_value.

    Returns the list of newly created Match objects.

    Raises ValueError if the encounter's tournament has no associated
    TournamentScenario (via SimpleTournament) or if the config is invalid.
    """
    from matches.models import Match  # local import to avoid circular deps

    # Resolve the scenario and config
    tournament = encounter.tournament
    scenario = _get_scenario_for_tournament(tournament)
    cfg = get_vs_config(scenario)

    errors = validate_vs_config(cfg)
    if errors:
        raise ValueError(f"Invalid VS config: {'; '.join(errors)}")

    created_matches: list[Match] = []

    for game_def in cfg["games"]:
        fmt = game_def["format"]
        count = game_def["count"]
        pts = game_def["points_per_win"]
        match_type = _FORMAT_TO_MATCH_TYPE[fmt]

        for _ in range(count):
            match = Match.objects.create(
                tournament=tournament,
                team1=encounter.team1,
                team2=encounter.team2,
                status="pending",
                match_type=match_type,
                vs_encounter=encounter,
                vs_points_value=pts,
                vs_lineup_team1_locked=False,
                vs_lineup_team2_locked=False,
                time_limit_minutes=getattr(tournament, "default_time_limit_minutes", None),
            )
            created_matches.append(match)
            logger.info(
                "VS sub-game created: match_id=%s  encounter_id=%s  "
                "format=%s  pts=%s  %s vs %s",
                match.pk,
                encounter.pk,
                fmt,
                pts,
                encounter.team1.name,
                encounter.team2.name,
            )

    return created_matches


def _get_scenario_for_tournament(tournament):
    """
    Try to retrieve the TournamentScenario linked to a Tournament via
    SimpleTournament.  Returns None if no link exists (config will fall back
    to DEFAULT_VS_CONFIG).
    """
    try:
        from simple_creator.models import SimpleTournament
        st = SimpleTournament.objects.select_related("scenario").get(
            tournament=tournament
        )
        return st.scenario
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Point accumulation
# ---------------------------------------------------------------------------

@transaction.atomic
def update_vs_encounter_points(encounter: "VSEncounter") -> None:
    """
    Recalculate and save team1_points / team2_points for a VSEncounter by
    summing vs_points_value from all completed sub-games.

    Also marks encounter.is_complete=True when every sub-game is done, and
    updates TournamentTeam.vs_points for both teams.

    This function is idempotent — safe to call multiple times.
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
        # draws award 0 points to either side

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

    # Propagate to TournamentTeam.vs_points for both teams
    _update_tournament_team_vs_points(encounter.tournament, encounter.team1)
    _update_tournament_team_vs_points(encounter.tournament, encounter.team2)


def _update_tournament_team_vs_points(tournament, team) -> None:
    """
    Recompute and save TournamentTeam.vs_points for one team in a tournament
    by summing all VSEncounter points where the team participated.
    """
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
        "TournamentTeam vs_points updated: tournament=%s  team=%s  total=%d",
        tournament.pk,
        team.name,
        total,
    )


# ---------------------------------------------------------------------------
# Lazy Q import (avoids circular import at module level)
# ---------------------------------------------------------------------------

def models_Q(*args, **kwargs):
    from django.db.models import Q
    return Q(*args, **kwargs)
