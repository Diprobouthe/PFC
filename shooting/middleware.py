"""
Middleware for Shot Accuracy Tracker

Provides rate limiting and security features.
"""

import time
from django.core.cache import cache
from django.http import JsonResponse
from django.conf import settings
from .permissions import get_shot_tracker_setting


class ShotTrackerRateLimitMiddleware:
    """
    Rate limiting middleware for shot recording endpoints
    """
    
    def __init__(self, get_response):
        self.get_response = get_response
        
    def __call__(self, request):
        # Check if this is a shot recording request
        if (request.path.startswith('/api/shoot/') and 
            request.method == 'POST' and 
            '/event/' in request.path):
            
            # Apply rate limiting
            if not self._check_rate_limit(request):
                return JsonResponse({
                    'error': 'Rate limit exceeded. Please slow down.',
                    'retry_after': 60
                }, status=429)
        
        response = self.get_response(request)
        return response
    
    def _check_rate_limit(self, request):
        """Check if request is within rate limits"""
        if not request.user.is_authenticated:
            return True  # Skip for anonymous users
        
        # Get rate limit from settings
        rate_limit = get_shot_tracker_setting('RATE_LIMIT_SHOTS_PER_MINUTE', 60)
        
        # Create cache key
        cache_key = f'shot_rate_limit:{request.user.id}'
        
        # Get current count
        current_count = cache.get(cache_key, 0)
        
        if current_count >= rate_limit:
            return False
        
        # Increment counter
        cache.set(cache_key, current_count + 1, 60)  # 60 second window
        return True


class ShotTrackerSecurityMiddleware:
    """
    Security middleware for shot tracker features
    """
    
    def __init__(self, get_response):
        self.get_response = get_response
        
    def __call__(self, request):
        # Check if shot tracker is enabled
        if request.path.startswith('/api/shoot/'):
            if not getattr(settings, 'FEATURE_SHOOT_TRACKER', True):
                return JsonResponse({
                    'error': 'Shot tracker feature is disabled'
                }, status=503)
        
        response = self.get_response(request)
        return response


class ShotTrackerSessionCleanupMiddleware:
    """
    Middleware to clean up stale shot tracker sessions
    """
    
    def __init__(self, get_response):
        self.get_response = get_response
        self.last_cleanup = 0
        self.cleanup_interval = 3600  # 1 hour
        
    def __call__(self, request):
        # Periodically clean up stale sessions
        now = time.time()
        if now - self.last_cleanup > self.cleanup_interval:
            self._cleanup_stale_sessions()
            self.last_cleanup = now
        
        response = self.get_response(request)
        return response
    
    def _cleanup_stale_sessions(self):
        """Clean up stale sessions in the background"""
        try:
            from .models import ShotSession
            from django.utils import timezone
            from datetime import timedelta
            
            # Get timeout from settings
            timeout_hours = get_shot_tracker_setting('SESSION_TIMEOUT_HOURS', 24)
            cutoff_time = timezone.now() - timedelta(hours=timeout_hours)
            
            # Find and end stale sessions
            stale_sessions = ShotSession.objects.filter(
                is_active=True,
                created_at__lt=cutoff_time
            )
            
            for session in stale_sessions:
                session.end_session()
                
        except Exception:
            # Silently fail - don't break the request
            pass
