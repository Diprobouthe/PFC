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

def calculate_buchholz_scores(tournament, stage=None):
    """
    Calculate Buchholz scores for all teams in a tournament or stage.
    Buchholz score = sum of all opponents' Swiss points.
    Must be calculated after all Swiss points are updated.
    """
    logger.info(f"Calculating Buchholz scores for tournament {tournament.name}")
    
    # Get tournament teams
    if stage:
        # For multi-stage tournaments, only consider teams in this stage
        tournament_teams = TournamentTeam.objects.filter(
            tournament=tournament,
            current_stage_number=stage.stage_number,
            is_active=True
        )
        match_filter = Q(tournament=tournament, stage=stage, status='completed')
    else:
        tournament_teams = TournamentTeam.objects.filter(
            tournament=tournament,
            is_active=True
        )
        match_filter = Q(tournament=tournament, status='completed')
    
    # Calculate Buchholz for each team
    for team_tt in tournament_teams:
        buchholz_score = 0.0
        opponents_count = 0
        
        # Get all completed matches for this team
        team_matches = Match.objects.filter(match_filter).filter(
            Q(team1=team_tt.team) | Q(team2=team_tt.team)
        )
        
        for match in team_matches:
            # Determine opponent
            if match.team1 == team_tt.team:
                opponent = match.team2
            else:
                opponent = match.team1
            
            if opponent:
                # Get opponent's tournament team record
                try:
                    if stage:
                        opponent_tt = TournamentTeam.objects.get(
                            tournament=tournament,
                            team=opponent,
                            current_stage_number=stage.stage_number
                        )
                    else:
                        opponent_tt = TournamentTeam.objects.get(
                            tournament=tournament,
                            team=opponent
                        )
                    
                    # Add opponent's Swiss points to Buchholz score
                    buchholz_score += opponent_tt.swiss_points
                    opponents_count += 1
                    
                except TournamentTeam.DoesNotExist:
                    logger.warning(f"Opponent {opponent.name} not found in tournament teams")
                    continue
        
        # Handle bye rounds - typically count as playing against yourself
        if team_tt.received_bye_in_round:
            buchholz_score += team_tt.swiss_points
            opponents_count += 1
        
        # Update Buchholz score
        team_tt.buchholz_score = buchholz_score
        team_tt.save()
        
        logger.debug(f"{team_tt.team.name}: {team_tt.swiss_points} Swiss pts, {buchholz_score} Buchholz ({opponents_count} opponents)")
    
    logger.info(f"Buchholz calculation completed for {tournament_teams.count()} teams")

def get_swiss_rankings(tournament, stage=None):
    """
    Get Swiss tournament rankings with proper tie-breaking.
    Returns teams ordered by: Swiss points (desc), Buchholz score (desc), points scored (desc)
    """
    logger.info(f"Getting Swiss rankings for tournament {tournament.name}")
    
    # First, ensure all Swiss points are up to date
    update_all_swiss_points(tournament, stage)
    
    # Then calculate Buchholz scores
    calculate_buchholz_scores(tournament, stage)
    
    # Get tournament teams with proper ordering
    if stage:
        tournament_teams = TournamentTeam.objects.filter(
            tournament=tournament,
            current_stage_number=stage.stage_number,
            is_active=True
        )
    else:
        tournament_teams = TournamentTeam.objects.filter(
            tournament=tournament,
            is_active=True
        )
    
    # Calculate additional stats for each team
    rankings = []
    for i, team_tt in enumerate(tournament_teams.order_by('-swiss_points', '-buchholz_score', '-id')):
        # Get match statistics
        if stage:
            team_matches = Match.objects.filter(
                tournament=tournament,
                stage=stage,
                status='completed'
            ).filter(Q(team1=team_tt.team) | Q(team2=team_tt.team))
        else:
            team_matches = Match.objects.filter(
                tournament=tournament,
                status='completed'
            ).filter(Q(team1=team_tt.team) | Q(team2=team_tt.team))
        
        matches_played = team_matches.count()
        matches_won = team_matches.filter(winner=team_tt.team).count()
        matches_lost = matches_played - matches_won
        
        # Calculate points scored and conceded
        points_scored = 0
        points_conceded = 0
        
        for match in team_matches:
            if match.team1 == team_tt.team:
                points_scored += match.team1_score or 0
                points_conceded += match.team2_score or 0
            else:
                points_scored += match.team2_score or 0
                points_conceded += match.team1_score or 0
        
        rankings.append({
            'position': i + 1,
            'team': team_tt.team,
            'tournament_team': team_tt,
            'swiss_points': team_tt.swiss_points,
            'buchholz_score': team_tt.buchholz_score,
            'matches_played': matches_played,
            'matches_won': matches_won,
            'matches_lost': matches_lost,
            'points_scored': points_scored,
            'points_conceded': points_conceded,
            'point_difference': points_scored - points_conceded,
        })
    
    logger.info(f"Swiss rankings calculated for {len(rankings)} teams")
    return rankings

