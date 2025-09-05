"""
Web-based monitoring dashboard for tournament automation
Provides real-time monitoring interface for debugging
"""

import json
from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.views import View
from django.contrib.admin.views.decorators import staff_member_required
from django.utils import timezone
from django.db.models import Count, Q
from datetime import timedelta

from .models import Tournament
from .automation_logger import AutomationLog, AutomationMonitor, AutomationLogger


@staff_member_required
def automation_dashboard(request):
    """Main automation monitoring dashboard"""
    # Get all active tournaments
    active_tournaments = Tournament.objects.filter(is_active=True)
    
    # Get recent automation activity
    recent_activity = AutomationLog.objects.select_related().order_by('-timestamp')[:50]
    
    # Get error statistics
    one_hour_ago = timezone.now() - timedelta(hours=1)
    one_day_ago = timezone.now() - timedelta(days=1)
    
    error_stats = {
        'last_hour': AutomationLog.objects.filter(
            event_type='error',
            timestamp__gte=one_hour_ago
        ).count(),
        'last_day': AutomationLog.objects.filter(
            event_type='error',
            timestamp__gte=one_day_ago
        ).count(),
        'total': AutomationLog.objects.filter(event_type='error').count(),
    }
    
    # Get tournament statuses
    tournament_statuses = []
    for tournament in active_tournaments:
        status = AutomationMonitor.get_tournament_status(tournament.id)
        tournament_statuses.append(status)
    
    context = {
        'tournament_statuses': tournament_statuses,
        'recent_activity': recent_activity,
        'error_stats': error_stats,
        'total_tournaments': active_tournaments.count(),
    }
    
    return render(request, 'tournaments/automation_dashboard.html', context)


@staff_member_required
def tournament_detail_monitoring(request, tournament_id):
    """Detailed monitoring for a specific tournament"""
    tournament = get_object_or_404(Tournament, id=tournament_id)
    
    # Get comprehensive status
    status = AutomationMonitor.get_tournament_status(tournament_id)
    
    # Get all logs for this tournament
    logs = AutomationLog.objects.filter(
        tournament_id=tournament_id
    ).order_by('-timestamp')[:100]
    
    # Get log statistics
    log_stats = AutomationLog.objects.filter(
        tournament_id=tournament_id
    ).values('event_type').annotate(count=Count('id'))
    
    # Get recent errors with details
    recent_errors = AutomationLog.objects.filter(
        tournament_id=tournament_id,
        event_type='error'
    ).order_by('-timestamp')[:10]
    
    # Get tournament structure
    stages = tournament.stages.all().order_by('stage_number')
    rounds = tournament.rounds.all().order_by('number')
    matches = tournament.matches.all().order_by('-id')[:20]
    
    context = {
        'tournament': tournament,
        'status': status,
        'logs': logs,
        'log_stats': log_stats,
        'recent_errors': recent_errors,
        'stages': stages,
        'rounds': rounds,
        'matches': matches,
    }
    
    return render(request, 'tournaments/tournament_monitoring.html', context)


@staff_member_required
def automation_logs_api(request, tournament_id=None):
    """API endpoint for real-time log updates"""
    # Get query parameters
    since_id = request.GET.get('since_id', 0)
    event_type = request.GET.get('event_type')
    limit = int(request.GET.get('limit', 20))
    
    # Build query
    query = AutomationLog.objects.filter(id__gt=since_id)
    
    if tournament_id:
        query = query.filter(tournament_id=tournament_id)
    
    if event_type:
        query = query.filter(event_type=event_type)
    
    logs = query.order_by('-timestamp')[:limit]
    
    # Format logs for JSON response
    log_data = []
    for log in logs:
        log_data.append({
            'id': log.id,
            'tournament_id': log.tournament_id,
            'event_type': log.event_type,
            'message': log.message,
            'details': log.details,
            'reasoning': log.reasoning,
            'context': log.context,
            'timestamp': log.timestamp.isoformat(),
            'data': log.data,
        })
    
    return JsonResponse({
        'logs': log_data,
        'latest_id': logs[0].id if logs else since_id,
        'count': len(log_data),
    })


@staff_member_required
def tournament_status_api(request, tournament_id=None):
    """API endpoint for tournament status updates"""
    if tournament_id:
        status = AutomationMonitor.get_tournament_status(tournament_id)
        return JsonResponse(status)
    else:
        statuses = AutomationMonitor.get_all_tournaments_status()
        return JsonResponse({'tournaments': statuses})


