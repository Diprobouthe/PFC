"""
Team Session Management Utilities

This module provides session management for team PIN authentication,
similar to the codename authentication system but for teams.
"""

from django.contrib.sessions.models import Session
from django.utils import timezone
from datetime import timedelta
import re


class TeamSessionManager:
    """Manages team PIN sessions for authentication"""
    
    SESSION_KEY = 'team_pin'
    REMEMBER_KEY = 'team_pin_remember'
    TEAM_NAME_KEY = 'team_name'
    
    @classmethod
    def login_team(cls, request, team_pin, team_name, remember_me=False):
        """
        Store team PIN in session for authentication
        
        Args:
            request: Django request object
            team_pin: Team PIN (6 characters)
            team_name: Team name for display
            remember_me: Whether to extend session duration
        """
        # Validate PIN format
        if not cls.is_valid_pin_format(team_pin):
            return False
            
        # Store in session
        request.session[cls.SESSION_KEY] = team_pin.upper()
        request.session[cls.TEAM_NAME_KEY] = team_name
        
        if remember_me:
            request.session[cls.REMEMBER_KEY] = True
            # Extend session to 7 days
            request.session.set_expiry(timedelta(days=7))
        else:
            request.session[cls.REMEMBER_KEY] = False
            # Default session expiry (browser close)
            request.session.set_expiry(0)
            
        return True
    
    @classmethod
    def logout_team(cls, request):
        """Remove team PIN from session"""
        keys_to_remove = [cls.SESSION_KEY, cls.TEAM_NAME_KEY, cls.REMEMBER_KEY]
        for key in keys_to_remove:
            if key in request.session:
                del request.session[key]
    
    @classmethod
    def get_team_pin(cls, request):
        """Get team PIN from session"""
        return request.session.get(cls.SESSION_KEY)
    
    @classmethod
    def get_team_name(cls, request):
        """Get team name from session"""
        return request.session.get(cls.TEAM_NAME_KEY)
    
    @classmethod
    def is_team_logged_in(cls, request):
        """Check if team is logged in"""
        return cls.SESSION_KEY in request.session
    
    @classmethod
    def get_remember_preference(cls, request):
        """Get remember me preference"""
        return request.session.get(cls.REMEMBER_KEY, False)
    
    @classmethod
    def is_valid_pin_format(cls, pin):
        """
        Validate PIN format (6 alphanumeric characters)
        
        Args:
            pin: PIN string to validate
            
        Returns:
            bool: True if valid format, False otherwise
        """
        if not pin:
            return False
        return bool(re.match(r'^[A-Za-z0-9]{6}$', pin))
    
    @classmethod
    def format_pin(cls, pin):
        """
        Format PIN to uppercase
        
        Args:
            pin: PIN string to format
            
        Returns:
            str: Formatted PIN in uppercase
        """
        if not pin:
            return ''
        return pin.upper().strip()
    
    @classmethod
    def get_team_session_data(cls, request):
        """
        Get all team session data
        
        Returns:
            dict: Team session information
        """
        return {
            'team_pin': cls.get_team_pin(request),
            'team_name': cls.get_team_name(request),
            'is_logged_in': cls.is_team_logged_in(request),
            'remember_me': cls.get_remember_preference(request)
        }

