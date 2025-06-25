# Session Management Utilities
from django.utils import timezone
from django.conf import settings
import re

class CodenameSessionManager:
    """
    Utility class for managing codename sessions
    """
    
    @staticmethod
    def is_valid_codename(codename):
        """Validate codename format (6 characters, alphanumeric)"""
        if not codename:
            return False
        return bool(re.match(r'^[A-Z0-9]{6}$', codename.upper()))
    
    @staticmethod
    def login_player(request, codename):
        """Store player codename in session"""
        if not CodenameSessionManager.is_valid_codename(codename):
            return False
        
        request.session['player_codename'] = codename.upper()
        request.session['codename_login_time'] = timezone.now().isoformat()
        request.session['session_active'] = True
        return True
    
    @staticmethod
    def logout_player(request):
        """Clear player session"""
        session_keys = ['player_codename', 'codename_login_time', 'session_active']
        for key in session_keys:
            request.session.pop(key, None)
    
    @staticmethod
    def get_logged_in_codename(request):
        """Get currently logged in codename"""
        if request.session.get('session_active'):
            return request.session.get('player_codename')
        return None
    
    @staticmethod
    def is_logged_in(request):
        """Check if player is logged in"""
        return bool(request.session.get('session_active') and 
                   request.session.get('player_codename'))
    
    @staticmethod
    def get_session_info(request):
        """Get complete session information"""
        if not CodenameSessionManager.is_logged_in(request):
            return None
        
        return {
            'codename': request.session.get('player_codename'),
            'login_time': request.session.get('codename_login_time'),
            'is_active': True
        }



class TeamPinSessionManager:
    """
    Utility class for managing team PIN sessions
    """
    
    @staticmethod
    def is_valid_pin(pin):
        """Validate team PIN format (6 characters, alphanumeric)"""
        if not pin:
            return False
        return bool(re.match(r'^[A-Z0-9]{6}$', pin.upper()))
    
    @staticmethod
    def login_team(request, pin):
        """Store team PIN in session"""
        if not TeamPinSessionManager.is_valid_pin(pin):
            return False
        
        request.session['team_pin'] = pin.upper()
        request.session['team_login_time'] = timezone.now().isoformat()
        request.session['team_session_active'] = True
        return True
    
    @staticmethod
    def logout_team(request):
        """Clear team session"""
        session_keys = ['team_pin', 'team_login_time', 'team_session_active']
        for key in session_keys:
            request.session.pop(key, None)
    
    @staticmethod
    def get_logged_in_pin(request):
        """Get currently logged in team PIN"""
        if request.session.get('team_session_active'):
            return request.session.get('team_pin')
        return None
    
    @staticmethod
    def is_team_logged_in(request):
        """Check if team is logged in"""
        return bool(request.session.get('team_session_active') and 
                   request.session.get('team_pin'))
    
    @staticmethod
    def get_team_session_info(request):
        """Get complete team session information"""
        if not TeamPinSessionManager.is_team_logged_in(request):
            return None
        
        return {
            'pin': request.session.get('team_pin'),
            'login_time': request.session.get('team_login_time'),
            'is_active': True
        }
    
    @staticmethod
    def get_team_by_pin(pin):
        """Get team object by PIN (helper method)"""
        from teams.models import Team
        try:
            return Team.objects.get(pin=pin.upper())
        except Team.DoesNotExist:
            return None

    @staticmethod
    def get_player_by_codename(codename):
        """Get player object by codename (helper method)"""
        try:
            from friendly_games.models import PlayerCodename
            player_codename = PlayerCodename.objects.get(codename=codename.upper())
            return player_codename.player
        except:
            return None


class SessionManager:
    """
    Combined session manager for both players and teams
    """
    
    @staticmethod
    def get_session_context(request):
        """Get complete session context for templates"""
        context = {
            'session_codename': CodenameSessionManager.get_logged_in_codename(request),
            'player_logged_in': CodenameSessionManager.is_logged_in(request),
            'team_pin': TeamPinSessionManager.get_logged_in_pin(request),
            'team_logged_in': TeamPinSessionManager.is_team_logged_in(request),
        }
        
        # Add player object and name if logged in
        if context['player_logged_in'] and context['session_codename']:
            player = TeamPinSessionManager.get_player_by_codename(context['session_codename'])
            context['logged_in_player'] = player
            context['player_name'] = player.name if player else context['session_codename']
        
        # Add team object if logged in
        if context['team_logged_in']:
            team = TeamPinSessionManager.get_team_by_pin(context['team_pin'])
            context['logged_in_team'] = team
            context['team_name'] = team.name if team else None
        
        return context

