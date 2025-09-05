"""
Team Authentication Views

AJAX endpoints for team login/logout functionality
"""

from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_protect
from django.utils.decorators import method_decorator
from django.contrib import messages
from teams.models import Team
from .team_session_utils import TeamSessionManager
import json


@csrf_protect
@require_http_methods(["POST"])
def team_login(request):
    """
    AJAX endpoint for team login
    
    Expected POST data:
    {
        "team_pin": "ABC123",
        "remember_me": true/false
    }
    """
    try:
        # Parse JSON data
        data = json.loads(request.body)
        team_pin = data.get('team_pin', '').strip()
        remember_me = data.get('remember_me', False)
        
        # Validate PIN format
        if not TeamSessionManager.is_valid_pin_format(team_pin):
            return JsonResponse({
                'success': False,
                'error': 'PIN must be exactly 6 alphanumeric characters'
            })
        
        # Format PIN
        formatted_pin = TeamSessionManager.format_pin(team_pin)
        
        # Find team by PIN
        try:
            team = Team.objects.get(pin=formatted_pin)
        except Team.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': 'Invalid team PIN. Please check and try again.'
            })
        
        # Login team
        success = TeamSessionManager.login_team(
            request, 
            formatted_pin, 
            team.name, 
            remember_me
        )
        
        if success:
            return JsonResponse({
                'success': True,
                'team_name': team.name,
                'team_pin': formatted_pin,
                'message': f'Successfully logged in as {team.name}'
            })
        else:
            return JsonResponse({
                'success': False,
                'error': 'Login failed. Please try again.'
            })
            
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': 'Invalid request format'
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': 'An error occurred. Please try again.'
        })


@csrf_protect
@require_http_methods(["POST"])
def team_logout(request):
    """
    AJAX endpoint for team logout
    """
    try:
        # Get current team info before logout
        team_name = TeamSessionManager.get_team_name(request)
        
        # Logout team
        TeamSessionManager.logout_team(request)
        
        return JsonResponse({
            'success': True,
            'message': f'Successfully logged out{" from " + team_name if team_name else ""}'
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': 'Logout failed. Please try again.'
        })


@require_http_methods(["GET"])
def team_session_status(request):
    """
    Get current team session status
    """
    try:
        session_data = TeamSessionManager.get_team_session_data(request)
        
        return JsonResponse({
            'success': True,
            'data': session_data
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': 'Failed to get session status'
        })

