"""
Permissions for Shot Accuracy Tracker"""

from rest_framework import permissions
from django.contrib.auth.models import User
from django.conf import settings
from .models import ShotSession


def get_shot_tracker_setting(key, default=None):
    """Get shot tracker setting from Django settings"""
    shot_settings = getattr(settings, 'SHOT_TRACKER_SETTINGS', {})
    return shot_settings.get(key, default)


def get_shot_tracker_permission(key, default=None):
    """Get shot tracker permission from Django settings"""
    permissions_config = getattr(settings, 'SHOT_TRACKER_PERMISSIONS', {})
    return permissions_config.get(key, default)


class CanAccessSession(permissions.BasePermission):
    """
    Permission to check if user can access a shot session
    """
    
    def has_object_permission(self, request, view, obj):
        """Check if user can access this specific session"""
        if not isinstance(obj, ShotSession):
            return False
        
        # Session owner can always access
        if obj.user == request.user:
            return True
        
        # For in-game sessions, check if user is authorized for the match
        if obj.mode == 'ingame':
            return self._can_access_match(request.user, obj.match_id)
        
        return False
    
    def _can_access_match(self, user, match_id):
        """
        Check if user can access the specified match.
        This should be implemented based on your match permission system.
        """
        # TODO: Implement proper match permission checking
        # This might involve checking if the user is:
        # - A participant in the match
        # - A scorekeeper for the match
        # - An admin/organizer
        
        # For now, return True for authenticated users
        # In production, implement proper match access control
        return True


class CanCreateSession(permissions.BasePermission):
    """
    Permission to check if user can create a shot session
    """
    
    def has_permission(self, request, view):
        """Check if user can create sessions"""
        # Check authentication requirement
        if get_shot_tracker_permission('REQUIRE_AUTHENTICATION', True):
            if not request.user.is_authenticated:
                return False
        elif not request.user.is_authenticated:
            # Anonymous users can only create practice sessions if allowed
            if not get_shot_tracker_permission('ALLOW_ANONYMOUS_PRACTICE', False):
                return False
            # Only allow practice mode for anonymous users
            if request.data.get('mode') != 'practice':
                return False
        
        # Check if creating an in-game session
        if request.data.get('mode') == 'ingame':
            match_id = request.data.get('match_id')
            if match_id:
                return self._can_access_match(request.user, match_id)
        
        # Practice sessions are allowed for all authenticated users
        return True
    
    def _can_access_match(self, user, match_id):
        """Check if user can access the specified match"""
        # TODO: Implement proper match permission checking
        return True


class IsSessionOwner(permissions.BasePermission):
    """
    Permission to check if user is the session owner
    """
    
    def has_object_permission(self, request, view, obj):
        """Check if user owns this session"""
        if not isinstance(obj, ShotSession):
            return False
        
        return obj.user == request.user


class CanModifySession(permissions.BasePermission):
    """
    Permission to check if user can modify a session (add events, undo, end)
    """
    
    def has_object_permission(self, request, view, obj):
        """Check if user can modify this session"""
        if not isinstance(obj, ShotSession):
            return False
        
        # Only session owner can modify their own sessions
        if obj.user == request.user:
            return True
        
        # For in-game sessions, authorized scorekeepers might be able to modify
        # TODO: Implement scorekeeper permission checking
        if obj.mode == 'ingame':
            return self._is_authorized_scorekeeper(request.user, obj.match_id)
        
        return False
    
    def _is_authorized_scorekeeper(self, user, match_id):
        """Check if user is an authorized scorekeeper for the match"""
        # TODO: Implement scorekeeper permission checking
        # This might involve checking:
        # - Tournament organizer permissions
        # - Match official assignments
        # - Admin privileges
        
        return False  # For now, only session owners can modify


class CanViewSessionDetails(permissions.BasePermission):
    """
    Permission to check if user can view detailed session information
    """
    
    def has_object_permission(self, request, view, obj):
        """Check if user can view session details"""
        if not isinstance(obj, ShotSession):
            return False
        
        # Session owner can always view
        if obj.user == request.user:
            return True
        
        # For in-game sessions, other participants might be able to view
        if obj.mode == 'ingame':
            return self._can_view_match_sessions(request.user, obj.match_id)
        
        return False
    
    def _can_view_match_sessions(self, user, match_id):
        """Check if user can view sessions for this match"""
        # TODO: Implement match session viewing permissions
        # This might allow:
        # - Match participants to see each other's sessions
        # - Scorekeepers to see all sessions
        # - Tournament organizers to see all sessions
        
        return False  # For now, only session owners can view


# Utility functions for permission checking

def can_user_access_match(user, match_id):
    """
    Utility function to check if user can access a specific match.
    This should be implemented based on your match system.
    """
    # TODO: Implement based on your match model and permissions
    # Example implementation:
    
    try:
        # Import here to avoid circular imports
        from matches.models import Match
        
        match = Match.objects.get(id=match_id)
        
        # Check if user is a participant
        if match.team1 and user in [p.user for p in match.team1.players.all()]:
            return True
        if match.team2 and user in [p.user for p in match.team2.players.all()]:
            return True
        
        # Check if user is a scorekeeper (if you have this concept)
        # if hasattr(match, 'scorekeepers') and user in match.scorekeepers.all():
        #     return True
        
        # Check if user is tournament organizer
        if hasattr(match, 'tournament') and match.tournament:
            # TODO: Check tournament organizer permissions
            pass
        
        return False
        
    except:
        # If match doesn't exist or any error occurs, deny access
        return False


def is_user_scorekeeper_for_match(user, match_id):
    """
    Utility function to check if user is an authorized scorekeeper for a match.
    """
    # TODO: Implement based on your scorekeeper system
    return False


def is_user_tournament_organizer(user, tournament_id):
    """
    Utility function to check if user is a tournament organizer.
    """
    # TODO: Implement based on your tournament organizer system
    return False
