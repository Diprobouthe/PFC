"""
Swiss Tournament Ranking System with Buchholz Tie-Breaking
"""

import logging
from django.db.models import Q, F, Sum
from tournaments.models import Tournament, TournamentTeam, Stage
from matches.models import Match

logger = logging.getLogger(__name__)

def is_swiss_tournament(tournament):
    """Check if a tournament uses Swiss system (regular or smart)"""
    if tournament.format in ['swiss', 'smart_swiss']:
        return True
    
    # Check if any stage uses Swiss system
    if tournament.format == 'multi_stage':
        swiss_stages = tournament.stages.filter(format__in=['swiss', 'smart_swiss'])
        return swiss_stages.exists()
    
    return False

def is_wtf_tournament(tournament):
    """Check if a tournament uses WTF system"""
    if tournament.format == 'wtf':
        return True
    
    # Check if any stage uses WTF system
    if tournament.format == 'multi_stage':
        wtf_stages = tournament.stages.filter(format='wtf')
        return wtf_stages.exists()
    
    return False

def _scoped_tournament_teams(tournament, stage=None):
    queryset = TournamentTeam.objects.filter(tournament=tournament, is_active=True).select_related("team")
    if stage:
        queryset = queryset.filter(current_stage_number=stage.stage_number)
    return list(queryset)


def _scoped_completed_matches(tournament, stage=None):
    queryset = Match.objects.filter(tournament=tournament, status="completed").select_related("team1", "team2")
    if stage:
        queryset = queryset.filter(stage=stage)
    return list(queryset)


def _batched_team_stats(tournament, stage=None):
    """Return active records, completed Matches, and one-pass side statistics."""
    tournament_teams = _scoped_tournament_teams(tournament, stage)
    stats = {
        row.team_id: {"played": 0, "won": 0, "scored": 0, "conceded": 0}
        for row in tournament_teams
    }
    matches = _scoped_completed_matches(tournament, stage)
    for match in matches:
        for own_id, opponent_id, own_score, opponent_score in (
            (match.team1_id, match.team2_id, match.team1_score, match.team2_score),
            (match.team2_id, match.team1_id, match.team2_score, match.team1_score),
        ):
            if own_id not in stats:
                continue
            entry = stats[own_id]
            entry["played"] += 1
            entry["scored"] += own_score or 0
            entry["conceded"] += opponent_score or 0
            entry["won"] += int(match.winner_id == own_id)
    return tournament_teams, matches, stats


def update_all_swiss_points(tournament, stage=None):
    """Publish Swiss points with two bounded queries and one bulk update."""
    tournament_teams, matches, _stats = _batched_team_stats(tournament, stage)
    wins = {row.team_id: 0 for row in tournament_teams}
    for match in matches:
        if match.winner_id in wins:
            wins[match.winner_id] += 1
    for row in tournament_teams:
        row.swiss_points = wins[row.team_id] * 3 + (3 if row.received_bye_in_round is not None else 0)
    if tournament_teams:
        TournamentTeam.objects.bulk_update(tournament_teams, ["swiss_points"], batch_size=250)
    logger.info("Published Swiss points for %s teams", len(tournament_teams))


def calculate_buchholz_scores(tournament, stage=None):
    """Publish Buchholz from one loaded Match set; no per-team queries."""
    tournament_teams, matches, _stats = _batched_team_stats(tournament, stage)
    points = {row.team_id: row.swiss_points for row in tournament_teams}
    scores = {team_id: 0.0 for team_id in points}
    for match in matches:
        if match.team1_id in scores and match.team2_id in points:
            scores[match.team1_id] += points[match.team2_id]
        if match.team2_id in scores and match.team1_id in points:
            scores[match.team2_id] += points[match.team1_id]
    for row in tournament_teams:
        if row.received_bye_in_round:
            scores[row.team_id] += points[row.team_id]
        row.buchholz_score = scores[row.team_id]
    if tournament_teams:
        TournamentTeam.objects.bulk_update(tournament_teams, ["buchholz_score"], batch_size=250)
    logger.info("Published Buchholz scores for %s teams", len(tournament_teams))


