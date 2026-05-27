"""
Practice Models for PFC Shooting Practice (v0.2)

Adds:
- court_complex FK on PracticeSession (nullable, for court-aware sessions)
- atelier (int 1-5) and shot_distance on Shot (for Tir de Précision structured drills)
- 'tir_de_precision' drill type

All new fields are nullable/blank so existing sessions are fully unaffected.
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
    ]

    DISTANCE_CHOICES = [
        ('6m', '6 meters'),
        ('7m', '7 meters'),
        ('8m', '8 meters'),
        ('9m', '9 meters'),
        ('10m', '10 meters'),
        ('ing', 'InG'),
    ]

    DRILL_TYPE_CHOICES = [
        ('open', 'Open Shot'),
        ('boule_in_line', 'Balls in a Line'),
        ('hidden_target', 'Hidden Target'),
        ('boule_behind_boule', 'Boule Behind Boule'),
        ('sequence', 'Sequence Drill'),
        ('tir_de_precision', 'Tir de Précision'),
        ('obstacle', 'Obstacle Shot'),
        ('tactical', 'Tactical Situation'),
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
        help_text="Fixed throwing distance for the entire session (not used for Tir de Précision)"
    )
    drill_type = models.CharField(
        max_length=30,
        blank=True,
        default='',
        help_text="Type of shooting drill for this session (empty = open shot)"
    )

    # Court complex association (optional, used for Tir de Précision and future drills)
    court_complex = models.ForeignKey(
        'courts.CourtComplex',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='practice_sessions',
        help_text="Court complex where this session takes place"
    )

    # Session timing
    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    # Optional metadata
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
    # Tir de Précision total score (sum of points across all shots)
    tdp_score = models.PositiveIntegerField(
        default=0,
        help_text="Total Tir de Précision score (max 100 for a full 20-shot session)"
    )

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
    def is_tir_de_precision(self):
        return self.drill_type == 'tir_de_precision'

    @property
    def is_tactical(self):
        return self.drill_type == 'tactical'

    @property
    def is_sequence(self):
        return self.drill_type == 'sequence'

    @property
    def duration(self):
        if self.ended_at:
            return self.ended_at - self.started_at
        return timezone.now() - self.started_at

    @property
    def hit_percentage(self):
        if self.total_shots == 0:
            return 0.0
        if self.practice_type == 'shooting':
            successful_shots = self.hits + self.petit_carreaux + self.carreaux
        else:
            successful_shots = self.perfects + self.petit_perfects + self.goods + self.fairs
        return (successful_shots / self.total_shots) * 100

    @property
    def carreau_percentage(self):
        if self.total_shots == 0:
            return 0.0
        return (self.carreaux / self.total_shots) * 100

    @property
    def petit_carreau_percentage(self):
        if self.total_shots == 0:
            return 0.0
        return (self.petit_carreaux / self.total_shots) * 100

    @property
    def miss_percentage(self):
        if self.total_shots == 0:
            return 0.0
        return (self.misses / self.total_shots) * 100

    def end_session(self):
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
        # Tir de Précision / Tactical / Sequence score (all use tdp_score field)
        if self.drill_type in ('tir_de_precision', 'tactical', 'sequence'):
            score = 0
            for s in shots:
                score += s.tdp_points
            self.tdp_score = score
        self.save(update_fields=[
            'total_shots', 'hits', 'petit_carreaux', 'carreaux', 'misses',
            'perfects', 'petit_perfects', 'goods', 'fairs', 'fars', 'tdp_score'
        ])


class Shot(models.Model):
    """
    Individual shot within a practice session.
    Maintains exact sequence order for pattern analysis.

    For Tir de Précision sessions, atelier (1-5) and shot_distance are populated.
    For all other sessions these fields remain null.
    """

    SHOT_OUTCOMES = [
        # Shooting practice outcomes
        ('miss', 'Miss'),
        ('hit', 'Hit'),
        ('petit_carreau', 'Petit Carreau'),
        ('carreau', 'Carreau'),
        # Tir de Précision outcomes (ateliers 1-4)
        ('tdp_manque', 'Manqué (0 pts)'),
        ('tdp_touche', 'Touché (1 pt)'),
        ('tdp_reussi', 'Réussi (3 pts)'),
        ('tdp_carreau', 'Carreau (5 pts)'),
        # Tir de Précision outcomes (atelier 5 — target jack)
        ('tdp_jack_manque', 'Manqué — Jack (0 pts)'),
        ('tdp_jack_touche', 'Touché — Jack (3 pts)'),
        ('tdp_jack_reussi', 'Réussi — Jack (5 pts)'),
        # Pointing practice outcomes
        ('perfect', 'Perfect'),
        ('petit_perfect', 'Petit Perfect'),
        ('good', 'Good'),
        ('far', 'Far'),
        ('very_far', 'Very Far'),
    ]

    # Tir de Précision atelier definitions (used by UI and views)
    # Tactical atelier definitions are in tactical_scenarios.py
    TDP_ATELIERS = [
        {
            'number': 1,
            'name': 'Atelier 1',
            'label': 'Target Boule — Open',
            'description': 'Single target boule at the centre of the circle. No obstacles.',
            'icon': '🎯',
            'has_jack_target': False,
        },
        {
            'number': 2,
            'name': 'Atelier 2',
            'label': 'Target Boule Behind Jack',
            'description': 'Target boule at centre. One obstacle jack placed in front (~10 cm gap).',
            'icon': '🎯🔴',
            'has_jack_target': False,
        },
        {
            'number': 3,
            'name': 'Atelier 3',
            'label': 'Target Boule Between Two Obstacle Boules',
            'description': 'Target boule at centre flanked by two obstacle boules (~3 cm gap each side).',
            'icon': '⚫🎯⚫',
            'has_jack_target': False,
        },
        {
            'number': 4,
            'name': 'Atelier 4',
            'label': 'Target Boule Partially Hidden',
            'description': 'Target boule at centre. One obstacle boule in front, partially blocking the target (~10 cm gap).',
            'icon': '⚫🎯',
            'has_jack_target': False,
        },
        {
            'number': 5,
            'name': 'Atelier 5',
            'label': 'Target Jack (But)',
            'description': 'Target is the jack (cochonnet), placed 20 cm from the front of the circle. No obstacles.',
            'icon': '🔴',
            'has_jack_target': True,
        },
    ]

    TDP_DISTANCES = ['6m', '7m', '8m', '9m']

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(
        PracticeSession,
        on_delete=models.CASCADE,
        related_name='shots'
    )

    # Sequence tracking
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

    # Tir de Précision structured fields (null for all other drill types)
    atelier = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        help_text="Atelier number (1-5) for Tir de Précision sessions"
    )
    shot_distance = models.CharField(
        max_length=3,
        blank=True,
        default='',
        help_text="Throwing distance for this specific shot (e.g. '6m', '7m') — used in Tir de Précision"
    )

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

    @property
    def tdp_points(self):
        """Return the Tir de Précision point value for this shot outcome."""
        mapping = {
            'tdp_manque': 0,
            'tdp_touche': 1,
            'tdp_reussi': 3,
            'tdp_carreau': 5,
            'tdp_jack_manque': 0,
            'tdp_jack_touche': 3,
            'tdp_jack_reussi': 5,
        }
        return mapping.get(self.outcome, 0)

    @property
    def tdp_outcome_label(self):
        """Human-readable label for TdP outcomes."""
        labels = {
            'tdp_manque': 'Manqué',
            'tdp_touche': 'Touché',
            'tdp_reussi': 'Réussi',
            'tdp_carreau': 'Carreau',
            'tdp_jack_manque': 'Manqué',
            'tdp_jack_touche': 'Touché',
            'tdp_jack_reussi': 'Réussi',
        }
        return labels.get(self.outcome, self.get_outcome_display())

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
    """

    player_codename = models.CharField(max_length=50, unique=True, db_index=True)

    total_sessions = models.PositiveIntegerField(default=0)
    total_shots = models.PositiveIntegerField(default=0)
    total_hits = models.PositiveIntegerField(default=0)
    total_carreaux = models.PositiveIntegerField(default=0)
    total_misses = models.PositiveIntegerField(default=0)

    best_hit_streak = models.PositiveIntegerField(default=0)
    average_session_length = models.DurationField(null=True, blank=True)

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
        if self.total_shots == 0:
            return 0.0
        return (self.total_hits / self.total_shots) * 100

    @property
    def overall_carreau_percentage(self):
        if self.total_shots == 0:
            return 0.0
        return (self.total_carreaux / self.total_shots) * 100

    @classmethod
    def update_for_player(cls, player_codename):
        sessions = PracticeSession.objects.filter(
            player_codename=player_codename,
            is_active=False
        )

        if not sessions.exists():
            return

        total_sessions = sessions.count()
        total_shots = sum(s.total_shots for s in sessions)
        total_hits = sum(s.hits for s in sessions)
        total_carreaux = sum(s.carreaux for s in sessions)
        total_misses = sum(s.misses for s in sessions)

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
