"""
Template tags for Shot Accuracy Tracker
"""

from django import template
from django.conf import settings
from django.contrib.auth.models import AnonymousUser

register = template.Library()


@register.inclusion_tag('shooting/shot_tracker_widget.html', takes_context=True)
def shot_tracker_widget(context, mode='practice', match_id=None, inning=None):
    """
    Render the shot tracker widget
    
    Usage:
    {% load shot_tracker_tags %}
    {% shot_tracker_widget mode="practice" %}
    {% shot_tracker_widget mode="ingame" match_id=match.id %}
    """
    request = context.get('request')
    
    # Check if user is authenticated
    if not request or isinstance(request.user, AnonymousUser):
        return {
            'show_widget': False,
            'error': 'Authentication required'
        }
    
    # Check feature flag
    feature_enabled = getattr(settings, 'FEATURE_SHOOT_TRACKER', True)
    
    return {
        'show_widget': feature_enabled,
        'mode': mode,
        'match_id': match_id,
        'inning': inning,
        'feature_shoot_tracker': feature_enabled,
        'user': request.user,
        'csrf_token': context.get('csrf_token', ''),
    }


@register.simple_tag(takes_context=True)
def shot_tracker_enabled(context):
    """
    Check if shot tracker feature is enabled
    
    Usage:
    {% shot_tracker_enabled as tracker_enabled %}
    {% if tracker_enabled %}...{% endif %}
    """
    return getattr(settings, 'FEATURE_SHOOT_TRACKER', True)


@register.simple_tag
def shot_tracker_css():
    """
    Get the CSS file path for shot tracker
    
    Usage:
    <link rel="stylesheet" href="{% shot_tracker_css %}">
    """
    return 'shooting/css/shot-tracker.css'


@register.simple_tag
def shot_tracker_js():
    """
    Get the JS file path for shot tracker
    
    Usage:
    <script src="{% shot_tracker_js %}"></script>
    """
    return 'shooting/js/shot-tracker.js'


@register.filter
def can_track_shots(user, match=None):
    """
    Check if user can track shots for a match
    
    Usage:
    {% if user|can_track_shots:match %}...{% endif %}
    """
    if isinstance(user, AnonymousUser):
        return False
    
    if not match:
        return True  # Practice mode allowed for all authenticated users
    
    # TODO: Implement proper match permission checking
    # For now, allow all authenticated users
    return True


@register.inclusion_tag('shooting/shot_tracker_stats.html', takes_context=True)
def user_shot_stats(context, user=None):
    """
    Render user shooting statistics summary
    
    Usage:
    {% user_shot_stats %}
    {% user_shot_stats user=some_user %}
    """
    request = context.get('request')
    
    if not user:
        user = request.user if request else None
    
    if not user or isinstance(user, AnonymousUser):
        return {'show_stats': False}
    
    # TODO: Fetch user stats from API or database
    # For now, return placeholder
    return {
        'show_stats': True,
        'user': user,
        'stats': {
            'total_sessions': 0,
            'total_shots': 0,
            'hit_rate': 0.0,
            'best_streak': 0
        }
    }


@register.simple_tag
def shot_tracker_api_url():
    """
    Get the base API URL for shot tracker
    
    Usage:
    var apiUrl = '{% shot_tracker_api_url %}';
    """
    return '/api/shoot/'


@register.inclusion_tag('shooting/shot_stats_summary.html', takes_context=True)
def shot_stats_summary(context):
    """
    Display shooting practice statistics summary for the current player
    
    Usage:
    {% load shot_tracker_tags %}
    {% shot_stats_summary %}
    """
    from practice.models import PracticeStatistics, PracticeSession
    from pfc_core.session_utils import CodenameSessionManager
    
    request = context.get('request')
    player = context.get('player')
    
    # Get player codename from context or session
    player_codename = None
    if player and hasattr(player, 'codename'):
        player_codename = player.codename
    elif request:
        player_codename = CodenameSessionManager.get_logged_in_codename(request)
    
    if not player_codename:
        return {'has_stats': False}
    
    # Get or update statistics
    try:
        stats = PracticeStatistics.objects.get(player_codename=player_codename)
    except PracticeStatistics.DoesNotExist:
        # Try to create stats from existing sessions
        stats = PracticeStatistics.update_for_player(player_codename)
        if not stats:
            return {'has_stats': False}
    
    # Get recent sessions
    recent_sessions = PracticeSession.objects.filter(
        player_codename=player_codename,
        is_active=False
    ).order_by('-ended_at')[:5]
    
    return {
        'has_stats': True,
        'stats': stats,
        'recent_sessions': recent_sessions,
        'player_codename': player_codename,
    }
