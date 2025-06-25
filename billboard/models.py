from django.db import models
from django.utils import timezone
from datetime import timedelta
from courts.models import CourtComplex


class BillboardEntry(models.Model):
    ACTION_CHOICES = [
        ('AT_COURTS', 'I\'m at the courts'),
        ('GOING_TO_COURTS', 'I\'m going to the courts'),
        ('LOOKING_FOR_MATCH', 'Looking to complete a PFC tournament match'),
    ]
    
    TIME_SLOTS = [
        ('09:00', '09:00'),
        ('10:00', '10:00'),
        ('11:00', '11:00'),
        ('12:00', '12:00'),
        ('13:00', '13:00'),
        ('14:00', '14:00'),
        ('15:00', '15:00'),
        ('16:00', '16:00'),
        ('17:00', '17:00'),
        ('18:00', '18:00'),
        ('19:00', '19:00'),
        ('20:00', '20:00'),
        ('21:00', '21:00'),
        ('22:00', '22:00'),
    ]
    
    codename = models.CharField(max_length=6, help_text="Player codename (required)")
    action_type = models.CharField(max_length=20, choices=ACTION_CHOICES)
    court_complex = models.ForeignKey(CourtComplex, on_delete=models.CASCADE, help_text="Select court complex")
    scheduled_time = models.CharField(max_length=5, choices=TIME_SLOTS, blank=True, null=True, help_text="For 'going to courts' entries")
    scheduled_date = models.DateField(blank=True, null=True, help_text="Date for scheduled appointments")
    opponent_team = models.CharField(max_length=100, blank=True, null=True, help_text="For tournament match requests")
    message = models.TextField(blank=True, null=True, help_text="Optional message")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)
    is_confirmed = models.BooleanField(default=False, help_text="True when opponent team has confirmed the match")
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = "Billboard Entry"
        verbose_name_plural = "Billboard Entries"
    
    def __str__(self):
        return f"{self.get_player_name()} - {self.get_action_type_display()} at {self.court_complex.name}"
    
    def get_player_name(self):
        """Get the actual player name from codename for display (privacy-safe)"""
        try:
            from friendly_games.models import PlayerCodename
            player_codename = PlayerCodename.objects.get(codename=self.codename)
            return player_codename.player.name
        except PlayerCodename.DoesNotExist:
            return f"Player ({self.codename})"  # Fallback if codename not found
    
    def is_expired(self):
        """Check if entry is older than 24 hours"""
        return timezone.now() - self.created_at > timedelta(hours=24)
    
    def can_respond(self, codename):
        """Check if a codename can respond to this entry"""
        if self.action_type == 'LOOKING_FOR_MATCH':
            # For match requests, only opponents can respond
            return self.opponent_team and codename.upper() in self.opponent_team.upper()
        return True
    
    def get_responses(self):
        """Get all responses for this entry"""
        return self.responses.filter(created_at__gte=timezone.now() - timedelta(hours=24))
    
    def get_response_count(self):
        """Get count of active responses"""
        return self.get_responses().count()
    
    @classmethod
    def get_daily_count(cls, codename, action_type):
        """Get count of entries for a codename and action type today"""
        today = timezone.now().date()
        return cls.objects.filter(
            codename=codename,
            action_type=action_type,
            created_at__date=today,
            is_active=True
        ).count()
    
    @classmethod
    def can_create_entry(cls, codename, action_type):
        """Check if user can create another entry of this type today"""
        return cls.get_daily_count(codename, action_type) < 2


class BillboardResponse(models.Model):
    RESPONSE_CHOICES = [
        ('JOINING', 'Joining'),
        ('ACCEPTING', 'Accepting'),
    ]
    
    entry = models.ForeignKey(BillboardEntry, on_delete=models.CASCADE, related_name='responses')
    codename = models.CharField(max_length=6, help_text="Responding player codename")
    response_type = models.CharField(max_length=10, choices=RESPONSE_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']
        unique_together = ['entry', 'codename']  # Prevent duplicate responses
        verbose_name = "Billboard Response"
        verbose_name_plural = "Billboard Responses"
    
    def __str__(self):
        return f"{self.get_player_name()} - {self.get_response_type_display()} to {self.entry}"
    
    def get_player_name(self):
        """Get the actual player name from codename for display (privacy-safe)"""
        try:
            from friendly_games.models import PlayerCodename
            player_codename = PlayerCodename.objects.get(codename=self.codename)
            return player_codename.player.name
        except PlayerCodename.DoesNotExist:
            return f"Player ({self.codename})"  # Fallback if codename not found
    
    def get_response_text(self):
        """Get display text for the response"""
        if self.entry.action_type == 'AT_COURTS':
            return "I'm there too!"
        elif self.entry.action_type == 'GOING_TO_COURTS':
            return "I'll come too!"
        elif self.entry.action_type == 'LOOKING_FOR_MATCH':
            return "We accept!"
        return "Joined"


class BillboardSettings(models.Model):
    """Global settings for the Billboard module"""
    max_entries_per_day = models.IntegerField(default=2, help_text="Maximum entries per action type per day")
    entry_expiry_hours = models.IntegerField(default=24, help_text="Hours after which entries expire")
    is_enabled = models.BooleanField(default=True, help_text="Enable/disable the Billboard module")
    
    class Meta:
        verbose_name = "Billboard Settings"
        verbose_name_plural = "Billboard Settings"
    
    def __str__(self):
        return "Billboard Settings"
    
    @classmethod
    def get_settings(cls):
        """Get or create settings instance"""
        settings, created = cls.objects.get_or_create(pk=1)
        return settings

