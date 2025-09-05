"""
Tournament Automation Logging System
Provides comprehensive logging and monitoring for tournament automation debugging
"""

import logging
import json
import traceback
from datetime import datetime
from django.conf import settings
from django.db import models
from django.utils import timezone
from typing import Dict, Any, Optional, List
import os

class AutomationLogger:
    """Comprehensive logging system for tournament automation"""
    
    def __init__(self, tournament_id: int):
        self.tournament_id = tournament_id
        self.logger = self._setup_logger()
        
    def _setup_logger(self):
        """Setup dedicated logger for automation"""
        logger_name = f"automation.tournament_{self.tournament_id}"
        logger = logging.getLogger(logger_name)
        
        if not logger.handlers:
            # Create logs directory if it doesn't exist
            log_dir = os.path.join(settings.BASE_DIR, 'logs', 'automation')
            os.makedirs(log_dir, exist_ok=True)
            
            # File handler for detailed logs
            log_file = os.path.join(log_dir, f'tournament_{self.tournament_id}.log')
            file_handler = logging.FileHandler(log_file)
            file_handler.setLevel(logging.DEBUG)
            
            # Console handler for immediate feedback
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.INFO)
            
            # Detailed formatter
            formatter = logging.Formatter(
                '%(asctime)s | %(levelname)s | T%(tournament_id)s | %(funcName)s:%(lineno)d | %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            
            file_handler.setFormatter(formatter)
            console_handler.setFormatter(formatter)
            
            logger.addHandler(file_handler)
            logger.addHandler(console_handler)
            logger.setLevel(logging.DEBUG)
            
        return logger
    
    def log_automation_start(self, trigger_type: str, trigger_data: Dict[str, Any]):
        """Log automation process start"""
        self.logger.info(
            f"🚀 AUTOMATION START | Trigger: {trigger_type}",
            extra={'tournament_id': self.tournament_id}
        )
        self.logger.debug(
            f"Trigger data: {json.dumps(trigger_data, default=str)}",
            extra={'tournament_id': self.tournament_id}
        )
        
        # Store in database for monitoring
        AutomationLog.objects.create(
            tournament_id=self.tournament_id,
            event_type='automation_start',
            trigger_type=trigger_type,
            data=trigger_data,
            timestamp=timezone.now()
        )
    
    def log_tournament_state(self, tournament):
        """Log current tournament state"""
        state_data = {
            'id': tournament.id,
            'name': tournament.name,
            'format': tournament.format,
            'status': getattr(tournament, 'automation_status', 'unknown'),
            'current_round': tournament.current_round_number,
            'is_active': tournament.is_active,
            'is_archived': tournament.is_archived,
            'team_count': tournament.teams.count(),
            'stage_count': tournament.stages.count(),
            'round_count': tournament.rounds.count(),
        }
        
        self.logger.info(
            f"📊 TOURNAMENT STATE | Status: {state_data['status']} | Round: {state_data['current_round']}",
            extra={'tournament_id': self.tournament_id}
        )
        self.logger.debug(
            f"Full state: {json.dumps(state_data, default=str)}",
            extra={'tournament_id': self.tournament_id}
        )
        
        return state_data
    
    def log_stage_analysis(self, stages: List[Any]):
        """Log stage configuration and status"""
        stage_data = []
        for stage in stages:
            stage_info = {
                'number': stage.stage_number,
                'name': stage.name,
                'format': stage.format,
                'rounds_in_stage': stage.num_rounds_in_stage,
                'qualifiers': stage.num_qualifiers,
                'teams_in_stage': stage.teams.count() if hasattr(stage, 'teams') else 0,
            }
            stage_data.append(stage_info)
            
            self.logger.info(
                f"🎯 STAGE {stage.stage_number} | {stage.name} | {stage.format} | "
                f"Rounds: {stage.num_rounds_in_stage} | Qualifiers: {stage.num_qualifiers}",
                extra={'tournament_id': self.tournament_id}
            )
        
        self.logger.debug(
            f"All stages: {json.dumps(stage_data, default=str)}",
            extra={'tournament_id': self.tournament_id}
        )
        
        return stage_data
    
    def log_round_analysis(self, rounds: List[Any]):
        """Log round status and completion"""
        round_data = []
        for round_obj in rounds:
            round_info = {
                'number': round_obj.number,
                'stage_number': round_obj.stage.stage_number if round_obj.stage else None,
                'number_in_stage': round_obj.number_in_stage,
                'is_complete': round_obj.is_complete,
                'match_count': round_obj.matches.count() if hasattr(round_obj, 'matches') else 0,
            }
            round_data.append(round_info)
            
            status = "✅ COMPLETE" if round_obj.is_complete else "⏳ INCOMPLETE"
            self.logger.info(
                f"🔄 ROUND {round_obj.number} | Stage {round_info['stage_number']} | "
                f"Matches: {round_info['match_count']} | {status}",
                extra={'tournament_id': self.tournament_id}
            )
        
        return round_data
    
    def log_match_analysis(self, matches: List[Any]):
        """Log match status and completion"""
        match_data = []
        for match in matches:
            match_info = {
                'id': match.id,
                'round_number': match.round_number if hasattr(match, 'round_number') else None,
                'status': match.status,
                'is_completed': match.status == 'completed',
                'team1': str(match.team1) if hasattr(match, 'team1') else None,
                'team2': str(match.team2) if hasattr(match, 'team2') else None,
                'winner': str(match.winner) if hasattr(match, 'winner') and match.winner else None,
            }
            match_data.append(match_info)
            
            status_emoji = "✅" if match_info['is_completed'] else "⏳"
            self.logger.debug(
                f"{status_emoji} MATCH {match.id} | R{match_info['round_number']} | "
                f"{match_info['team1']} vs {match_info['team2']} | {match.status}",
                extra={'tournament_id': self.tournament_id}
            )
        
        completed_count = sum(1 for m in match_data if m['is_completed'])
        total_count = len(match_data)
        
        self.logger.info(
            f"⚽ MATCHES | Total: {total_count} | Completed: {completed_count} | Pending: {total_count - completed_count}",
            extra={'tournament_id': self.tournament_id}
        )
        
        return match_data
    
    def log_decision_point(self, decision: str, reasoning: str, data: Dict[str, Any] = None):
        """Log automation decision points"""
        self.logger.info(
            f"🤔 DECISION | {decision}",
            extra={'tournament_id': self.tournament_id}
        )
        self.logger.info(
            f"💭 REASONING | {reasoning}",
            extra={'tournament_id': self.tournament_id}
        )
        
        if data:
            self.logger.debug(
                f"Decision data: {json.dumps(data, default=str)}",
                extra={'tournament_id': self.tournament_id}
            )
        
        AutomationLog.objects.create(
            tournament_id=self.tournament_id,
            event_type='decision',
            message=decision,
            reasoning=reasoning,
            data=data or {},
            timestamp=timezone.now()
        )
    
    def log_action(self, action: str, details: str, data: Dict[str, Any] = None):
        """Log automation actions"""
        self.logger.info(
            f"⚡ ACTION | {action}",
            extra={'tournament_id': self.tournament_id}
        )
        self.logger.info(
            f"📝 DETAILS | {details}",
            extra={'tournament_id': self.tournament_id}
        )
        
        if data:
            self.logger.debug(
                f"Action data: {json.dumps(data, default=str)}",
                extra={'tournament_id': self.tournament_id}
            )
        
        AutomationLog.objects.create(
            tournament_id=self.tournament_id,
            event_type='action',
            message=action,
            details=details,
            data=data or {},
            timestamp=timezone.now()
        )
    
    def log_error(self, error: Exception, context: str, data: Dict[str, Any] = None):
        """Log automation errors with full context"""
        error_info = {
            'error_type': type(error).__name__,
            'error_message': str(error),
            'traceback': traceback.format_exc(),
            'context': context,
            'data': data or {}
        }
        
        self.logger.error(
            f"❌ ERROR | {context} | {type(error).__name__}: {str(error)}",
            extra={'tournament_id': self.tournament_id}
        )
        self.logger.debug(
            f"Error details: {json.dumps(error_info, default=str)}",
            extra={'tournament_id': self.tournament_id}
        )
        
        AutomationLog.objects.create(
            tournament_id=self.tournament_id,
            event_type='error',
            message=f"{type(error).__name__}: {str(error)}",
            context=context,
            data=error_info,
            timestamp=timezone.now()
        )
    
    def log_success(self, action: str, result: Dict[str, Any]):
        """Log successful automation completion"""
        self.logger.info(
            f"✅ SUCCESS | {action}",
            extra={'tournament_id': self.tournament_id}
        )
        self.logger.debug(
            f"Success result: {json.dumps(result, default=str)}",
            extra={'tournament_id': self.tournament_id}
        )
        
        AutomationLog.objects.create(
            tournament_id=self.tournament_id,
            event_type='success',
            message=action,
            data=result,
            timestamp=timezone.now()
        )
    
    def log_status_change(self, old_status: str, new_status: str, reason: str):
        """Log automation status changes"""
        self.logger.info(
            f"🔄 STATUS CHANGE | {old_status} → {new_status} | Reason: {reason}",
            extra={'tournament_id': self.tournament_id}
        )
        
        AutomationLog.objects.create(
            tournament_id=self.tournament_id,
            event_type='status_change',
            message=f"{old_status} → {new_status}",
            reasoning=reason,
            data={'old_status': old_status, 'new_status': new_status},
            timestamp=timezone.now()
        )


class AutomationLog(models.Model):
    """Database model for storing automation logs"""
    
    EVENT_TYPES = [
        ('automation_start', 'Automation Start'),
        ('decision', 'Decision Point'),
        ('action', 'Action Taken'),
        ('error', 'Error Occurred'),
        ('success', 'Success'),
        ('status_change', 'Status Change'),
    ]
    
    tournament_id = models.IntegerField()
    event_type = models.CharField(max_length=20, choices=EVENT_TYPES)
    message = models.TextField()
    details = models.TextField(blank=True)
    reasoning = models.TextField(blank=True)
    context = models.TextField(blank=True)
    trigger_type = models.CharField(max_length=50, blank=True)
    data = models.JSONField(default=dict)
    timestamp = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['tournament_id', '-timestamp']),
            models.Index(fields=['event_type', '-timestamp']),
        ]
    
    def __str__(self):
        return f"T{self.tournament_id} | {self.event_type} | {self.message[:50]}"


