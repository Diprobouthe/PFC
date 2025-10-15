"""
WTF (Weighted Tuned Filtering) Algorithm Implementation
πετΑ Index-based ranking system for tournament management

This module implements the WTF algorithm that embodies the πετΑ philosophy:
rewarding quality of opposition and resistance, not just victories.
"""

import logging
from typing import Dict, List, Tuple, Optional, Any
from decimal import Decimal, ROUND_HALF_UP
from django.db.models import Q, Avg, Sum, Count
from tournaments.models import Tournament, TournamentTeam, Stage
from matches.models import Match

logger = logging.getLogger(__name__)


class WTFAlgorithm:
    """
    WTF (Weighted Tuned Filtering) Algorithm
    
    Implements πετΑ Index (PI) calculation based on:
    - SoS: Strength of Schedule (Median Buchholz)
    - QoR: Quality of Resistance (Match closeness)
    - SSF: Swiss Soft Factor (Win recognition)
    - BR: Base Rating (Optional PFC rating)
    """
    
    # Default configuration
    DEFAULT_CONFIG = {
        "weights": {
            "SoS": 0.40,  # Strength of Schedule
            "QoR": 0.30,  # Quality of Resistance
            "SSF": 0.15,  # Swiss Soft Factor
            "PFC": 0.15   # Base Rating
        },
        "use_pfc_rating": True,
        "pfc_rating_field": "pfc_rating",
        "pfc_normalize": True,
        "buchholz_mode": "median_cut1",
        "margin_cap": 13,
        "pairing_mode": "pushup_cooldown_then_nearest",
        "avoid_repeats": True
    }
    
    def __init__(self, tournament: Tournament, stage: Optional[Stage] = None, config: Optional[Dict] = None):
        """Initialize WTF algorithm with tournament and configuration."""
        self.tournament = tournament
        self.stage = stage
        self.config = {**self.DEFAULT_CONFIG, **(config or {})}
        
        # Normalize weights if PFC rating is disabled
        if not self.config["use_pfc_rating"]:
            weights = self.config["weights"]
            total_weight = weights["SoS"] + weights["QoR"] + weights["SSF"]
            self.config["weights"] = {
                "SoS": weights["SoS"] / total_weight,
                "QoR": weights["QoR"] / total_weight,
                "SSF": weights["SSF"] / total_weight,
                "PFC": 0.0
            }
    
    def calculate_peta_index(self, tournament_teams: List[TournamentTeam]) -> Dict[int, Dict[str, float]]:
        """
        Calculate πετΑ Index (PI) for all teams.
        
        PI(t) = w_SoS·SoS' + w_QoR·QoR' + w_SSF·SSF' + w_PFC·BR'
        
        Returns:
            Dict mapping team_id to metrics dict with PI, SoS, QoR, SSF, BR
        """
        logger.info(f"Calculating πετΑ Index for {len(tournament_teams)} teams")
        
        # Calculate raw metrics for all teams
        sos_values = self._calculate_strength_of_schedule(tournament_teams)
        qor_values = self._calculate_quality_of_resistance(tournament_teams)
        ssf_values = self._calculate_swiss_soft_factor(tournament_teams)
        br_values = self._calculate_base_rating(tournament_teams)
        
        # Normalize all metrics to [0, 1]
        sos_normalized = self._normalize_values(sos_values)
        qor_normalized = self._normalize_values(qor_values)
        ssf_normalized = self._normalize_values(ssf_values)
        br_normalized = self._normalize_values(br_values)
        
        # Calculate πετΑ Index for each team
        peta_indices = {}
        weights = self.config["weights"]
        
        for team_id in [tt.team.id for tt in tournament_teams]:
            pi = (
                weights["SoS"] * sos_normalized.get(team_id, 0.0) +
                weights["QoR"] * qor_normalized.get(team_id, 0.0) +
                weights["SSF"] * ssf_normalized.get(team_id, 0.0) +
                weights["PFC"] * br_normalized.get(team_id, 0.0)
            )
            
            peta_indices[team_id] = {
                "PI": round(pi, 4),
                "SoS": round(sos_normalized.get(team_id, 0.0), 4),
                "QoR": round(qor_normalized.get(team_id, 0.0), 4),
                "SSF": round(ssf_normalized.get(team_id, 0.0), 4),
                "BR": round(br_normalized.get(team_id, 0.0), 4),
                "SoS_raw": round(sos_values.get(team_id, 0.0), 2),
                "QoR_raw": round(qor_values.get(team_id, 0.0), 4),
                "SSF_raw": round(ssf_values.get(team_id, 0.0), 4),
                "BR_raw": br_values.get(team_id, 0.0)
            }
        
        logger.info(f"πετΑ Index calculation completed for {len(peta_indices)} teams")
        return peta_indices
    
    def _calculate_strength_of_schedule(self, tournament_teams: List[TournamentTeam]) -> Dict[int, float]:
        """
        Calculate Strength of Schedule using Median Buchholz (cut-1).
        
        SoS = sum of opponents' Swiss Points, dropping highest and lowest.
        """
        sos_values = {}
        
        for tt in tournament_teams:
            # Get all opponents this team has faced
            team_matches = self._get_team_matches(tt.team.id)
            opponent_swiss_points = []
            
            for match in team_matches:
                opponent_id = match.team2.id if match.team1.id == tt.team.id else match.team1.id
                try:
                    opponent_tt = TournamentTeam.objects.get(tournament=self.tournament, team_id=opponent_id)
                    opponent_swiss_points.append(opponent_tt.swiss_points)
                except TournamentTeam.DoesNotExist:
                    continue
            
            # Calculate Median Buchholz (cut-1)
            if len(opponent_swiss_points) <= 2:
                # Not enough opponents for cut-1, use sum
                sos = sum(opponent_swiss_points)
            else:
                # Drop highest and lowest, sum the rest
                opponent_swiss_points.sort()
                sos = sum(opponent_swiss_points[1:-1])
            
            sos_values[tt.team.id] = float(sos)
        
        return sos_values
    
    def _calculate_quality_of_resistance(self, tournament_teams: List[TournamentTeam]) -> Dict[int, float]:
        """
        Calculate Quality of Resistance based on match closeness.
        
        QoR = average of match closeness scores
        closeness = 1 - min(|score_for - score_against|, M_cap) / M_cap
        """
        qor_values = {}
        margin_cap = self.config["margin_cap"]
        
        for tt in tournament_teams:
            team_matches = self._get_team_matches(tt.team.id)
            closeness_scores = []
            
            for match in team_matches:
                if match.team1_score is not None and match.team2_score is not None:
                    # Determine team's score and opponent's score
                    if match.team1.id == tt.team.id:
                        team_score = match.team1_score
                        opponent_score = match.team2_score
                    else:
                        team_score = match.team2_score
                        opponent_score = match.team1_score
                    
                    # Calculate closeness
                    margin = abs(team_score - opponent_score)
                    capped_margin = min(margin, margin_cap)
                    closeness = 1.0 - (capped_margin / margin_cap)
                    closeness_scores.append(closeness)
            
            # Average closeness across all matches
            qor = sum(closeness_scores) / len(closeness_scores) if closeness_scores else 0.0
            qor_values[tt.team.id] = qor
        
        return qor_values
    
    def _calculate_swiss_soft_factor(self, tournament_teams: List[TournamentTeam]) -> Dict[int, float]:
        """
        Calculate Swiss Soft Factor.
        
        SSF = SwissPoints / (3 × rounds)
        """
        ssf_values = {}
        
        # Count total rounds played
        total_rounds = self._count_tournament_rounds()
        max_possible_points = 3 * total_rounds if total_rounds > 0 else 3
        
        for tt in tournament_teams:
            ssf = tt.swiss_points / max_possible_points if max_possible_points > 0 else 0.0
            ssf_values[tt.team.id] = ssf
        
        return ssf_values
    
    def _calculate_base_rating(self, tournament_teams: List[TournamentTeam]) -> Dict[int, float]:
        """
        Calculate Base Rating from PFC platform rating.
        
        Uses team.pfc_rating field if available and enabled.
        """
        br_values = {}
        
        if not self.config["use_pfc_rating"]:
            # PFC rating disabled, return 0.5 for all teams
            for tt in tournament_teams:
                br_values[tt.team.id] = 0.5
            return br_values
        
        # Extract PFC ratings from teams
        for tt in tournament_teams:
            try:
                # Get PFC rating from team
                pfc_rating = getattr(tt.team, self.config["pfc_rating_field"], None)
                if pfc_rating is not None:
                    br_values[tt.team.id] = float(pfc_rating)
                else:
                    br_values[tt.team.id] = 0.5  # Default neutral rating
            except (AttributeError, ValueError):
                br_values[tt.team.id] = 0.5  # Default neutral rating
        
        return br_values
    
    def _normalize_values(self, values: Dict[int, float]) -> Dict[int, float]:
        """Normalize values to [0, 1] range using min-max normalization."""
        if not values:
            return {}
        
        min_val = min(values.values())
        max_val = max(values.values())
        
        if max_val == min_val:
            # All values are the same, return 0.5 for all
            return {team_id: 0.5 for team_id in values.keys()}
        
        normalized = {}
        for team_id, value in values.items():
            normalized[team_id] = (value - min_val) / (max_val - min_val)
        
        return normalized
    
    def _get_team_matches(self, team_id: int) -> List[Match]:
        """Get all completed matches for a team in this tournament."""
        base_filter = Q(status='completed')
        
        if self.stage:
            # Multi-stage tournament - filter by stage
            base_filter &= Q(stage=self.stage)
        else:
            # Single-stage tournament - filter by tournament
            base_filter &= Q(tournament=self.tournament)
        
        # Filter by team participation
        team_filter = Q(team1_id=team_id) | Q(team2_id=team_id)
        
        return Match.objects.filter(base_filter & team_filter).order_by('id')  # Use id instead of round_number
    
    def _count_tournament_rounds(self) -> int:
        """Count the number of rounds played in the tournament/stage."""
        if self.stage:
            # Multi-stage tournament
            matches = Match.objects.filter(stage=self.stage, status='completed')
        else:
            # Single-stage tournament
            matches = Match.objects.filter(tournament=self.tournament, status='completed')
        
        if not matches.exists():
            return 0
        
        # Count distinct rounds - use round relation if available, otherwise estimate from match count
        try:
            return matches.aggregate(max_round=Count('round__round_number', distinct=True))['max_round'] or 0
        except:
            # Fallback: estimate rounds from match count (assuming 3 matches per round for 6 teams)
            return (matches.count() // 3) if matches.count() > 0 else 0
    
    def get_wtf_rankings(self, tournament_teams: List[TournamentTeam]) -> List[Dict[str, Any]]:
        """
        Get WTF rankings for tournament teams.
        
        Returns list of team rankings sorted by πετΑ Index (descending).
        """
        # Calculate πετΑ Index for all teams
        peta_indices = self.calculate_peta_index(tournament_teams)
        
        # Create ranking entries
        rankings = []
        for tt in tournament_teams:
            team_id = tt.team.id
            peta_data = peta_indices.get(team_id, {})
            
            # Get match statistics
            team_matches = self._get_team_matches(team_id)
            matches_played = len(team_matches)
            matches_won = sum(1 for match in team_matches if self._is_match_won(match, team_id))
            matches_lost = matches_played - matches_won
            
            # Get points scored/conceded
            points_scored, points_conceded = self._get_team_points(team_matches, team_id)
            
            ranking = {
                'team': tt.team,
                'position': 0,  # Will be set after sorting
                'peta_index': peta_data.get('PI', 0.0),
                'sos': peta_data.get('SoS', 0.0),
                'qor': peta_data.get('QoR', 0.0),
                'ssf': peta_data.get('SSF', 0.0),
                'base_rating': peta_data.get('BR', 0.0),
                'sos_raw': peta_data.get('SoS_raw', 0.0),
                'qor_raw': peta_data.get('QoR_raw', 0.0),
                'ssf_raw': peta_data.get('SSF_raw', 0.0),
                'base_rating_raw': peta_data.get('BR_raw', 0.0),
                'matches_played': matches_played,
                'matches_won': matches_won,
                'matches_lost': matches_lost,
                'points_scored': points_scored,
                'points_conceded': points_conceded,
                'swiss_points': tt.swiss_points,
            }
            rankings.append(ranking)
        
        # Sort by πετΑ Index (descending), then by Swiss points as tiebreaker
        rankings.sort(key=lambda x: (-x['peta_index'], -x['swiss_points']))
        
        # Set positions
        for i, ranking in enumerate(rankings):
            ranking['position'] = i + 1
        
        return rankings
    
    def _is_match_won(self, match: Match, team_id: int) -> bool:
        """Check if the team won the match."""
        if match.team1_score is None or match.team2_score is None:
            return False
        
        if match.team1.id == team_id:
            return match.team1_score > match.team2_score
        else:
            return match.team2_score > match.team1_score
    
    def _get_team_points(self, matches: List[Match], team_id: int) -> Tuple[int, int]:
        """Get total points scored and conceded by the team."""
        points_scored = 0
        points_conceded = 0
        
        for match in matches:
            if match.team1_score is not None and match.team2_score is not None:
                if match.team1.id == team_id:
                    points_scored += match.team1_score
                    points_conceded += match.team2_score
                else:
                    points_scored += match.team2_score
                    points_conceded += match.team1_score
        
        return points_scored, points_conceded


def generate_wtf_matches(tournament: Tournament, stage: Optional[Stage] = None, 
                        round_number: int = 1, config: Optional[Dict] = None) -> List[Match]:
    """
    Generate matches using WTF pairing algorithm.
    
    Uses push-up/cool-down strategy with nearest-PI fallback.
    """
    from tournaments.wtf_pairing import WTFPairingEngine
    
    pairing_engine = WTFPairingEngine(tournament, stage, config)
    return pairing_engine.generate_round_matches(round_number)


def is_wtf_tournament(tournament: Tournament) -> bool:
    """Check if tournament uses WTF algorithm."""
    if tournament.format == "wtf":
        return True
    
    # Check if any stage uses WTF
    if tournament.format == "multi_stage":
        return tournament.stages.filter(format="wtf").exists()
    
    return False
