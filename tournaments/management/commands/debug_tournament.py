"""
Django management command for debugging tournament automation
Usage: python manage.py debug_tournament <tournament_id> [options]
"""

import json
from django.core.management.base import BaseCommand
from django.utils import timezone
from tournaments.debugging_tools import TournamentDebugger, export_tournament_debug_report


class Command(BaseCommand):
    help = 'Debug tournament automation issues'
    
    def add_arguments(self, parser):
        parser.add_argument(
            'tournament_id',
            type=int,
            help='Tournament ID to debug'
        )
        parser.add_argument(
            '--full-report',
            action='store_true',
            help='Generate full diagnostic report'
        )
        parser.add_argument(
            '--timeline',
            type=int,
            default=24,
            help='Hours of timeline to show (default: 24)'
        )
        parser.add_argument(
            '--simulate',
            action='store_true',
            help='Simulate next automation step'
        )
        parser.add_argument(
            '--export',
            type=str,
            help='Export debug report to file'
        )
        parser.add_argument(
            '--recommendations',
            action='store_true',
            help='Show only recommendations'
        )
    
    def handle(self, *args, **options):
        tournament_id = options['tournament_id']
        debugger = TournamentDebugger(tournament_id)
        
        self.stdout.write(f"\n{'='*60}")
        self.stdout.write(f"TOURNAMENT {tournament_id} DEBUG ANALYSIS")
        self.stdout.write(f"{'='*60}")
        self.stdout.write(f"Timestamp: {timezone.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        
        if options['export']:
            self.export_report(tournament_id, options['export'])
            return
        
        if options['recommendations']:
            self.show_recommendations(debugger)
            return
        
        if options['full_report']:
            self.show_full_report(debugger)
        else:
            self.show_summary(debugger)
        
        if options['simulate']:
            self.show_simulation(debugger)
        
        if options['timeline']:
            self.show_timeline(debugger, options['timeline'])
    
    def show_summary(self, debugger):
        """Show summary diagnostic"""
        diagnostic = debugger.run_full_diagnostic()
        
        if 'error' in diagnostic:
            self.stdout.write(self.style.ERROR(diagnostic['error']))
            return
        
        # Tournament info
        info = diagnostic['tournament_info']
        self.stdout.write(f"Tournament: {info['name']} (ID: {info['id']})")
        self.stdout.write(f"Format: {info['format']}")
        self.stdout.write(f"Status: {info['automation_status']}")
        self.stdout.write(f"Current Round: {info['current_round']}")
        self.stdout.write(f"Active: {info['is_active']}")
        
        # Health score
        health_score = diagnostic['health_score']
        if health_score >= 80:
            health_color = self.style.SUCCESS
        elif health_score >= 60:
            health_color = self.style.WARNING
        else:
            health_color = self.style.ERROR
        
        self.stdout.write(f"Health Score: {health_color(f'{health_score}/100')}")
        
        # Quick stats
        self.stdout.write(f"\nQuick Stats:")
        self.stdout.write(f"  Teams: {info['team_count']}")
        self.stdout.write(f"  Stages: {info['stage_count']}")
        self.stdout.write(f"  Rounds: {info['round_count']}")
        self.stdout.write(f"  Matches: {info['match_count']}")
        
        # Error summary
        errors = diagnostic['error_analysis']['error_frequency']
        if errors['last_hour'] > 0:
            self.stdout.write(self.style.ERROR(f"  Errors (last hour): {errors['last_hour']}"))
        if errors['last_day'] > 0:
            self.stdout.write(self.style.WARNING(f"  Errors (last day): {errors['last_day']}"))
        
        # Issues summary
        total_issues = (
            len(diagnostic['stage_analysis']['issues']) +
            len(diagnostic['round_analysis']['issues']) +
            len(diagnostic['match_analysis']['issues']) +
            len(diagnostic['automation_status']['issues'])
        )
        
        if total_issues > 0:
            self.stdout.write(self.style.WARNING(f"  Total Issues: {total_issues}"))
        
        # Recommendations
        recommendations = diagnostic['recommendations']
        if recommendations:
            self.stdout.write(f"\nTop Recommendations:")
            for i, rec in enumerate(recommendations[:3], 1):
                self.stdout.write(f"  {i}. {rec}")
            
            if len(recommendations) > 3:
                self.stdout.write(f"  ... and {len(recommendations) - 3} more")
    
    def show_full_report(self, debugger):
        """Show full diagnostic report"""
        diagnostic = debugger.run_full_diagnostic()
        
        if 'error' in diagnostic:
            self.stdout.write(self.style.ERROR(diagnostic['error']))
            return
        
        # Tournament Info
        self.stdout.write(self.style.HTTP_INFO("TOURNAMENT INFORMATION"))
        info = diagnostic['tournament_info']
        for key, value in info.items():
            self.stdout.write(f"  {key}: {value}")
        
        # Stage Analysis
        self.stdout.write(f"\n{self.style.HTTP_INFO('STAGE ANALYSIS')}")
        stage_analysis = diagnostic['stage_analysis']
        self.stdout.write(f"  Total Stages: {stage_analysis['total_stages']}")
        
        for stage in stage_analysis['stages']:
            status = "✅ Complete" if stage['is_complete'] else "⏳ In Progress"
            self.stdout.write(f"  Stage {stage['number']}: {stage['name']} ({stage['format']}) - {status}")
            self.stdout.write(f"    Rounds: {stage['rounds_completed']}/{stage['rounds_required']}")
            self.stdout.write(f"    Teams: {stage['teams_in_stage']}, Qualifiers: {stage['qualifiers']}")
        
        if stage_analysis['issues']:
            self.stdout.write(f"  {self.style.WARNING('Issues:')}")
            for issue in stage_analysis['issues']:
                self.stdout.write(f"    - {issue}")
        
        # Round Analysis
        self.stdout.write(f"\n{self.style.HTTP_INFO('ROUND ANALYSIS')}")
        round_analysis = diagnostic['round_analysis']
        self.stdout.write(f"  Total Rounds: {round_analysis['total_rounds']}")
        self.stdout.write(f"  Completed: {round_analysis['completed_rounds']}")
        
        for round_info in round_analysis['rounds']:
            status = "✅" if round_info['is_complete'] else "⏳"
            self.stdout.write(f"  {status} Round {round_info['number']} (Stage {round_info['stage_number']})")
            self.stdout.write(f"    Matches: {round_info['completed_matches']}/{round_info['match_count']}")
        
        if round_analysis['issues']:
            self.stdout.write(f"  {self.style.WARNING('Issues:')}")
            for issue in round_analysis['issues']:
                self.stdout.write(f"    - {issue}")
        
        # Match Analysis
        self.stdout.write(f"\n{self.style.HTTP_INFO('MATCH ANALYSIS')}")
        match_analysis = diagnostic['match_analysis']
        self.stdout.write(f"  Total Matches: {match_analysis['total_matches']}")
        
        self.stdout.write("  By Status:")
        for status, count in match_analysis['by_status'].items():
            self.stdout.write(f"    {status}: {count}")
        
        self.stdout.write("  By Round:")
        for round_num, count in match_analysis['by_round'].items():
            self.stdout.write(f"    Round {round_num}: {count}")
        
        if match_analysis['issues']:
            self.stdout.write(f"  {self.style.WARNING('Issues:')}")
            for issue in match_analysis['issues']:
                self.stdout.write(f"    - {issue}")
        
        # Automation Status
        self.stdout.write(f"\n{self.style.HTTP_INFO('AUTOMATION STATUS')}")
        auto_status = diagnostic['automation_status']
        self.stdout.write(f"  Current Status: {auto_status['current_status']}")
        self.stdout.write(f"  Last Automation: {auto_status['last_automation'] or 'Never'}")
        
        self.stdout.write("  Event Counts:")
        for event_type, count in auto_status['event_counts'].items():
            self.stdout.write(f"    {event_type}: {count}")
        
        if auto_status['issues']:
            self.stdout.write(f"  {self.style.WARNING('Issues:')}")
            for issue in auto_status['issues']:
                self.stdout.write(f"    - {issue}")
        
        # Error Analysis
        self.stdout.write(f"\n{self.style.HTTP_INFO('ERROR ANALYSIS')}")
        error_analysis = diagnostic['error_analysis']
        freq = error_analysis['error_frequency']
        self.stdout.write(f"  Last Hour: {freq['last_hour']}")
        self.stdout.write(f"  Last Day: {freq['last_day']}")
        self.stdout.write(f"  Total: {freq['total']}")
        
        if error_analysis['error_types']:
            self.stdout.write("  Error Types:")
            for error_type, errors in error_analysis['error_types'].items():
                self.stdout.write(f"    {error_type}: {len(errors)} occurrences")
        
        # Recommendations
        self.stdout.write(f"\n{self.style.HTTP_INFO('RECOMMENDATIONS')}")
        recommendations = diagnostic['recommendations']
        if recommendations:
            for i, rec in enumerate(recommendations, 1):
                self.stdout.write(f"  {i}. {rec}")
        else:
            self.stdout.write("  No specific recommendations at this time.")
        
        # Health Score
        health_score = diagnostic['health_score']
        if health_score >= 80:
            health_color = self.style.SUCCESS
        elif health_score >= 60:
            health_color = self.style.WARNING
        else:
            health_color = self.style.ERROR
        
        self.stdout.write(f"\n{self.style.HTTP_INFO('OVERALL HEALTH')}")
        self.stdout.write(f"  Score: {health_color(f'{health_score}/100')}")
    
    def show_recommendations(self, debugger):
        """Show only recommendations"""
        diagnostic = debugger.run_full_diagnostic()
        
        if 'error' in diagnostic:
            self.stdout.write(self.style.ERROR(diagnostic['error']))
            return
        
        recommendations = diagnostic['recommendations']
        
        if not recommendations:
            self.stdout.write(self.style.SUCCESS("No specific recommendations - tournament appears healthy!"))
            return
        
        self.stdout.write(f"RECOMMENDATIONS FOR TOURNAMENT {debugger.tournament_id}:")
        self.stdout.write("-" * 50)
        
        for i, rec in enumerate(recommendations, 1):
            self.stdout.write(f"{i}. {rec}")
    
    def show_simulation(self, debugger):
        """Show automation simulation"""
        simulation = debugger.simulate_next_automation_step()
        
        self.stdout.write(f"\n{self.style.HTTP_INFO('AUTOMATION SIMULATION')}")
        
        if 'error' in simulation:
            self.stdout.write(self.style.ERROR(simulation['error']))
            return
        
        current = simulation['current_state']
        self.stdout.write(f"Current State:")
        self.stdout.write(f"  Round: {current['round']}")
        self.stdout.write(f"  Status: {current['status']}")
        
        if simulation['blocking_issues']:
            self.stdout.write(f"\n{self.style.ERROR('Blocking Issues:')}")
            for issue in simulation['blocking_issues']:
                self.stdout.write(f"  ❌ {issue}")
        
        if simulation['next_steps']:
            self.stdout.write(f"\n{self.style.SUCCESS('Next Steps:')}")
            for step in simulation['next_steps']:
                self.stdout.write(f"  ➡️  {step}")
        
        if not simulation['blocking_issues'] and not simulation['next_steps']:
            self.stdout.write(self.style.SUCCESS("\n✅ No automation steps needed - tournament is complete or waiting for matches."))
    
    def show_timeline(self, debugger, hours):
        """Show automation timeline"""
        timeline = debugger.get_automation_timeline(hours)
        
        self.stdout.write(f"\n{self.style.HTTP_INFO(f'AUTOMATION TIMELINE (Last {hours} hours)')}")
        
        if not timeline:
            self.stdout.write("No automation activity in the specified time period.")
            return
        
        for event in timeline:
            timestamp = event['timestamp'][:19].replace('T', ' ')  # Format timestamp
            event_type = event['event_type'].upper()
            message = event['message']
            
            # Color code by event type
            if event_type == 'ERROR':
                color = self.style.ERROR
            elif event_type == 'SUCCESS':
                color = self.style.SUCCESS
            elif event_type == 'WARNING':
                color = self.style.WARNING
            else:
                color = self.style.NOTICE
            
            self.stdout.write(f"  {timestamp} | {color(event_type)} | {message}")
            
            if event['details']:
                self.stdout.write(f"    Details: {event['details']}")
            if event['reasoning']:
                self.stdout.write(f"    Reasoning: {event['reasoning']}")
    
    def export_report(self, tournament_id, filename):
        """Export debug report to file"""
        try:
            report = export_tournament_debug_report(tournament_id)
            
            with open(filename, 'w') as f:
                f.write(report)
            
            self.stdout.write(
                self.style.SUCCESS(f"Debug report exported to: {filename}")
            )
            
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f"Failed to export report: {str(e)}")
            )

