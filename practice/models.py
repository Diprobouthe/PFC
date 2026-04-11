"""
Practice Models for PFC Shooting Practice (v0.1)

Simple training module for recording shooting attempts with exact sequence tracking.
Follows PFC design principles and maintains non-breaking requirements.
"""

from django.db import models
from django.utils import timezone
from django.core.validators import MinValueValidator, MaxValueValidator
import uuid


class PracticeSession(models.Model):
    """
    A shooting practice session linked to a player via codename.
    Stores session metadata and timing information.
    """
    
    PRACTICE_TYPES = [
        ('shooting', 'Shooting'),
        ('pointing', 'Pointing'),
        # Future: ('strategy', 'Strategy')
    ]
    
    DISTANCE_CHOICES = [
        ('6m', '6 meters'),
        ('7m', '7 meters'),
        ('8m', '8 meters'),
        ('9m', '9 meters'),
        ('10m', '10 meters'),
        ('ing', 'InG'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    player_codename = models.CharField(
        max_length=50, 
        db_index=True,
        help_text="Player codename from PFC system"
    )
    practice_type = models.CharField(
        max_length=20, 
        choices=PRACTICE_TYPES, 
        default='shooting',
        db_index=True
    )
    
    # Session attributes (required before starting)
    sequence_tracking = models.BooleanField(
        default=True,
        help_text="If True, shots must be entered in order. If False, any order is allowed."
    )
    distance = models.CharField(
        max_length=3,
        choices=DISTANCE_CHOICES,
        default='7m',
        help_text="Fixed throwing distance for the entire session"
    )
    
    # Session timing
    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    
    # Optional metadata for future use
    court = models.CharField(max_length=50, blank=True, help_text="Court identifier")
    terrain = models.CharField(max_length=50, blank=True, help_text="Terrain type")
    notes = models.TextField(blank=True, help_text="Optional session notes")
    
    # Computed statistics (updated on shot creation)
    total_shots = models.PositiveIntegerField(default=0)
    # Shooting practice stats
    hits = models.PositiveIntegerField(default=0)
    petit_carreaux = models.PositiveIntegerField(default=0)
    carreaux = models.PositiveIntegerField(default=0)
    misses = models.PositiveIntegerField(default=0)
    # Pointing practice stats
    perfects = models.PositiveIntegerField(default=0)
    petit_perfects = models.PositiveIntegerField(default=0)
    goods = models.PositiveIntegerField(default=0)
    fairs = models.PositiveIntegerField(default=0)
    fars = models.PositiveIntegerField(default=0)
    
    is_active = models.BooleanField(default=True, db_index=True)
    
    class Meta:
        db_table = 'practice_sessions'
        ordering = ['-started_at']
        indexes = [
            models.Index(fields=['player_codename', '-started_at']),
            models.Index(fields=['practice_type', '-started_at']),
        ]
    
    def __str__(self):
        return f"Practice {self.practice_type} - {self.player_codename} ({self.started_at.strftime('%Y-%m-%d %H:%M')})"
    
    @property
    def duration(self):
        """Calculate session duration"""
        if self.ended_at:
            return self.ended_at - self.started_at
        return timezone.now() - self.started_at
    
    @property
    def hit_percentage(self):
        """Calculate hit percentage (success rate for both shooting and pointing)"""
        if self.total_shots == 0:
            return 0.0
        
        if self.practice_type == 'shooting':
            # For shooting: hits + petit_carreaux + carreaux = successful shots
            successful_shots = self.hits + self.petit_carreaux + self.carreaux
        else:  # pointing
            # For pointing: perfects + petit_perfects + goods + fairs = successful shots
            successful_shots = self.perfects + self.petit_perfects + self.goods + self.fairs
        
        return (successful_shots / self.total_shots) * 100
    
    @property
    def carreau_percentage(self):
        """Calculate carreau percentage"""
        if self.total_shots == 0:
            return 0.0
        return (self.carreaux / self.total_shots) * 100
    
    @property
    def petit_carreau_percentage(self):
        """Calculate petit carreau percentage"""
        if self.total_shots == 0:
            return 0.0
        return (self.petit_carreaux / self.total_shots) * 100
    
    @property
    def miss_percentage(self):
        """Calculate miss percentage"""
        if self.total_shots == 0:
            return 0.0
        return (self.misses / self.total_shots) * 100
    
    def end_session(self):
        """Mark session as ended"""
        if self.is_active:
            self.ended_at = timezone.now()
            self.is_active = False
            self.save(update_fields=['ended_at', 'is_active'])
    
    def update_statistics(self):
        """Recalculate statistics from shots"""
        shots = self.shots.all()
        self.total_shots = shots.count()
        # Shooting practice stats
        self.hits = shots.filter(outcome='hit').count()
        self.petit_carreaux = shots.filter(outcome='petit_carreau').count()
        self.carreaux = shots.filter(outcome='carreau').count()
        self.misses = shots.filter(outcome='miss').count()
        # Pointing practice stats
        self.perfects = shots.filter(outcome='perfect').count()
        self.petit_perfects = shots.filter(outcome='petit_perfect').count()
        self.goods = shots.filter(outcome='good').count()
        self.fairs = shots.filter(outcome='fair').count()
        self.fars = shots.filter(outcome='far').count()
        self.save(update_fields=['total_shots', 'hits', 'petit_carreaux', 'carreaux', 'misses', 'perfects', 'petit_perfects', 'goods', 'fairs', 'fars'])


class Shot(models.Model):
    """
    Individual shot within a practice session.
    Maintains exact sequence order for pattern analysis.
    """
    
    SHOT_OUTCOMES = [
        # Shooting practice outcomes
        ('miss', 'Miss'),
        ('hit', 'Hit'),
        ('petit_carreau', 'Petit Carreau'),  # Small perfect shot
        ('carreau', 'Carreau'),              # Perfect shot
        # Pointing practice outcomes
        ('perfect', 'Perfect'),        # 0-5cm
        ('petit_perfect', 'Petit Perfect'),  # 5-10cm
        ('good', 'Good'),              # 10-30cm
        ('far', 'Far'),                # 30cm-1m
        ('very_far', 'Very Far'),      # >1m
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(
        PracticeSession, 
        on_delete=models.CASCADE, 
        related_name='shots'
    )
    
    # Sequence tracking (critical for pattern analysis)
    sequence_number = models.PositiveIntegerField(
        validators=[MinValueValidator(1)],
        help_text="Order in sequence (1, 2, 3, ...)"
    )
    
    outcome = models.CharField(
        max_length=20, 
        choices=SHOT_OUTCOMES,
        db_index=True
    )
    
    timestamp = models.DateTimeField(auto_now_add=True)
    
    # Optional distance measurement (for pointing practice)
    distance_cm = models.PositiveIntegerField(
        null=True, 
        blank=True,
        help_text="Distance from target in centimeters (for pointing practice)"
    )
    
    # Optional future metadata
    notes = models.CharField(max_length=200, blank=True)
    
    class Meta:
        db_table = 'practice_shots'
        ordering = ['sequence_number']
        unique_together = ['session', 'sequence_number']
        indexes = [
            models.Index(fields=['session', 'sequence_number']),
            models.Index(fields=['outcome', 'timestamp']),
        ]
    
    def __str__(self):
        return f"Shot #{self.sequence_number}: {self.get_outcome_display()}"
    
    def save(self, *args, **kwargs):
        if not self.sequence_number:
            last_shot = Shot.objects.filter(session=self.session).order_by('-sequence_number').first()
            self.sequence_number = (last_shot.sequence_number + 1) if last_shot else 1
        elif self.session.sequence_tracking:
            last_shot = Shot.objects.filter(session=self.session).order_by('-sequence_number').first()
            expected_number = (last_shot.sequence_number + 1) if last_shot else 1
            if self.sequence_number != expected_number:
                from django.core.exceptions import ValidationError
                raise ValidationError(f"Sequence tracking is ON. Expected shot #{expected_number}, got #{self.sequence_number}")
        
        super().save(*args, **kwargs)
        self.session.update_statistics()


class PracticeStatistics(models.Model):
    """
    Aggregated statistics for a player's practice sessions.
    Updated periodically for performance optimization.
    """
    
    player_codename = models.CharField(max_length=50, unique=True, db_index=True)
    
    # Overall statistics
    total_sessions = models.PositiveIntegerField(default=0)
    total_shots = models.PositiveIntegerField(default=0)
    total_hits = models.PositiveIntegerField(default=0)
    total_carreaux = models.PositiveIntegerField(default=0)
    total_misses = models.PositiveIntegerField(default=0)
    
    # Performance metrics
    best_hit_streak = models.PositiveIntegerField(default=0)
    average_session_length = models.DurationField(null=True, blank=True)
    
    # Pattern analysis (for future use)
    common_miss_position = models.CharField(
        max_length=50, 
        blank=True,
        help_text="e.g., 'shots 4-6', 'after shot 10'"
    )
    
    last_updated = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'practice_statistics'
        verbose_name_plural = 'Practice Statistics'
    
    def __str__(self):
        return f"Stats for {self.player_codename}"
    
    @property
    def overall_hit_percentage(self):
        """Calculate overall hit percentage"""
        if self.total_shots == 0:
            return 0.0
        return (self.total_hits / self.total_shots) * 100
    
    @property
    def overall_carreau_percentage(self):
        """Calculate overall carreau percentage"""
        if self.total_shots == 0:
            return 0.0
        return (self.total_carreaux / self.total_shots) * 100
    
    @classmethod
    def update_for_player(cls, player_codename):
        """Update statistics for a specific player"""
        sessions = PracticeSession.objects.filter(
            player_codename=player_codename,
            is_active=False  # Only completed sessions
        )
        
        if not sessions.exists():
            return
        
        # Calculate aggregated statistics
        total_sessions = sessions.count()
        total_shots = sum(s.total_shots for s in sessions)
        total_hits = sum(s.hits for s in sessions)
        total_carreaux = sum(s.carreaux for s in sessions)
        total_misses = sum(s.misses for s in sessions)
        
        # Calculate best hit streak across all sessions
        best_streak = 0
        for session in sessions:
            current_streak = 0
            max_session_streak = 0
            for shot in session.shots.all():
                if shot.outcome in ['hit', 'carreau']:
                    current_streak += 1
                    max_session_streak = max(max_session_streak, current_streak)
                else:
                    current_streak = 0
            best_streak = max(best_streak, max_session_streak)
        
        # Update or create statistics record
        stats, created = cls.objects.get_or_create(
            player_codename=player_codename,
            defaults={
                'total_sessions': total_sessions,
                'total_shots': total_shots,
                'total_hits': total_hits,
                'total_carreaux': total_carreaux,
                'total_misses': total_misses,
                'best_hit_streak': best_streak,
            }
        )
        
        if not created:
            stats.total_sessions = total_sessions
            stats.total_shots = total_shots
            stats.total_hits = total_hits
            stats.total_carreaux = total_carreaux
            stats.total_misses = total_misses
            stats.best_hit_streak = best_streak
            stats.save()
        
        return stats
