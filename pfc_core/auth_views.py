from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.contrib import messages
from .session_utils import CodenameSessionManager
import json

@require_http_methods(["POST"])
def codename_login(request):
    """
    Handle codename login via AJAX or form submission
    """
    try:
        # Handle both AJAX and form data
        if request.content_type == 'application/json':
            data = json.loads(request.body)
            codename = data.get('codename', '').strip().upper()
        else:
            codename = request.POST.get('codename', '').strip().upper()
        
        if not codename:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'error': 'Codename is required'})
            messages.error(request, 'Codename is required')
            return redirect(request.META.get('HTTP_REFERER', '/'))
        
        if CodenameSessionManager.login_player(request, codename):
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': True, 
                    'codename': codename,
                    'message': f'Welcome back, {codename}!'
                })
            messages.success(request, f'Welcome back, {codename}!')
            return redirect(request.META.get('HTTP_REFERER', '/'))
        else:
            error_msg = 'Invalid codename format. Please use 6 alphanumeric characters.'
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'error': error_msg})
            messages.error(request, error_msg)
            return redirect(request.META.get('HTTP_REFERER', '/'))
            
    except Exception as e:
        error_msg = 'An error occurred during login'
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': error_msg})
        messages.error(request, error_msg)
        return redirect(request.META.get('HTTP_REFERER', '/'))

@require_http_methods(["GET", "POST"])
def codename_logout(request):
    """
    Handle codename logout
    """
    try:
        codename = CodenameSessionManager.get_logged_in_codename(request)
        CodenameSessionManager.logout_player(request)
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': True,
                'message': 'Logged out successfully'
            })
        
        if codename:
            messages.success(request, f'Goodbye, {codename}!')
        else:
            messages.info(request, 'Logged out successfully')
        
        return redirect(request.META.get('HTTP_REFERER', '/'))
        
    except Exception as e:
        error_msg = 'An error occurred during logout'
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': error_msg})
        messages.error(request, error_msg)
        return redirect(request.META.get('HTTP_REFERER', '/'))

@require_http_methods(["GET"])
def codename_status(request):
    """
    Get current codename login status (AJAX endpoint)
    """
    try:
        session_info = CodenameSessionManager.get_session_info(request)
        
        if session_info:
            return JsonResponse({
                'logged_in': True,
                'codename': session_info['codename'],
                'login_time': session_info['login_time']
            })
        else:
            return JsonResponse({
                'logged_in': False,
                'codename': None
            })
            
    except Exception as e:
        return JsonResponse({
            'logged_in': False,
            'error': 'Unable to check status'
        })

def quick_login_modal(request):
    """
    Render quick login modal (for AJAX loading)
    """
    return render(request, 'auth/quick_login_modal.html')


# Team Authentication Views
from .team_auth_views import team_login, team_logout, team_session_status

def team_pin_login(request):
    """Wrapper for team login"""
    return team_login(request)

def team_pin_logout(request):
    """Wrapper for team logout"""
    return team_logout(request)

def team_pin_status(request):
    """Wrapper for team session status"""
    return team_session_status(request)

def team_login_modal(request):
    """Render team login modal"""
    return render(request, 'auth/team_login_modal.html')

