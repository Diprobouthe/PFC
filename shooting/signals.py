"""
Signals for Shot Accuracy Tracker

Handles automatic session management based on match events.
"""

from django.db.models.signals import post_save, pre_delete
from django.dispatch import receiver
from django.contrib.auth.models import User
from .models import ShotSession


@receiver(post_save, sender=User)
def create_user_shooting_profile(sender, instance, created, **kwargs):
    """
    Create any necessary shooting-related data when a new user is created.
    Currently not needed, but placeholder for future enhancements.
    """
    if created:
        # Future: Create user shooting preferences, default settings, etc.
        pass


# TODO: Add signal handlers for match completion
# When implementing, you'll want to connect to your match model's signals
# to automatically end in-game shot sessions when matches are completed.

# Example implementation (uncomment and adapt when ready):
"""
@receiver(post_save, sender='matches.Match')
def handle_match_completion(sender, instance, **kwargs):
    '''
    Automatically end active in-game shot sessions when a match is completed.
    '''
    if instance.status == 'completed':  # Adjust based on your match model
        # End all active sessions for this match
        active_sessions = ShotSession.objects.filter(
            match_id=instance.id,
            mode='ingame',
            is_active=True
        )
        
        for session in active_sessions:
            session.end_session()
"""


def auto_end_match_sessions(match_id):
    """
    Utility function to automatically end all active sessions for a match.
    Can be called manually from match completion logic.
    """
    active_sessions = ShotSession.objects.filter(
        match_id=match_id,
        mode='ingame',
        is_active=True
    )
    
    ended_count = 0
    for session in active_sessions:
        session.end_session()
        ended_count += 1
    
    return ended_count
