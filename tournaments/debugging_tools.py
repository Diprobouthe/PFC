"""
Comprehensive debugging tools for tournament automation
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from collections import defaultdict

from django.utils import timezone
from django.db.models import Q, Count

from .models import Tournament, Stage, Round, TournamentTeam
from matches.models import Match
from .automation_logger import AutomationLogger


class TournamentDebugger:
    """Comprehensive debugging tools for tournament automation"""
    
    def __init__(self, tournament_id: int):
        self.tournament_id = tournament_id
        self.logger = AutomationLogger(tournament_id)
        
    def run_full_diagnostic(self) -> Dict[str, Any]:
        """Run complete diagnostic analysis of tournament"""
        try:
            tournament = Tournament.objects.get(id=self.tournament_id)
        except Tournament.DoesNotExist:
            return {'error': f'Tournament {self.tournament_id} not found'}
        
        diagnostic = {
            'tournament_id': self.tournament_id,
            'timestamp': timezone.now().isoformat(),
            'tournament_info': self._analyze_tournament_info(tournament),
            'stage_analysis': self._analyze_stages(tournament),
            'round_analysis': self._analyze_rounds(tournament),
            'match_analysis': self._analyze_matches(tournament),
            'automation_status': self._analyze_automation_status(tournament),
            'error_analysis': self._analyze_errors(),
            'recommendations': self._generate_recommendations(tournament),
            'health_score': 0,  # Will be calculated
        }
        
        # Calculate health score
        diagnostic['health_score'] = self._calculate_health_score(diagnostic)
        
        return diagnostic
    
    def _analyze_tournament_info(self, tournament) -> Dict[str, Any]:
        """Analyze basic tournament information"""
        return {
            'id': tournament.id,
            'name': tournament.name,
            'format': tournament.format,
            'is_active': tournament.is_active,
            'is_archived': tournament.is_archived,
            'current_round': tournament.current_round_number,
            'automation_status': getattr(tournament, 'automation_status', 'unknown'),
            'created': tournament.created_at.isoformat() if hasattr(tournament, 'created_at') else None,
            'updated': tournament.updated_at.isoformat() if hasattr(tournament, 'updated_at') else None,
            'team_count': tournament.teams.count(),
            'stage_count': tournament.stages.count(),
            'round_count': tournament.rounds.count(),
            'match_count': tournament.matches.count(),
        }
    
    def _analyze_stages(self, tournament) -> Dict[str, Any]:
        """Analyze tournament stages configuration"""
        stages = tournament.stages.all().order_by('stage_number')
        
        stage_analysis = {
            'total_stages': len(stages),
            'stages': [],
            'issues': [],
        }
        
        for stage in stages:
            stage_info = {
                'number': stage.stage_number,
                'name': stage.name,
                'format': stage.format,
                'rounds_required': stage.num_rounds_in_stage,
                'qualifiers': stage.num_qualifiers,
                'teams_in_stage': stage.teams.count() if hasattr(stage, 'teams') else 0,
                'rounds_completed': 0,
                'is_complete': False,
            }
            
            # Count completed rounds for this stage
            stage_rounds = tournament.rounds.filter(stage=stage)
            completed_rounds = stage_rounds.filter(is_complete=True).count()
            stage_info['rounds_completed'] = completed_rounds
            stage_info['is_complete'] = completed_rounds >= stage.num_rounds_in_stage
            
            # Check for issues
            if stage.num_qualifiers > stage.teams.count() if hasattr(stage, 'teams') else 0:
                stage_analysis['issues'].append(
                    f"Stage {stage.stage_number}: More qualifiers ({stage.num_qualifiers}) than teams"
                )
            
            if stage.num_rounds_in_stage <= 0:
                stage_analysis['issues'].append(
                    f"Stage {stage.stage_number}: Invalid rounds count ({stage.num_rounds_in_stage})"
                )
            
            stage_analysis['stages'].append(stage_info)
        
        return stage_analysis
    
    def _analyze_rounds(self, tournament) -> Dict[str, Any]:
        """Analyze tournament rounds status"""
        rounds = tournament.rounds.all().order_by('number')
        
        round_analysis = {
            'total_rounds': len(rounds),
            'completed_rounds': 0,
            'rounds': [],
            'issues': [],
        }
        
        for round_obj in rounds:
            round_info = {
                'number': round_obj.number,
                'stage_number': round_obj.stage.stage_number if round_obj.stage else None,
                'number_in_stage': round_obj.number_in_stage,
                'is_complete': round_obj.is_complete,
                'match_count': 0,
                'completed_matches': 0,
                'pending_matches': 0,
            }
            
            # Count matches for this round
            round_matches = tournament.matches.filter(round=round_obj)
            round_info['match_count'] = round_matches.count()
            round_info['completed_matches'] = round_matches.filter(status='completed').count()
            round_info['pending_matches'] = round_matches.exclude(status='completed').count()
            
            # Check completion consistency
            if round_obj.is_complete and round_info['pending_matches'] > 0:
                round_analysis['issues'].append(
                    f"Round {round_obj.number}: Marked complete but has {round_info['pending_matches']} pending matches"
                )
            
            if not round_obj.is_complete and round_info['pending_matches'] == 0 and round_info['match_count'] > 0:
                round_analysis['issues'].append(
                    f"Round {round_obj.number}: All matches complete but round not marked complete"
                )
            
            if round_obj.is_complete:
                round_analysis['completed_rounds'] += 1
            
            round_analysis['rounds'].append(round_info)
        
        return round_analysis
    
    def _analyze_matches(self, tournament) -> Dict[str, Any]:
        """Analyze tournament matches"""
        matches = tournament.matches.all()
        
        match_analysis = {
            'total_matches': matches.count(),
            'by_status': {},
            'by_round': {},
            'issues': [],
            'recent_matches': [],
        }
        
        # Count by status
        status_counts = matches.values('status').annotate(count=Count('id'))
        for item in status_counts:
            match_analysis['by_status'][item['status']] = item['count']
        
        # Analyze by round
        round_counts = matches.values('round__number').annotate(count=Count('id'))
        by_round = {item['round__number']: item['count'] for item in round_counts}
        
        for round_num, count in by_round.items():
            if round_num is not None:
                match_analysis['by_round'][str(round_num)] = count
        
        # Get recent matches
        recent_matches = matches.order_by('-id')[:10]
        for match in recent_matches:
            match_info = {
                'id': match.id,
                'round_number': match.round.number if match.round else None,
                'status': match.status,
                'team1': str(match.team1) if hasattr(match, 'team1') else None,
                'team2': str(match.team2) if hasattr(match, 'team2') else None,
                'winner': str(match.winner) if hasattr(match, 'winner') and match.winner else None,
                'created': match.created_at.isoformat() if hasattr(match, 'created_at') else None,
            }
            match_analysis['recent_matches'].append(match_info)
        
        # Check for issues
        duplicate_pairings = self._find_duplicate_pairings(matches)
        if duplicate_pairings:
            match_analysis['issues'].extend(duplicate_pairings)
        
        return match_analysis
    
    def _find_duplicate_pairings(self, matches) -> List[str]:
        """Find duplicate team pairings in matches"""
        pairings = {}
        duplicates = []
        
        for match in matches:
            if not (hasattr(match, 'team1') and hasattr(match, 'team2')):
                continue
                
            # Create a normalized pairing key
            teams = sorted([str(match.team1), str(match.team2)])
            pairing_key = f"{teams[0]} vs {teams[1]}"
            
            if pairing_key in pairings:
                pairings[pairing_key].append(match.id)
            else:
                pairings[pairing_key] = [match.id]
        
        # Find duplicates
        for pairing, match_ids in pairings.items():
            if len(match_ids) > 1:
                duplicates.append(f"Duplicate pairing '{pairing}' in matches: {match_ids}")
        
        return duplicates
    
    def _analyze_automation_status(self, tournament) -> Dict[str, Any]:
        """Analyze automation status and history"""
        automation_status = getattr(tournament, 'automation_status', 'unknown')
        
        # Get automation logs
        recent_logs = AutomationLog.objects.filter(
            tournament_id=self.tournament_id
        ).order_by('-timestamp')[:20]
        
        # Get last automation attempt
        last_automation = AutomationLog.objects.filter(
            tournament_id=self.tournament_id,
            event_type='automation_start'
        ).first()
        
        # Get status changes
        status_changes = AutomationLog.objects.filter(
            tournament_id=self.tournament_id,
            event_type='status_change'
        ).order_by('-timestamp')[:5]
        
        # Count events by type
        event_counts = AutomationLog.objects.filter(
            tournament_id=self.tournament_id
        ).values('event_type').annotate(count=Count('id'))
        
        analysis = {
            'current_status': automation_status,
            'last_automation': last_automation.timestamp.isoformat() if last_automation else None,
            'event_counts': {item['event_type']: item['count'] for item in event_counts},
            'recent_status_changes': [
                {
                    'timestamp': change.timestamp.isoformat(),
                    'message': change.message,
                    'reasoning': change.reasoning,
                }
                for change in status_changes
            ],
            'issues': [],
        }
        
        # Check for stuck status
        if automation_status == 'processing':
            if last_automation:
                time_since = timezone.now() - last_automation.timestamp
                if time_since > timedelta(minutes=10):
                    analysis['issues'].append(
                        f"Status stuck in 'processing' for {time_since.total_seconds()//60:.0f} minutes"
                    )
        
        return analysis
    
    def _analyze_errors(self) -> Dict[str, Any]:
        """Analyze automation errors"""
        # Get recent errors
        recent_errors = AutomationLog.objects.filter(
            tournament_id=self.tournament_id,
            event_type='error'
        ).order_by('-timestamp')[:10]
        
        # Group errors by type
        error_types = {}
        for error in recent_errors:
            error_type = error.data.get('error_type', 'Unknown') if error.data else 'Unknown'
            if error_type not in error_types:
                error_types[error_type] = []
            error_types[error_type].append({
                'timestamp': error.timestamp.isoformat(),
                'message': error.message,
                'context': error.context,
            })
        
        # Get error frequency
        one_hour_ago = timezone.now() - timedelta(hours=1)
        one_day_ago = timezone.now() - timedelta(days=1)
        
        error_frequency = {
            'last_hour': AutomationLog.objects.filter(
                tournament_id=self.tournament_id,
                event_type='error',
                timestamp__gte=one_hour_ago
            ).count(),
            'last_day': AutomationLog.objects.filter(
                tournament_id=self.tournament_id,
                event_type='error',
                timestamp__gte=one_day_ago
            ).count(),
            'total': AutomationLog.objects.filter(
                tournament_id=self.tournament_id,
                event_type='error'
            ).count(),
        }
        
        return {
            'error_frequency': error_frequency,
            'error_types': error_types,
            'recent_errors': [
                {
                    'timestamp': error.timestamp.isoformat(),
                    'message': error.message,
                    'context': error.context,
                    'error_type': error.data.get('error_type', 'Unknown') if error.data else 'Unknown',
                }
                for error in recent_errors
            ],
        }
    
    def _generate_recommendations(self, tournament) -> List[str]:
        """Generate recommendations based on analysis"""
        recommendations = []
        
        # Check automation status
        automation_status = getattr(tournament, 'automation_status', 'unknown')
        if automation_status == 'processing':
            recommendations.append("Reset automation status to 'idle' to allow new automation attempts")
        elif automation_status == 'error':
            recommendations.append("Check error logs and reset automation status after fixing issues")
        
        # Check round completion
        incomplete_rounds = tournament.rounds.filter(is_complete=False)
        for round_obj in incomplete_rounds:
            pending_matches = tournament.matches.filter(
                round_number=round_obj.number
            ).exclude(status='completed').count()
            
            if pending_matches == 0:
                recommendations.append(f"Mark Round {round_obj.number} as complete - all matches finished")
        
        # Check stage progression
        stages = tournament.stages.all().order_by('stage_number')
        for stage in stages:
            completed_rounds = tournament.rounds.filter(
                stage=stage, is_complete=True
            ).count()
            
            if completed_rounds >= stage.num_rounds_in_stage:
                # Check if teams should advance to next stage
                next_stage = stages.filter(stage_number=stage.stage_number + 1).first()
                if next_stage and next_stage.teams.count() == 0:
                    recommendations.append(
                        f"Advance top {stage.num_qualifiers} teams from Stage {stage.stage_number} to Stage {next_stage.stage_number}"
                    )
        
        # Check for errors
        recent_errors = AutomationLog.objects.filter(
            tournament_id=self.tournament_id,
            event_type='error',
            timestamp__gte=timezone.now() - timedelta(hours=1)
        ).count()
        
        if recent_errors > 0:
            recommendations.append(f"Investigate {recent_errors} recent errors in automation logs")
        
        return recommendations
    
    def _calculate_health_score(self, diagnostic: Dict[str, Any]) -> int:
        """Calculate overall health score (0-100)"""
        score = 100
        
        # Deduct for errors
        error_frequency = diagnostic['error_analysis']['error_frequency']
        score -= min(error_frequency['last_hour'] * 10, 30)  # Max 30 points for recent errors
        score -= min(error_frequency['last_day'] * 2, 20)    # Max 20 points for daily errors
        
        # Deduct for issues
        total_issues = (
            len(diagnostic['stage_analysis']['issues']) +
            len(diagnostic['round_analysis']['issues']) +
            len(diagnostic['match_analysis']['issues']) +
            len(diagnostic['automation_status']['issues'])
        )
        score -= min(total_issues * 5, 25)  # Max 25 points for issues
        
        # Deduct for stuck automation
        if diagnostic['automation_status']['current_status'] == 'processing':
            score -= 15
        elif diagnostic['automation_status']['current_status'] == 'error':
            score -= 25
        
        return max(score, 0)
    
    def get_automation_timeline(self, hours: int = 24) -> List[Dict[str, Any]]:
        """Get automation timeline for the last N hours"""
        since = timezone.now() - timedelta(hours=hours)
        
        logs = AutomationLog.objects.filter(
            tournament_id=self.tournament_id,
            timestamp__gte=since
        ).order_by('timestamp')
        
        timeline = []
        for log in logs:
            timeline.append({
                'timestamp': log.timestamp.isoformat(),
                'event_type': log.event_type,
                'message': log.message,
                'details': log.details,
                'reasoning': log.reasoning,
                'context': log.context,
            })
        
        return timeline
    
    def simulate_next_automation_step(self) -> Dict[str, Any]:
        """Simulate what the next automation step would be"""
        try:
            tournament = Tournament.objects.get(id=self.tournament_id)
        except Tournament.DoesNotExist:
            return {'error': f'Tournament {self.tournament_id} not found'}
        
        simulation = {
            'current_state': {
                'round': tournament.current_round_number,
                'status': getattr(tournament, 'automation_status', 'unknown'),
            },
            'next_steps': [],
            'blocking_issues': [],
        }
        
        # Check if automation can proceed
        if getattr(tournament, 'automation_status', 'idle') != 'idle':
            simulation['blocking_issues'].append(
                f"Automation status is '{getattr(tournament, 'automation_status', 'unknown')}', not 'idle'"
            )
        
        # Check current round completion
        current_round = tournament.rounds.filter(number=tournament.current_round_number).first()
        if current_round:
            pending_matches = tournament.matches.filter(
                round_number=current_round.number
            ).exclude(status='completed').count()
            
            if pending_matches > 0:
                simulation['next_steps'].append(
                    f"Wait for {pending_matches} matches in Round {current_round.number} to complete"
                )
            else:
                if not current_round.is_complete:
                    simulation['next_steps'].append(f"Mark Round {current_round.number} as complete")
                
                # Check if stage is complete
                stage = current_round.stage
                if stage:
                    completed_rounds = tournament.rounds.filter(
                        stage=stage, is_complete=True
                    ).count()
                    
                    if completed_rounds >= stage.num_rounds_in_stage:
                        simulation['next_steps'].append(f"Advance teams from Stage {stage.stage_number}")
                    else:
                        simulation['next_steps'].append(f"Generate Round {tournament.current_round_number + 1}")
        
        return simulation


class AutomationProfiler:
    """Performance profiling for automation operations"""
    
    def __init__(self, tournament_id: int):
        self.tournament_id = tournament_id
        self.start_time = None
        self.checkpoints = []
    
    def start_profiling(self):
        """Start profiling session"""
        self.start_time = timezone.now()
        self.checkpoints = []
        self.checkpoint("Profiling started")
    
    def checkpoint(self, description: str):
        """Add a checkpoint"""
        if self.start_time is None:
            self.start_profiling()
        
        now = timezone.now()
        elapsed = (now - self.start_time).total_seconds()
        
        self.checkpoints.append({
            'timestamp': now.isoformat(),
            'elapsed_seconds': elapsed,
            'description': description,
        })
    
    def get_profile_report(self) -> Dict[str, Any]:
        """Get profiling report"""
        if not self.checkpoints:
            return {'error': 'No profiling data available'}
        
        total_time = self.checkpoints[-1]['elapsed_seconds']
        
        return {
            'tournament_id': self.tournament_id,
            'total_time_seconds': total_time,
            'checkpoint_count': len(self.checkpoints),
            'checkpoints': self.checkpoints,
            'performance_summary': {
                'fast': total_time < 1.0,
                'acceptable': total_time < 5.0,
                'slow': total_time >= 5.0,
            }
        }


def export_tournament_debug_report(tournament_id: int) -> str:
    """Export comprehensive debug report as JSON"""
    debugger = TournamentDebugger(tournament_id)
    diagnostic = debugger.run_full_diagnostic()
    timeline = debugger.get_automation_timeline(hours=48)
    simulation = debugger.simulate_next_automation_step()
    
    report = {
        'export_timestamp': timezone.now().isoformat(),
        'tournament_id': tournament_id,
        'diagnostic': diagnostic,
        'timeline': timeline,
        'simulation': simulation,
    }
    
    return json.dumps(report, indent=2, cls=DjangoJSONEncoder)

