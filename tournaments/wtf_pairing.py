"""
WTF Pairing Engine - Push-Up/Cool-Down Strategy
Implements specialized pairing logic for WTF tournaments

This module handles the unique pairing strategy for WTF tournaments:
1. Identify Push-Up teams (low Swiss, high PI)
2. Identify Cool-Down teams (high Swiss, low PI)  
3. Pair Push-Up vs Cool-Down when possible
4. Fall back to nearest-PI pairing
"""

import logging
from typing import Dict, List, Tuple, Optional, Set
from django.db.models import Q
from tournaments.models import Tournament, TournamentTeam, Stage, Round
from matches.models import Match
from teams.models import Team
from tournaments.wtf_algorithm import WTFAlgorithm

logger = logging.getLogger(__name__)


class WTFPairingEngine:
    """
    WTF Pairing Engine implementing push-up/cool-down strategy.
    
    Pairing Logic:
    1. Calculate πετΑ Index for all teams
    2. Tag teams as Push-Up or Cool-Down
    3. Pair Push-Up vs Cool-Down (avoiding repeats)
    4. Pair remaining teams by nearest PI
    """
    
    def __init__(self, tournament: Tournament, stage: Optional[Stage] = None, config: Optional[Dict] = None):
        """Initialize WTF pairing engine."""
        self.tournament = tournament
        self.stage = stage
        self.wtf_algorithm = WTFAlgorithm(tournament, stage, config)
        self.config = config or {}
        
        # Pairing thresholds
        self.pushup_threshold = 0.6  # PI above this with low Swiss = Push-Up
        self.cooldown_threshold = 0.4  # PI below this with high Swiss = Cool-Down
        self.swiss_median_split = True  # Use median Swiss points for high/low split
    
    def generate_round_matches(self, round_number: int) -> List[Match]:
        """
        Generate matches for a round using WTF pairing strategy.
        
        Returns:
            List of created Match objects
        """
        logger.info(f"Generating WTF round {round_number} matches for tournament {self.tournament.name}")
        
        # Get active tournament teams
        tournament_teams = self._get_active_teams()
        if len(tournament_teams) < 2:
            logger.warning("Not enough teams for pairing")
            return []
        
        # Calculate πετΑ Index for all teams
        peta_indices = self.wtf_algorithm.calculate_peta_index(tournament_teams)
        
        # Get Swiss points for classification
        swiss_points = {tt.team.id: tt.swiss_points for tt in tournament_teams}
        
        # Classify teams as Push-Up, Cool-Down, or Normal
        team_classifications = self._classify_teams(peta_indices, swiss_points)
        
        # Generate pairings using WTF strategy
        pairings = self._generate_wtf_pairings(tournament_teams, peta_indices, team_classifications)
        
        # Create Match objects
        matches = self._create_matches(pairings, round_number)
        
        logger.info(f"Generated {len(matches)} WTF matches for round {round_number}")
        return matches
    
    def _get_active_teams(self) -> List[TournamentTeam]:
        """Get active tournament teams for pairing."""
        if self.stage:
            # Multi-stage tournament
            return list(TournamentTeam.objects.filter(
                tournament=self.tournament,
                current_stage_number=self.stage.stage_number,
                is_active=True
            ).select_related('team'))
        else:
            # Single-stage tournament
            return list(TournamentTeam.objects.filter(
                tournament=self.tournament,
                is_active=True
            ).select_related('team'))
    
    def _classify_teams(self, peta_indices: Dict[int, Dict], swiss_points: Dict[int, int]) -> Dict[int, str]:
        """
        Classify teams as Push-Up, Cool-Down, or Normal.
        
        Push-Up: Low Swiss points but high πετΑ Index (strong resistance)
        Cool-Down: High Swiss points but low πετΑ Index (easy wins)
        Normal: Everything else
        """
        classifications = {}
        
        # Calculate median Swiss points for high/low split
        swiss_values = list(swiss_points.values())
        swiss_values.sort()
        n = len(swiss_values)
        swiss_median = swiss_values[n // 2] if n > 0 else 0
        
        for team_id, peta_data in peta_indices.items():
            pi = peta_data.get('PI', 0.0)
            swiss = swiss_points.get(team_id, 0)
            
            # Classification logic
            if swiss <= swiss_median and pi >= self.pushup_threshold:
                # Low Swiss, High PI = Push-Up
                classifications[team_id] = "pushup"
            elif swiss > swiss_median and pi <= self.cooldown_threshold:
                # High Swiss, Low PI = Cool-Down
                classifications[team_id] = "cooldown"
            else:
                # Normal team
                classifications[team_id] = "normal"
        
        logger.info(f"Team classifications: {classifications}")
        return classifications
    
    def _generate_wtf_pairings(self, tournament_teams: List[TournamentTeam], 
                              peta_indices: Dict[int, Dict], 
                              classifications: Dict[int, str]) -> List[Tuple[TournamentTeam, TournamentTeam]]:
        """
        Generate pairings using WTF strategy.
        
        Strategy:
        1. Pair Push-Up vs Cool-Down teams (avoiding repeats)
        2. Pair remaining teams by nearest πετΑ Index
        """
        pairings = []
        unpaired_teams = tournament_teams.copy()
        
        # Get teams by classification
        pushup_teams = [tt for tt in tournament_teams if classifications.get(tt.team.id) == "pushup"]
        cooldown_teams = [tt for tt in tournament_teams if classifications.get(tt.team.id) == "cooldown"]
        normal_teams = [tt for tt in tournament_teams if classifications.get(tt.team.id) == "normal"]
        
        logger.info(f"Push-Up teams: {len(pushup_teams)}, Cool-Down teams: {len(cooldown_teams)}, Normal teams: {len(normal_teams)}")
        
        # Phase 1: Pair Push-Up vs Cool-Down
        pushup_cooldown_pairs = self._pair_pushup_cooldown(pushup_teams, cooldown_teams)
        for pair in pushup_cooldown_pairs:
            pairings.append(pair)
            unpaired_teams.remove(pair[0])
            unpaired_teams.remove(pair[1])
        
        # Phase 2: Pair remaining teams by nearest πετΑ Index
        nearest_pi_pairs = self._pair_by_nearest_pi(unpaired_teams, peta_indices)
        pairings.extend(nearest_pi_pairs)
        
        return pairings
    
    def _pair_pushup_cooldown(self, pushup_teams: List[TournamentTeam], 
                             cooldown_teams: List[TournamentTeam]) -> List[Tuple[TournamentTeam, TournamentTeam]]:
        """
        Pair Push-Up teams with Cool-Down teams, avoiding repeats.
        """
        pairings = []
        used_pushup = set()
        used_cooldown = set()
        
        for pushup_team in pushup_teams:
            if pushup_team.team.id in used_pushup:
                continue
            
            # Find best Cool-Down opponent (avoiding repeats)
            best_cooldown = None
            for cooldown_team in cooldown_teams:
                if (cooldown_team.team.id in used_cooldown or 
                    self._have_teams_played(pushup_team.team.id, cooldown_team.team.id)):
                    continue
                
                best_cooldown = cooldown_team
                break
            
            if best_cooldown:
                pairings.append((pushup_team, best_cooldown))
                used_pushup.add(pushup_team.team.id)
                used_cooldown.add(best_cooldown.team.id)
                logger.info(f"Push-Up/Cool-Down pair: {pushup_team.team.name} vs {best_cooldown.team.name}")
        
        return pairings
    
    def _pair_by_nearest_pi(self, teams: List[TournamentTeam], 
                           peta_indices: Dict[int, Dict]) -> List[Tuple[TournamentTeam, TournamentTeam]]:
        """
        Pair remaining teams by nearest πετΑ Index values.
        """
        pairings = []
        unpaired = teams.copy()
        
        # Sort teams by πετΑ Index for efficient pairing
        unpaired.sort(key=lambda tt: peta_indices.get(tt.team.id, {}).get('PI', 0.0), reverse=True)
        
        while len(unpaired) >= 2:
            team1 = unpaired[0]
            team1_pi = peta_indices.get(team1.team.id, {}).get('PI', 0.0)
            
            # Find nearest PI opponent (avoiding repeats)
            best_opponent = None
            best_pi_diff = float('inf')
            
            for i, team2 in enumerate(unpaired[1:], 1):
                if self._have_teams_played(team1.team.id, team2.team.id):
                    continue
                
                team2_pi = peta_indices.get(team2.team.id, {}).get('PI', 0.0)
                pi_diff = abs(team1_pi - team2_pi)
                
                if pi_diff < best_pi_diff:
                    best_pi_diff = pi_diff
                    best_opponent = team2
            
            if best_opponent:
                pairings.append((team1, best_opponent))
                unpaired.remove(team1)
                unpaired.remove(best_opponent)
                logger.info(f"Nearest-PI pair: {team1.team.name} vs {best_opponent.team.name} (PI diff: {best_pi_diff:.3f})")
            else:
                # No valid opponent found, pair with next available (allowing repeat)
                if len(unpaired) >= 2:
                    team2 = unpaired[1]
                    pairings.append((team1, team2))
                    unpaired.remove(team1)
                    unpaired.remove(team2)
                    logger.warning(f"Forced pair (repeat): {team1.team.name} vs {team2.team.name}")
                else:
                    # Odd number of teams, team1 gets a bye
                    logger.info(f"Bye: {team1.team.name}")
                    break
        
        return pairings
    
    def _have_teams_played(self, team1_id: int, team2_id: int) -> bool:
        """Check if two teams have already played against each other."""
        if not self.config.get("avoid_repeats", True):
            return False
        
        base_filter = Q(status__in=['completed', 'active', 'pending'])
        
        if self.stage:
            base_filter &= Q(stage=self.stage)
        else:
            base_filter &= Q(tournament=self.tournament)
        
        # Check if teams have played
        match_exists = Match.objects.filter(
            base_filter &
            ((Q(team1_id=team1_id) & Q(team2_id=team2_id)) |
             (Q(team1_id=team2_id) & Q(team2_id=team1_id)))
        ).exists()
        
        return match_exists
    
    def _create_matches(self, pairings: List[Tuple[TournamentTeam, TournamentTeam]], 
                       round_number: int) -> List[Match]:
        """Create Match objects from pairings."""
        matches = []
        
        for team1_tt, team2_tt in pairings:
            # Get the round object
            round_obj = Round.objects.get(
                tournament=self.tournament,
                stage=self.stage,
                number_in_stage=round_number
            )
            
            match_data = {
                'tournament': self.tournament,
                'team1': team1_tt.team,
                'team2': team2_tt.team,
                'round': round_obj,
                'status': 'pending',
                'time_limit_minutes': self.tournament.default_time_limit_minutes,
            }
            
            if self.stage:
                match_data['stage'] = self.stage
            
            match = Match.objects.create(**match_data)
            matches.append(match)
            
            logger.info(f"Created WTF match: {team1_tt.team.name} vs {team2_tt.team.name} (Round {round_number})")
        
        return matches


class WTFPairingAnalyzer:
    """
    Analyzer for WTF pairing decisions and team classifications.
    
    Provides insights into why teams were paired and classified.
    """
    
    def __init__(self, tournament: Tournament, stage: Optional[Stage] = None):
        """Initialize WTF pairing analyzer."""
        self.tournament = tournament
        self.stage = stage
        self.wtf_algorithm = WTFAlgorithm(tournament, stage)
    
    def analyze_round_pairings(self, round_number: int) -> Dict[str, any]:
        """
        Analyze pairings for a specific round.
        
        Returns detailed analysis of pairing decisions.
        """
        # Get matches for the round
        matches = self._get_round_matches(round_number)
        
        # Get tournament teams and calculate metrics
        tournament_teams = self._get_tournament_teams()
        peta_indices = self.wtf_algorithm.calculate_peta_index(tournament_teams)
        
        # Analyze each pairing
        pairing_analysis = []
        for match in matches:
            team1_id = match.team1.id
            team2_id = match.team2.id
            
            team1_data = peta_indices.get(team1_id, {})
            team2_data = peta_indices.get(team2_id, {})
            
            analysis = {
                'match': match,
                'team1_pi': team1_data.get('PI', 0.0),
                'team2_pi': team2_data.get('PI', 0.0),
                'pi_difference': abs(team1_data.get('PI', 0.0) - team2_data.get('PI', 0.0)),
                'team1_swiss': self._get_team_swiss_points(team1_id),
                'team2_swiss': self._get_team_swiss_points(team2_id),
                'pairing_type': self._classify_pairing_type(team1_data, team2_data),
                'quality_score': self._calculate_pairing_quality(team1_data, team2_data)
            }
            pairing_analysis.append(analysis)
        
        return {
            'round_number': round_number,
            'total_matches': len(matches),
            'pairings': pairing_analysis,
            'average_pi_difference': sum(p['pi_difference'] for p in pairing_analysis) / len(pairing_analysis) if pairing_analysis else 0,
            'pairing_type_distribution': self._get_pairing_type_distribution(pairing_analysis)
        }
    
    def _get_round_matches(self, round_number: int) -> List[Match]:
        """Get matches for a specific round."""
        base_filter = Q(round_number=round_number)
        
        if self.stage:
            base_filter &= Q(stage=self.stage)
        else:
            base_filter &= Q(tournament=self.tournament)
        
        return list(Match.objects.filter(base_filter).select_related('team1', 'team2'))
    
    def _get_tournament_teams(self) -> List[TournamentTeam]:
        """Get tournament teams."""
        if self.stage:
            return list(TournamentTeam.objects.filter(
                tournament=self.tournament,
                stage=self.stage
            ).select_related('team'))
        else:
            return list(TournamentTeam.objects.filter(
                tournament=self.tournament
            ).select_related('team'))
    
    def _get_team_swiss_points(self, team_id: int) -> int:
        """Get Swiss points for a team."""
        try:
            if self.stage:
                tt = TournamentTeam.objects.get(tournament=self.tournament, stage=self.stage, team_id=team_id)
            else:
                tt = TournamentTeam.objects.get(tournament=self.tournament, team_id=team_id)
            return tt.swiss_points
        except TournamentTeam.DoesNotExist:
            return 0
    
    def _classify_pairing_type(self, team1_data: Dict, team2_data: Dict) -> str:
        """Classify the type of pairing."""
        team1_pi = team1_data.get('PI', 0.0)
        team2_pi = team2_data.get('PI', 0.0)
        
        pi_diff = abs(team1_pi - team2_pi)
        
        if pi_diff < 0.1:
            return "nearest_pi"
        elif (team1_pi > 0.6 and team2_pi < 0.4) or (team1_pi < 0.4 and team2_pi > 0.6):
            return "pushup_cooldown"
        else:
            return "balanced"
    
    def _calculate_pairing_quality(self, team1_data: Dict, team2_data: Dict) -> float:
        """Calculate quality score for a pairing (0-1, higher is better)."""
        # Quality based on PI similarity and balance
        pi_diff = abs(team1_data.get('PI', 0.0) - team2_data.get('PI', 0.0))
        pi_similarity = 1.0 - min(pi_diff, 1.0)  # Closer PI = higher quality
        
        # Bonus for push-up/cool-down pairings
        pushup_cooldown_bonus = 0.2 if self._classify_pairing_type(team1_data, team2_data) == "pushup_cooldown" else 0.0
        
        return min(pi_similarity + pushup_cooldown_bonus, 1.0)
    
    def _get_pairing_type_distribution(self, pairing_analysis: List[Dict]) -> Dict[str, int]:
        """Get distribution of pairing types."""
        distribution = {}
        for analysis in pairing_analysis:
            pairing_type = analysis['pairing_type']
            distribution[pairing_type] = distribution.get(pairing_type, 0) + 1
        return distribution