def get_swiss_rankings(tournament, stage=None):
    """Read the most recently published Swiss projection without mutation."""
    tournament_teams, _matches, stats = _batched_team_stats(tournament, stage)
    tournament_teams.sort(
        key=lambda row: (row.swiss_points, row.buchholz_score, row.id), reverse=True
    )
    rankings = []
    for position, row in enumerate(tournament_teams, 1):
        data = stats[row.team_id]
        rankings.append({
            "position": position,
            "team": row.team,
            "tournament_team": row,
            "swiss_points": row.swiss_points,
            "buchholz_score": row.buchholz_score,
            "matches_played": data["played"],
            "matches_won": data["won"],
            "matches_lost": data["played"] - data["won"],
            "points_scored": data["scored"],
            "points_conceded": data["conceded"],
            "point_difference": data["scored"] - data["conceded"],
        })
    return rankings


def get_stage_rankings(tournament, stage_number):
    try:
        stage = tournament.stages.get(stage_number=stage_number)
    except Stage.DoesNotExist:
        logger.error("Stage %s not found for Tournament %s", stage_number, tournament.id)
        return []
    return get_swiss_rankings(tournament, stage) if stage.format in ["swiss", "smart_swiss"] else get_traditional_rankings(tournament, stage)


def get_traditional_rankings(tournament, stage=None):
    """Read batch-computed traditional standings without per-team queries."""
    tournament_teams, _matches, stats = _batched_team_stats(tournament, stage)
    rankings = []
    for row in tournament_teams:
        data = stats[row.team_id]
        rankings.append({
            "team": row.team,
            "tournament_team": row,
            "matches_played": data["played"],
            "matches_won": data["won"],
            "matches_lost": data["played"] - data["won"],
            "points_scored": data["scored"],
            "points_conceded": data["conceded"],
            "point_difference": data["scored"] - data["conceded"],
        })
    rankings.sort(key=lambda item: (item["matches_won"], item["point_difference"], item["points_scored"]), reverse=True)
    for position, ranking in enumerate(rankings, 1):
        ranking["position"] = position
    return rankings


# ---------------------------------------------------------------------------
# Multi-stage global leaderboard
# ---------------------------------------------------------------------------

def is_multistage_team_tournament(tournament):
    """
    Return True only for multi-stage tournaments that are NOT mêlée / super-mêlée.
    Mêlée and super-mêlée use player-based leaderboards and must not be affected.
    """
    if tournament.format != 'multi_stage':
        return False
    # Exclude mêlée formats
    if getattr(tournament, 'is_melee', False):
        return False
    return True


def _determine_team_status(team, tournament, stages, current_stage_number):
    """
    Determine the display status of a team in a multi-stage tournament.

    Rules:
    - If the team's current_stage_number equals the highest stage, and
      the tournament has a completed final stage with a winner, mark as champion.
    - If the team advanced to the last stage but did not win, mark as finalist
      (for 2-team finals) or semi-finalist (for 4-team semi-finals).
    - If the team did not advance beyond their initial stage, mark as eliminated
      with the stage name.
    - If the tournament is still in progress and the team is still active,
      mark as active.
    """
    from matches.models import Match

    max_stage = max(s.stage_number for s in stages) if stages else 1
    team_stage = team.current_stage_number

    # Check if team is still active in the tournament
    if team.is_active and team_stage == current_stage_number:
        return 'active'

    # Team did not advance beyond their stage → eliminated
    if team_stage < max_stage:
        stage_obj = next((s for s in stages if s.stage_number == team_stage), None)
        stage_name = stage_obj.name if stage_obj else f"Stage {team_stage}"
        return f'eliminated ({stage_name})'

    # Team reached the final stage
    final_stage = next((s for s in stages if s.stage_number == max_stage), None)
    if final_stage:
        # Check if there's a winner in the final stage
        final_matches = Match.objects.filter(
            tournament=tournament,
            stage=final_stage,
            status='completed'
        )
        if final_matches.exists():
            # Find the champion (team that won the most final-stage matches)
            wins = {}
            for m in final_matches:
                if m.winner:
                    wins[m.winner_id] = wins.get(m.winner_id, 0) + 1
            if wins:
                champion_id = max(wins, key=wins.get)
                if team.team_id == champion_id:
                    return 'champion'
                # Finalist = reached final stage but did not win
                stage_teams_count = tournament.tournamentteam_set.filter(
                    current_stage_number=max_stage
                ).count()
                if stage_teams_count <= 2:
                    return 'finalist'
                return 'semi-finalist'

    return 'active'


