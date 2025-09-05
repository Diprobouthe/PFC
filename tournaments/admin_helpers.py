# admin_helpers.py - Admin functions for tournament management

import logging
from django.contrib import messages
from django.http import HttpResponseRedirect
from django.urls import reverse
from .tasks_new import (
    retry_tournament_automation, 
    manual_advance_stage, 
    manual_generate_round,
    get_tournament_status
)

logger = logging.getLogger("tournaments")

def retry_automation_action(modeladmin, request, queryset):
    """Admin action to retry automation for selected tournaments"""
    count = 0
    for tournament in queryset:
        try:
            retry_tournament_automation(tournament.id)
            count += 1
        except Exception as e:
            messages.error(request, f"Failed to retry automation for {tournament.name}: {e}")
    
    if count > 0:
        messages.success(request, f"Retried automation for {count} tournament(s)")

retry_automation_action.short_description = "Retry automation for selected tournaments"

def advance_stage_action(modeladmin, request, queryset):
    """Admin action to manually advance stage for selected tournaments"""
    count = 0
    for tournament in queryset:
        try:
            manual_advance_stage(tournament.id)
            count += 1
        except Exception as e:
            messages.error(request, f"Failed to advance stage for {tournament.name}: {e}")
    
    if count > 0:
        messages.success(request, f"Advanced stage for {count} tournament(s)")

advance_stage_action.short_description = "Manually advance to next stage"

def generate_round_action(modeladmin, request, queryset):
    """Admin action to manually generate next round for selected tournaments"""
    count = 0
    for tournament in queryset:
        try:
            manual_generate_round(tournament.id)
            count += 1
        except Exception as e:
            messages.error(request, f"Failed to generate round for {tournament.name}: {e}")
    
    if count > 0:
        messages.success(request, f"Generated round for {count} tournament(s)")

generate_round_action.short_description = "Manually generate next round"

def reset_automation_status_action(modeladmin, request, queryset):
    """Admin action to reset automation status to idle"""
    count = 0
    for tournament in queryset:
        try:
            tournament.automation_status = "idle"
            tournament.save()
            count += 1
        except Exception as e:
            messages.error(request, f"Failed to reset status for {tournament.name}: {e}")
    
    if count > 0:
        messages.success(request, f"Reset automation status for {count} tournament(s)")

reset_automation_status_action.short_description = "Reset automation status to idle"

def get_tournament_debug_info(tournament):
    """Get detailed debug information for a tournament"""
    try:
        status = get_tournament_status(tournament.id)
        
        debug_info = []
        debug_info.append(f"Tournament: {status.get('name', 'Unknown')}")
        debug_info.append(f"Format: {status.get('format', 'Unknown')}")
        debug_info.append(f"Automation Status: {status.get('automation_status', 'Unknown')}")
        debug_info.append(f"Current Round: {status.get('current_round', 'None')}")
        debug_info.append(f"Active Teams: {status.get('active_teams', 0)}/{status.get('total_teams', 0)}")
        
        current_stage = status.get('current_stage')
        if current_stage:
            debug_info.append(f"Current Stage: {current_stage['number']} ({current_stage['name']})")
            debug_info.append(f"Stage Format: {current_stage['format']}")
            debug_info.append(f"Stage Rounds: {current_stage['num_rounds']}")
            debug_info.append(f"Stage Qualifiers: {current_stage['num_qualifiers']}")
            debug_info.append(f"Stage Complete: {status.get('stage_complete', False)}")
        
        debug_info.append(f"Tournament Complete: {status.get('tournament_complete', False)}")
        
        return "\n".join(debug_info)
        
    except Exception as e:
        return f"Error getting debug info: {e}"

def tournament_status_view(request, tournament_id):
    """View to display tournament status and debug information"""
    try:
        from .models import Tournament
        tournament = Tournament.objects.get(id=tournament_id)
        
        status = get_tournament_status(tournament_id)
        debug_info = get_tournament_debug_info(tournament)
        
        context = {
            'tournament': tournament,
            'status': status,
            'debug_info': debug_info,
        }
        
        # For now, just return a simple response
        # In a full implementation, this would render a template
        from django.http import HttpResponse
        
        html = f"""
        <html>
        <head><title>Tournament {tournament_id} Status</title></head>
        <body>
        <h1>Tournament Status: {tournament.name}</h1>
        <pre>{debug_info}</pre>
        <hr>
        <h2>Actions</h2>
        <a href="/admin/tournaments/tournament/{tournament_id}/change/">Edit Tournament</a><br>
        <a href="/admin/tournaments/tournament/">Back to Tournament List</a>
        </body>
        </html>
        """
        
        return HttpResponse(html)
        
    except Exception as e:
        from django.http import HttpResponse
        return HttpResponse(f"Error: {e}", status=500)

