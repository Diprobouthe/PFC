"""
DRF API Views for Shot Accuracy Tracker
"""

from rest_framework import status, permissions
from rest_framework.decorators import api_view, permission_classes, action
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet
from rest_framework.views import APIView
from django.shortcuts import get_object_or_404
from django.contrib.auth.models import User
from django.db.models import Sum, Max, Count, Q
from django.utils import timezone
from django.core.cache import cache
from django.conf import settings
import time

from .models import ShotSession, ShotEvent, Achievement, EarnedAchievement, ShotSessionManager
from .serializers import (
    ShotSessionSerializer, ShotSessionCreateSerializer, ShotEventCreateSerializer,
    SessionSummarySerializer, AchievementSerializer, SessionListSerializer,
    UserStatsSerializer
)
from .permissions import CanAccessSession, CanCreateSession


class ShotSessionViewSet(ModelViewSet):
    """
    ViewSet for managing shot sessions
    """
    
    serializer_class = ShotSessionSerializer
    permission_classes = []  # Temporarily allow anonymous access for testing
    
    def get_queryset(self):
        """Filter sessions by current user or allow anonymous sessions"""
        if self.request.user.is_authenticated:
            return ShotSession.objects.filter(user=self.request.user)
        else:
            # For anonymous users, return sessions without user (testing mode)
            return ShotSession.objects.filter(user__isnull=True)
    
    def get_serializer_class(self):
        """Use different serializers for different actions"""
        if self.action == 'create':
            return ShotSessionCreateSerializer
        elif self.action == 'list':
            return SessionListSerializer
        return ShotSessionSerializer
    
    def create(self, request, *args, **kwargs):
        """Create a new shot session"""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        # Check permissions for in-game sessions
        if serializer.validated_data.get('mode') == 'ingame':
            match_id = serializer.validated_data.get('match_id')
            if not self._can_access_match(request.user, match_id):
                return Response(
                    {'error': 'You do not have permission to track shots for this match'},
                    status=status.HTTP_403_FORBIDDEN
                )
        
        # Check for existing active session (skip for anonymous users)
        active_session = None
        if request.user.is_authenticated:
            active_session = ShotSession.objects.filter(
                user=request.user,
                is_active=True
            ).first()
        
        if active_session:
            return Response(
                {
                    'error': 'You already have an active session',
                    'active_session_id': str(active_session.id)
                },
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Create session with user if authenticated, otherwise anonymous
        if request.user.is_authenticated:
            session = serializer.save(user=request.user)
        else:
            session = serializer.save(user=None)
        
        return Response({
            'session_id': str(session.id),
            'mode': session.mode,
            'match_id': str(session.match_id) if session.match_id else None,
            'is_active': session.is_active
        }, status=status.HTTP_201_CREATED)
    
    def _can_access_match(self, user, match_id):
        """Check if user can access the specified match"""
        # TODO: Implement proper match permission checking
        # For now, allow all authenticated users
        # In production, check if user is participant or scorekeeper
        return True
    
    @action(detail=True, methods=['post'])
    def event(self, request, pk=None):
        """Add a shot event to the session"""
        session = self.get_object()
        
        # Check session permissions
        if not self._can_modify_session(request.user, session):
            return Response(
                {'error': 'You do not have permission to modify this session'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Check if session is active
        if not session.is_active:
            return Response(
                {'error': 'Cannot add events to an ended session'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Rate limiting check
        if not self._check_rate_limit(session):
            return Response(
                {'error': 'Rate limit exceeded. Please wait before recording another shot.'},
                status=status.HTTP_429_TOO_MANY_REQUESTS
            )
        
        # Validate event data
        event_serializer = ShotEventCreateSerializer(data=request.data)
        event_serializer.is_valid(raise_exception=True)
        
        # Record the shot
        try:
            result = ShotSessionManager.record_shot(
                session, 
                event_serializer.validated_data['is_hit']
            )
            
            # Prepare response
            summary_data = {
                'session': result['session'],
                'unlocked_achievements': result['unlocked_achievements']
            }
            
            response_serializer = SessionSummarySerializer(summary_data)
            return Response(response_serializer.data, status=status.HTTP_200_OK)
            
        except ValueError as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    @action(detail=True, methods=['post'])
    def undo(self, request, pk=None):
        """Undo the last shot event"""
        session = self.get_object()
        
        # Check session permissions
        if not self._can_modify_session(request.user, session):
            return Response(
                {'error': 'You do not have permission to modify this session'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Check if session is active
        if not session.is_active:
            return Response(
                {'error': 'Cannot undo events in an ended session'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            result = ShotSessionManager.undo_last_shot(session)
            
            if result['undone']:
                response_serializer = SessionSummarySerializer(result['session'])
                return Response(response_serializer.data, status=status.HTTP_200_OK)
            else:
                return Response(
                    {'error': 'No events to undo'},
                    status=status.HTTP_400_BAD_REQUEST
                )
                
        except ValueError as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    @action(detail=True, methods=['post'])
    def end(self, request, pk=None):
        """End the session"""
        session = self.get_object()
        
        # Check session permissions
        if not self._can_modify_session(request.user, session):
            return Response(
                {'error': 'You do not have permission to modify this session'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        if not session.is_active:
            return Response(
                {'error': 'Session is already ended'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        session.end_session()
        
        return Response({'ok': True}, status=status.HTTP_200_OK)
    
    @action(detail=True, methods=['get'])
    def summary(self, request, pk=None):
        """Get session summary"""
        session = self.get_object()
        
        # Check session permissions
        if not self._can_view_session(request.user, session):
            return Response(
                {'error': 'You do not have permission to view this session'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        response_serializer = SessionSummarySerializer(session)
        return Response(response_serializer.data, status=status.HTTP_200_OK)
    
    def _can_modify_session(self, user, session):
        """Check if user can modify the session"""
        # Only session owner can modify
        return session.user == user
    
    def _can_view_session(self, user, session):
        """Check if user can view the session"""
        # For now, only session owner can view
        # In future, might allow scorekeepers to view in-game sessions
        return session.user == user
    
    def _check_rate_limit(self, session):
        """Check rate limiting for shot events"""
        cache_key = f"shot_rate_limit_{session.id}"
        last_shot_time = cache.get(cache_key)
        
        current_time = time.time()
        min_interval = getattr(settings, 'SHOT_TRACKER_MIN_INTERVAL', 0.3)  # 300ms default
        
        if last_shot_time and (current_time - last_shot_time) < min_interval:
            return False
        
        # Update the cache with current time
        cache.set(cache_key, current_time, timeout=60)  # Cache for 1 minute
        return True


class UserStatsView(APIView):
    """
    View for getting user shooting statistics
    """
    
    permission_classes = []  # Temporarily allow anonymous access for testing
    
    def get(self, request):
        """Get comprehensive user shooting statistics"""
        user = request.user
        
        # Get user's sessions
        sessions = ShotSession.objects.filter(user=user)
        
        # Calculate aggregate stats
        stats = sessions.aggregate(
            total_sessions=Count('id'),
            total_shots=Sum('total_shots'),
            total_hits=Sum('total_hits'),
            best_streak_ever=Max('best_streak')
        )
        
        # Handle null values
        stats['total_sessions'] = stats['total_sessions'] or 0
        stats['total_shots'] = stats['total_shots'] or 0
        stats['total_hits'] = stats['total_hits'] or 0
        stats['best_streak_ever'] = stats['best_streak_ever'] or 0
        
        # Calculate overall hit rate
        if stats['total_shots'] > 0:
            stats['overall_hit_rate'] = stats['total_hits'] / stats['total_shots']
        else:
            stats['overall_hit_rate'] = 0.0
        
        # Count achievements
        stats['achievements_count'] = EarnedAchievement.objects.filter(user=user).count()
        
        # Get recent sessions
        stats['recent_sessions'] = sessions.order_by('-started_at')[:10]
        
        serializer = UserStatsSerializer(stats)
        return Response(serializer.data, status=status.HTTP_200_OK)


class AchievementListView(APIView):
    """
    View for listing available achievements
    """
    
    permission_classes = []  # Temporarily allow anonymous access for testing
    
    def get(self, request):
        """Get list of all available achievements"""
        achievements = Achievement.objects.filter(is_active=True).order_by('threshold')
        serializer = AchievementSerializer(achievements, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


# Function-based views for simpler endpoints

@api_view(['GET'])
@permission_classes([])  # Temporarily allow anonymous access
def active_session(request):
    """Get user's current active session if any"""
    active_session = ShotSession.objects.filter(
        user=request.user,
        is_active=True
    ).first()
    
    if active_session:
        serializer = ShotSessionSerializer(active_session)
        return Response(serializer.data, status=status.HTTP_200_OK)
    else:
        return Response(
            {'error': 'No active session found'},
            status=status.HTTP_404_NOT_FOUND
        )


@api_view(['GET'])
@permission_classes([])  # Temporarily allow anonymous access
def match_sessions(request, match_id):
    """Get all sessions for a specific match"""
    # Check if user has access to this match
    # TODO: Implement proper match permission checking
    
    sessions = ShotSession.objects.filter(
        match_id=match_id,
        mode='ingame'
    ).order_by('-started_at')
    
    serializer = SessionListSerializer(sessions, many=True)
    return Response(serializer.data, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([])  # Temporarily allow anonymous access
def end_all_active_sessions(request):
    """End all active sessions for the user (emergency endpoint)"""
    active_sessions = ShotSession.objects.filter(
        user=request.user,
        is_active=True
    )
    
    count = active_sessions.count()
    
    for session in active_sessions:
        session.end_session()
    
    return Response(
        {'ended_sessions': count},
        status=status.HTTP_200_OK
    )