@method_decorator(staff_member_required, name='dispatch')
class AutomationControlView(View):
    """API for controlling automation (reset status, trigger manually, etc.)"""
    
    def post(self, request, tournament_id):
        """Handle automation control actions"""
        tournament = get_object_or_404(Tournament, id=tournament_id)
        action = request.POST.get('action')
        
        logger = AutomationLogger(tournament_id)
        
        try:
            if action == 'reset_status':
                # Reset automation status to idle
                old_status = getattr(tournament, 'automation_status', 'unknown')
                tournament.automation_status = 'idle'
                tournament.save()
                
                logger.log_status_change(
                    old_status, 'idle', 
                    'Manual reset via monitoring dashboard'
                )
                
                return JsonResponse({
                    'success': True,
                    'message': f'Tournament {tournament_id} status reset to idle'
                })
            
            elif action == 'trigger_automation':
                # Manually trigger automation
                from .automation_engine import TournamentAutomationEngine
                
                engine = TournamentAutomationEngine(tournament)
                result = engine.process_tournament()
                
                return JsonResponse({
                    'success': True,
                    'message': f'Automation triggered for tournament {tournament_id}',
                    'result': result
                })
            
            elif action == 'generate_round':
                # Manually generate next round
                from .automation_engine import TournamentAutomationEngine
                
                engine = TournamentAutomationEngine(tournament)
                result = engine.generate_next_round()
                
                return JsonResponse({
                    'success': True,
                    'message': f'Round generation triggered for tournament {tournament_id}',
                    'result': result
                })
            
            elif action == 'advance_stage':
                # Manually advance to next stage
                from .automation_engine import TournamentAutomationEngine
                
                engine = TournamentAutomationEngine(tournament)
                result = engine.advance_to_next_stage()
                
                return JsonResponse({
                    'success': True,
                    'message': f'Stage advancement triggered for tournament {tournament_id}',
                    'result': result
                })
            
            else:
                return JsonResponse({
                    'success': False,
                    'error': f'Unknown action: {action}'
                })
                
        except Exception as e:
            logger.log_error(e, f'Manual action failed: {action}')
            return JsonResponse({
                'success': False,
                'error': str(e)
            })


@staff_member_required
def automation_health_check(request):
    """Health check endpoint for automation system"""
    # Check recent automation activity
    one_hour_ago = timezone.now() - timedelta(hours=1)
    
    # Count recent events
    recent_events = AutomationLog.objects.filter(
        timestamp__gte=one_hour_ago
    ).values('event_type').annotate(count=Count('id'))
    
    # Count errors
    recent_errors = AutomationLog.objects.filter(
        event_type='error',
        timestamp__gte=one_hour_ago
    ).count()
    
    # Check stuck tournaments (processing status for > 10 minutes)
    ten_minutes_ago = timezone.now() - timedelta(minutes=10)
    stuck_tournaments = Tournament.objects.filter(
        automation_status='processing',
        updated_at__lt=ten_minutes_ago
    ).count()
    
    # Determine overall health
    if recent_errors > 5 or stuck_tournaments > 0:
        health_status = 'critical'
    elif recent_errors > 0:
        health_status = 'warning'
    else:
        health_status = 'healthy'
    
    health_data = {
        'status': health_status,
        'timestamp': timezone.now().isoformat(),
        'recent_errors': recent_errors,
        'stuck_tournaments': stuck_tournaments,
        'recent_events': {event['event_type']: event['count'] for event in recent_events},
        'active_tournaments': Tournament.objects.filter(is_active=True).count(),
    }
    
    return JsonResponse(health_data)


@staff_member_required
def export_automation_logs(request, tournament_id=None):
    """Export automation logs as CSV or JSON"""
    format_type = request.GET.get('format', 'json')
    
    # Build query
    query = AutomationLog.objects.all()
    if tournament_id:
        query = query.filter(tournament_id=tournament_id)
    
    # Apply date filters if provided
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    
    if start_date:
        query = query.filter(timestamp__gte=start_date)
    if end_date:
        query = query.filter(timestamp__lte=end_date)
    
    logs = query.order_by('-timestamp')[:1000]  # Limit to 1000 records
    
    if format_type == 'json':
        log_data = []
        for log in logs:
            log_data.append({
                'id': log.id,
                'tournament_id': log.tournament_id,
                'event_type': log.event_type,
                'message': log.message,
                'details': log.details,
                'reasoning': log.reasoning,
                'context': log.context,
                'timestamp': log.timestamp.isoformat(),
                'data': log.data,
            })
        
        response = JsonResponse({'logs': log_data}, json_dumps_params={'indent': 2})
        response['Content-Disposition'] = f'attachment; filename="automation_logs_{tournament_id or "all"}.json"'
        return response
    
    elif format_type == 'csv':
        import csv
        from io import StringIO
        
        output = StringIO()
        writer = csv.writer(output)
        
        # Write header
        writer.writerow([
            'ID', 'Tournament ID', 'Event Type', 'Message', 'Details', 
            'Reasoning', 'Context', 'Timestamp'
        ])
        
        # Write data
        for log in logs:
            writer.writerow([
                log.id, log.tournament_id, log.event_type, log.message,
                log.details, log.reasoning, log.context, log.timestamp
            ])
        
        response = HttpResponse(output.getvalue(), content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="automation_logs_{tournament_id or "all"}.csv"'
        return response
    
    else:
        return JsonResponse({'error': 'Invalid format. Use json or csv.'}, status=400)

