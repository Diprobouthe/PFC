"""
Shot Accuracy Tracker Models

Domain model implementation following the PFC Shot Accuracy Tracker specification.
Tracks shooting sessions, events, achievements, and earned achievements.
"""

from django.db import models
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone
from django.db import transaction
import uuid


class ShotSession(models.Model):
    """
    A shooting session that can be either practice or in-game.
    Tracks overall statistics and current state.
    """
    
    MODE_CHOICES = [
        ('practice', 'Practice'),
        ('ingame', 'In-Game'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='shot_sessions', null=True, blank=True)
    mode = models.CharField(max_length=20, choices=MODE_CHOICES, db_index=True)
    match_id = models.UUIDField(null=True, blank=True, help_text="Required if mode is 'ingame'")
    inning = models.SmallIntegerField(
        null=True, 
        blank=True, 
        validators=[MinValueValidator(1), MaxValueValidator(20)],
        help_text="Optional future use for tracking specific innings"
    )
    
    # Timestamps
    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    
    # Counters for fast UI access
    total_shots = models.PositiveIntegerField(default=0)
    total_hits = models.PositiveIntegerField(default=0)
    best_streak = models.PositiveIntegerField(default=0)
    current_streak = models.PositiveIntegerField(default=0)
    
    is_active = models.BooleanField(default=True)
    
    class Meta:
        ordering = ['-started_at']
        indexes = [
            models.Index(fields=['user', 'mode']),
            models.Index(fields=['match_id']),
            models.Index(fields=['is_active']),
        ]
    
    def __str__(self):
        return f"{self.user.username} - {self.mode} session ({self.started_at.strftime('%Y-%m-%d %H:%M')})"
    
    @property
    def hit_rate(self):
        """Calculate hit percentage as decimal (0.0 to 1.0)"""
        if self.total_shots == 0:
            return 0.0
        return self.total_hits / self.total_shots
    
    @property
    def hit_percentage(self):
        """Calculate hit percentage as integer (0 to 100)"""
        return round(self.hit_rate * 100)
    
    def end_session(self):
        """End the session and mark as inactive"""
        self.is_active = False
        self.ended_at = timezone.now()
        self.save(update_fields=['is_active', 'ended_at'])
    
    def clean(self):
        """Validate model constraints"""
        from django.core.exceptions import ValidationError
        
        if self.mode == 'ingame' and not self.match_id:
            raise ValidationError("match_id is required when mode is 'ingame'")
        
        if self.mode == 'practice' and self.match_id:
            raise ValidationError("match_id should not be set when mode is 'practice'")


class ShotEvent(models.Model):
    """
    Individual shot events within a session.
    Append-only model for maintaining shot sequence.
    """
    
    id = models.BigAutoField(primary_key=True)
    session = models.ForeignKey(ShotSession, on_delete=models.CASCADE, related_name='events')
    idx = models.PositiveIntegerField(help_text="Sequential index within session")
    is_hit = models.BooleanField()
    timestamp = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['idx']
        unique_together = [('session', 'idx')]
        indexes = [
            models.Index(fields=['session', 'idx']),
            models.Index(fields=['timestamp']),
        ]
    
    def __str__(self):
        hit_miss = "HIT" if self.is_hit else "MISS"
        return f"Shot {self.idx + 1}: {hit_miss} ({self.session.user.username})"
    
    def save(self, *args, **kwargs):
        """Auto-assign idx if not set"""
        if self.idx is None:
            # Get the next index for this session
            last_event = ShotEvent.objects.filter(session=self.session).order_by('-idx').first()
            self.idx = (last_event.idx + 1) if last_event else 0
        
        super().save(*args, **kwargs)


class Achievement(models.Model):
    """
    Configuration-driven achievements for streak thresholds.
    Managed via admin interface.
    """
    
    code = models.CharField(max_length=50, unique=True, help_text="Unique achievement code (e.g., STREAK_5)")
    name = models.CharField(max_length=100, help_text="Display name (e.g., '5 in a row')")
    description = models.TextField(blank=True, help_text="Optional description")
    threshold = models.PositiveIntegerField(help_text="Streak threshold to unlock this achievement")
    
    # Display options
    icon = models.CharField(max_length=50, blank=True, help_text="CSS icon class or emoji")
    color = models.CharField(max_length=7, default="#FFD700", help_text="Hex color for badge")
    
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['threshold', 'code']
        indexes = [
            models.Index(fields=['threshold']),
            models.Index(fields=['is_active']),
        ]
    
    def __str__(self):
        return f"{self.name} (Streak {self.threshold})"


class EarnedAchievement(models.Model):
    """
    Tracks which achievements users have earned in specific sessions.
    """
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='earned_achievements')
    session = models.ForeignKey(ShotSession, on_delete=models.CASCADE, related_name='earned_achievements')
    achievement = models.ForeignKey(Achievement, on_delete=models.CASCADE, related_name='earned_by')
    earned_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = [('user', 'session', 'achievement')]
        ordering = ['-earned_at']
        indexes = [
            models.Index(fields=['user', 'achievement']),
            models.Index(fields=['session']),
        ]
    
    def __str__(self):
        return f"{self.user.username} earned {self.achievement.name} ({self.earned_at.strftime('%Y-%m-%d %H:%M')})"


