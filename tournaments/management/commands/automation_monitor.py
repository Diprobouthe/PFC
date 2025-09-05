"""
Django management command for monitoring tournament automation
Usage: python manage.py automation_monitor [tournament_id]
"""

import time
import json
from django.core.management.base import BaseCommand
from django.utils import timezone
from tournaments.automation_logger import AutomationMonitor, AutomationLog


class Command(BaseCommand):
    help = 'Monitor tournament automation status and logs'
    
    def add_arguments(self, parser):
        parser.add_argument(
            'tournament_id',
            nargs='?',
            type=int,
            help='Tournament ID to monitor (optional, monitors all if not specified)'
        )
        parser.add_argument(
            '--follow',
            action='store_true',
            help='Follow logs in real-time'
        )
        parser.add_argument(
            '--errors-only',
            action='store_true',
            help='Show only error logs'
        )
        parser.add_argument(
            '--last',
            type=int,
            default=20,
            help='Number of recent logs to show (default: 20)'
        )
    
    def handle(self, *args, **options):
        tournament_id = options.get('tournament_id')
        follow = options.get('follow')
        errors_only = options.get('errors_only')
        last_count = options.get('last')
        
        if follow:
            self.follow_logs(tournament_id, errors_only)
        else:
            self.show_status(tournament_id, errors_only, last_count)
    
    def show_status(self, tournament_id, errors_only, last_count):
        """Show current automation status"""
        if tournament_id:
            status = AutomationMonitor.get_tournament_status(tournament_id)
            self.display_tournament_status(status)
            self.show_recent_logs(tournament_id, errors_only, last_count)
        else:
            statuses = AutomationMonitor.get_all_tournaments_status()
            self.display_all_tournaments_status(statuses)
    
    def follow_logs(self, tournament_id, errors_only):
        """Follow logs in real-time"""
        self.stdout.write(
            self.style.SUCCESS(f"Following automation logs for tournament {tournament_id or 'ALL'}...")
        )
        self.stdout.write("Press Ctrl+C to stop\n")
        
        last_log_id = 0
        
        try:
            while True:
                # Get new logs since last check
                query = AutomationLog.objects.filter(id__gt=last_log_id)
                
                if tournament_id:
                    query = query.filter(tournament_id=tournament_id)
                
                if errors_only:
                    query = query.filter(event_type='error')
                
                new_logs = query.order_by('id')
                
                for log in new_logs:
                    self.display_log(log)
                    last_log_id = log.id
                
                time.sleep(1)  # Check every second
                
        except KeyboardInterrupt:
            self.stdout.write("\nStopped monitoring.")
    
    def display_tournament_status(self, status):
        """Display tournament status"""
        if 'error' in status:
            self.stdout.write(self.style.ERROR(status['error']))
            return
        
        health_color = {
            'healthy': self.style.SUCCESS,
            'warning': self.style.WARNING,
            'critical': self.style.ERROR
        }.get(status['health_status'], self.style.NOTICE)
        
        self.stdout.write(f"\n{'='*60}")
        self.stdout.write(f"Tournament {status['tournament_id']}: {status['tournament_name']}")
        self.stdout.write(f"{'='*60}")
        self.stdout.write(f"Automation Status: {status['automation_status']}")
        self.stdout.write(f"Current Round: {status['current_round']}")
        self.stdout.write(f"Active: {status['is_active']}")
        self.stdout.write(f"Last Automation: {status['last_automation']}")
        self.stdout.write(f"Recent Errors: {status['recent_errors']}")
        self.stdout.write(health_color(f"Health: {status['health_status'].upper()}"))
        self.stdout.write("")
    
    def display_all_tournaments_status(self, statuses):
        """Display status for all tournaments"""
        self.stdout.write(f"\n{'='*80}")
        self.stdout.write("ALL TOURNAMENTS AUTOMATION STATUS")
        self.stdout.write(f"{'='*80}")
        
        for status in statuses:
            if 'error' in status:
                continue
                
            health_icon = {
                'healthy': '✅',
                'warning': '⚠️',
                'critical': '❌'
            }.get(status['health_status'], '❓')
            
            self.stdout.write(
                f"{health_icon} T{status['tournament_id']:2d} | "
                f"{status['tournament_name'][:20]:20s} | "
                f"Status: {status['automation_status']:10s} | "
                f"Round: {status['current_round']:2d} | "
                f"Errors: {status['recent_errors']:2d}"
            )
        
        self.stdout.write("")
    
    def show_recent_logs(self, tournament_id, errors_only, last_count):
        """Show recent logs for a tournament"""
        query = AutomationLog.objects.filter(tournament_id=tournament_id)
        
        if errors_only:
            query = query.filter(event_type='error')
        
        logs = query.order_by('-timestamp')[:last_count]
        
        if not logs:
            self.stdout.write("No logs found.")
            return
        
        self.stdout.write(f"Recent Logs (last {len(logs)}):")
        self.stdout.write("-" * 60)
        
        for log in reversed(logs):  # Show oldest first
            self.display_log(log)
    
    def display_log(self, log):
        """Display a single log entry"""
        # Color coding for event types
        colors = {
            'automation_start': self.style.HTTP_INFO,
            'decision': self.style.NOTICE,
            'action': self.style.SUCCESS,
            'error': self.style.ERROR,
            'success': self.style.SUCCESS,
            'status_change': self.style.WARNING,
        }
        
        color = colors.get(log.event_type, self.style.NOTICE)
        
        # Format timestamp
        timestamp = log.timestamp.strftime('%H:%M:%S')
        
        # Event type icon
        icons = {
            'automation_start': '🚀',
            'decision': '🤔',
            'action': '⚡',
            'error': '❌',
            'success': '✅',
            'status_change': '🔄',
        }
        
        icon = icons.get(log.event_type, '📝')
        
        # Main message
        message = f"{timestamp} | {icon} {log.event_type.upper()} | {log.message}"
        self.stdout.write(color(message))
        
        # Additional details
        if log.details:
            self.stdout.write(f"    Details: {log.details}")
        
        if log.reasoning:
            self.stdout.write(f"    Reasoning: {log.reasoning}")
        
        if log.context:
            self.stdout.write(f"    Context: {log.context}")
        
        # Show data for errors
        if log.event_type == 'error' and log.data:
            if 'traceback' in log.data:
                self.stdout.write("    Traceback:")
                for line in log.data['traceback'].split('\n')[-5:]:  # Last 5 lines
                    if line.strip():
                        self.stdout.write(f"      {line}")
        
        self.stdout.write("")  # Empty line for readability

