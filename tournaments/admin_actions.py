"""
Admin actions for tournament management
"""
from django.contrib import admin
from django.contrib import messages
from .completion import check_and_complete_tournament

def complete_and_assign_badges(modeladmin, request, queryset):
    """
    Admin action to manually complete tournaments and assign badges
    """
    completed_count = 0
    error_count = 0
    
    for tournament in queryset:
        try:
            # Mark as completed
            tournament.automation_status = 'completed'
            tournament.save()
            
            # Assign badges
            result = check_and_complete_tournament(tournament)
            
            if result:
                completed_count += 1
                messages.success(request, f'Tournament "{tournament.name}" completed and badges assigned')
            else:
                error_count += 1
                messages.warning(request, f'Tournament "{tournament.name}" completed but badge assignment may have failed')
                
        except Exception as e:
            error_count += 1
            messages.error(request, f'Error completing tournament "{tournament.name}": {str(e)}')
    
    if completed_count > 0:
        messages.success(request, f'Successfully completed {completed_count} tournament(s)')
    if error_count > 0:
        messages.error(request, f'Errors occurred with {error_count} tournament(s)')

complete_and_assign_badges.short_description = "Complete tournaments and assign badges"

def reset_automation_status(modeladmin, request, queryset):
    """
    Admin action to reset tournament automation status to idle
    """
    count = 0
    for tournament in queryset:
        tournament.automation_status = 'idle'
        tournament.save()
        count += 1
    
    messages.success(request, f'Reset automation status for {count} tournament(s) to idle')

reset_automation_status.short_description = "Reset automation status to idle"