def update_all_swiss_points(tournament, stage=None):
    """Update Swiss points for all teams in a tournament or stage"""
    logger.info(f"Updating Swiss points for tournament {tournament.name}")
    
    if stage:
        tournament_teams = TournamentTeam.objects.filter(
            tournament=tournament,
            current_stage_number=stage.stage_number,
            is_active=True
        )
    else:
        tournament_teams = TournamentTeam.objects.filter(
            tournament=tournament,
            is_active=True
        )
    
    for team_tt in tournament_teams:
        team_tt.update_swiss_stats()
    
    logger.info(f"Swiss points updated for {tournament_teams.count()} teams")

def get_stage_rankings(tournament, stage_number):
    """Get rankings for a specific stage in a multi-stage tournament"""
    try:
        stage = tournament.stages.get(stage_number=stage_number)
        
        if stage.format in ['swiss', 'smart_swiss']:
            return get_swiss_rankings(tournament, stage)
        else:
            # For non-Swiss stages, use traditional ranking
            return get_traditional_rankings(tournament, stage)
            
    except Stage.DoesNotExist:
        logger.error(f"Stage {stage_number} not found in tournament {tournament.name}")
        return []

def get_traditional_rankings(tournament, stage=None):
    """Get traditional rankings (wins, point difference) for non-Swiss tournaments"""
    logger.info(f"Getting traditional rankings for tournament {tournament.name}")
    
    if stage:
        tournament_teams = TournamentTeam.objects.filter(
            tournament=tournament,
            current_stage_number=stage.stage_number,
            is_active=True
        )
        match_filter = Q(tournament=tournament, stage=stage, status='completed')
    else:
        tournament_teams = TournamentTeam.objects.filter(
            tournament=tournament,
            is_active=True
        )
        match_filter = Q(tournament=tournament, status='completed')
    
    rankings = []
    for team_tt in tournament_teams:
        # Get match statistics
        team_matches = Match.objects.filter(match_filter).filter(
            Q(team1=team_tt.team) | Q(team2=team_tt.team)
        )
        
        matches_played = team_matches.count()
        matches_won = team_matches.filter(winner=team_tt.team).count()
        matches_lost = matches_played - matches_won
        
        # Calculate points scored and conceded
        points_scored = 0
        points_conceded = 0
        
        for match in team_matches:
            if match.team1 == team_tt.team:
                points_scored += match.team1_score or 0
                points_conceded += match.team2_score or 0
            else:
                points_scored += match.team2_score or 0
                points_conceded += match.team1_score or 0
        
        rankings.append({
            'team': team_tt.team,
            'tournament_team': team_tt,
            'matches_played': matches_played,
            'matches_won': matches_won,
            'matches_lost': matches_lost,
            'points_scored': points_scored,
            'points_conceded': points_conceded,
            'point_difference': points_scored - points_conceded,
        })
    
    # Sort by wins (desc), then point difference (desc), then points scored (desc)
    rankings.sort(key=lambda x: (x['matches_won'], x['point_difference'], x['points_scored']), reverse=True)
    
    # Add positions
    for i, ranking in enumerate(rankings):
        ranking['position'] = i + 1
    
    logger.info(f"Traditional rankings calculated for {len(rankings)} teams")
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