class ShotSessionManager:
    """
    Business logic manager for shot sessions.
    Handles event recording, counter updates, and achievement checking.
    """
    
    @staticmethod
    def record_shot(session, is_hit):
        """
        Record a shot event and update session counters.
        Returns updated session data and any newly unlocked achievements.
        """
        if not session.is_active:
            raise ValueError("Cannot record shots in an ended session")
        
        with transaction.atomic():
            # Create the shot event
            event = ShotEvent.objects.create(
                session=session,
                is_hit=is_hit
            )
            
            # Update counters
            session.total_shots += 1
            if is_hit:
                session.total_hits += 1
                session.current_streak += 1
                session.best_streak = max(session.best_streak, session.current_streak)
            else:
                session.current_streak = 0
            
            session.save(update_fields=['total_shots', 'total_hits', 'current_streak', 'best_streak'])
            
            # Check for new achievements
            newly_unlocked = ShotSessionManager._check_achievements(session)
            
            return {
                'event': event,
                'session': session,
                'unlocked_achievements': newly_unlocked
            }
    
    @staticmethod
    def undo_last_shot(session):
        """
        Undo the last shot event and recompute counters.
        Returns updated session data.
        """
        if not session.is_active:
            raise ValueError("Cannot undo shots in an ended session")
        
        with transaction.atomic():
            # Get the last event
            last_event = session.events.order_by('-idx').first()
            if not last_event:
                return {'session': session, 'undone': False}
            
            # Delete the event
            last_event.delete()
            
            # Recompute all counters from remaining events
            ShotSessionManager._recompute_counters(session)
            
            return {'session': session, 'undone': True}
    
    @staticmethod
    def _recompute_counters(session):
        """Recompute all session counters from events"""
        events = list(session.events.order_by('idx').values_list('is_hit', flat=True))
        
        session.total_shots = len(events)
        session.total_hits = sum(events)
        
        # Compute streaks
        current_streak = 0
        best_streak = 0
        
        for is_hit in events:
            if is_hit:
                current_streak += 1
                best_streak = max(best_streak, current_streak)
            else:
                current_streak = 0
        
        session.current_streak = current_streak
        session.best_streak = best_streak
        
        session.save(update_fields=['total_shots', 'total_hits', 'current_streak', 'best_streak'])
    
    @staticmethod
    def _check_achievements(session):
        """Check for newly unlocked achievements based on current streak"""
        if session.current_streak == 0:
            return []
        
        # Get achievements that match current streak
        matching_achievements = Achievement.objects.filter(
            threshold=session.current_streak,
            is_active=True
        )
        
        newly_unlocked = []
        for achievement in matching_achievements:
            # Check if not already earned in this session
            earned, created = EarnedAchievement.objects.get_or_create(
                user=session.user,
                session=session,
                achievement=achievement
            )
            
            if created:
                newly_unlocked.append(achievement)
        
        return newly_unlocked