class AutomationMonitor:
    """Real-time monitoring for automation status"""
    
    @staticmethod
    def get_tournament_status(tournament_id: int) -> Dict[str, Any]:
        """Get comprehensive tournament automation status"""
        from .models import Tournament
        
        try:
            tournament = Tournament.objects.get(id=tournament_id)
            
            # Get recent logs
            recent_logs = AutomationLog.objects.filter(
                tournament_id=tournament_id
            ).order_by('-timestamp')[:20]
            
            # Get error count in last hour
            one_hour_ago = timezone.now() - timezone.timedelta(hours=1)
            recent_errors = AutomationLog.objects.filter(
                tournament_id=tournament_id,
                event_type='error',
                timestamp__gte=one_hour_ago
            ).count()
            
            # Get last automation attempt
            last_automation = AutomationLog.objects.filter(
                tournament_id=tournament_id,
                event_type='automation_start'
            ).first()
            
            status = {
                'tournament_id': tournament_id,
                'tournament_name': tournament.name,
                'automation_status': getattr(tournament, 'automation_status', 'unknown'),
                'current_round': tournament.current_round_number,
                'is_active': tournament.is_active,
                'last_automation': last_automation.timestamp if last_automation else None,
                'recent_errors': recent_errors,
                'recent_logs': [
                    {
                        'timestamp': log.timestamp,
                        'event_type': log.event_type,
                        'message': log.message,
                        'details': log.details,
                    }
                    for log in recent_logs
                ],
                'health_status': 'healthy' if recent_errors == 0 else 'warning' if recent_errors < 3 else 'critical'
            }
            
            return status
            
        except Tournament.DoesNotExist:
            return {'error': f'Tournament {tournament_id} not found'}
    
    @staticmethod
    def get_all_tournaments_status() -> List[Dict[str, Any]]:
        """Get status for all active tournaments"""
        from .models import Tournament
        
        active_tournaments = Tournament.objects.filter(is_active=True)
        return [
            AutomationMonitor.get_tournament_status(t.id)
            for t in active_tournaments
        ]