def get_global_multistage_rankings(tournament):
    """
    Build a unified global leaderboard for a multi-stage team tournament.

    Strategy
    --------
    1. Collect ALL TournamentTeam records for this tournament (no is_active filter).
    2. For each team, aggregate stats across ALL stages they participated in.
    3. Determine the team's status (active / eliminated / champion / finalist).
    4. Sort by:
       a. Stage reached (desc) — teams that advanced further rank higher
       b. Swiss points (desc) — primary tie-breaker within same stage
       c. Buchholz score (desc) — secondary tie-breaker
       d. Point difference (desc) — tertiary tie-breaker
    5. Return a list of ranking dicts compatible with the existing leaderboard
       entry creation code.
    """
    logger.info(f"Building global multi-stage rankings for tournament {tournament.name}")

    stages = list(tournament.stages.order_by('stage_number'))
    if not stages:
        logger.warning(f"No stages found for tournament {tournament.name}")
        return []

    max_stage = max(s.stage_number for s in stages)
    current_stage_number = max_stage  # The highest stage that has matches

    # Get ALL tournament teams — do NOT filter by is_active or current_stage_number
    all_tournament_teams = tournament.tournamentteam_set.select_related('team').all()

    rankings = []
    for team_tt in all_tournament_teams:
        # Aggregate stats across ALL stages this team participated in
        from matches.models import Match
        from django.db.models import Q

        team_matches = Match.objects.filter(
            tournament=tournament,
            status='completed'
        ).filter(Q(team1=team_tt.team) | Q(team2=team_tt.team))

        matches_played = team_matches.count()
        matches_won = team_matches.filter(winner=team_tt.team).count()
        matches_lost = matches_played - matches_won

        points_scored = 0
        points_conceded = 0
        for match in team_matches:
            if match.team1_id == team_tt.team_id:
                points_scored += match.team1_score or 0
                points_conceded += match.team2_score or 0
            else:
                points_scored += match.team2_score or 0
                points_conceded += match.team1_score or 0

        # Determine status
        status = _determine_team_status(team_tt, tournament, stages, current_stage_number)

        rankings.append({
            'team': team_tt.team,
            'tournament_team': team_tt,
            'stage_reached': team_tt.current_stage_number,
            'tournament_status': status,
            'swiss_points': team_tt.swiss_points,
            'buchholz_score': team_tt.buchholz_score,
            'matches_played': matches_played,
            'matches_won': matches_won,
            'matches_lost': matches_lost,
            'points_scored': points_scored,
            'points_conceded': points_conceded,
            'point_difference': points_scored - points_conceded,
        })

    # Sort: stage_reached desc → swiss_points desc → buchholz desc → point_diff desc
    rankings.sort(key=lambda x: (
        x['stage_reached'],
        x['swiss_points'],
        x['buchholz_score'],
        x['point_difference'],
        x['points_scored'],
    ), reverse=True)

    # Assign positions
    for i, r in enumerate(rankings):
        r['position'] = i + 1

    logger.info(
        f"Global multi-stage rankings: {len(rankings)} teams "
        f"(stages 1–{max_stage})"
    )
    return rankings
