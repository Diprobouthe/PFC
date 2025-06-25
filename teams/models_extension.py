from django.db import models
from django.conf import settings
from .models import Player

class PlayerProfile(models.Model):
    """
    Extended profile information for players.
    This parallel model allows adding additional player information
    without modifying the core Player model.
    """
    player = models.OneToOneField(
        Player, 
        on_delete=models.CASCADE,
        related_name='profile'
    )
    
    # Contact information
    email = models.EmailField(blank=True, null=True)
    phone = models.CharField(max_length=20, blank=True, null=True)
    
    # Personal information
    date_of_birth = models.DateField(blank=True, null=True)
    bio = models.TextField(blank=True, null=True)
    
    # Player statistics
    skill_level = models.IntegerField(
        choices=[
            (1, 'Beginner'),
            (2, 'Intermediate'),
            (3, 'Advanced'),
            (4, 'Expert'),
            (5, 'Professional')
        ],
        default=1
    )
    matches_played = models.PositiveIntegerField(default=0)
    matches_won = models.PositiveIntegerField(default=0)
    
    # Preferences
    preferred_position = models.CharField(
        max_length=20,
        choices=[
            ('pointer', 'Pointer'),
            ('middle', 'Middle'),
            ('shooter', 'Shooter'),
            ('versatile', 'Versatile')
        ],
        blank=True,
        null=True
    )
    
    # Media
    profile_picture = models.ImageField(
        upload_to='player_profiles/',
        blank=True,
        null=True
    )
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"Profile for {self.player}"
    
    def win_rate(self):
        """Calculate and return the player's win rate as a percentage"""
        if self.matches_played == 0:
            return 0
        return round((self.matches_won / self.matches_played) * 100, 1)
    
    def update_match_stats(self, won=False):
        """Update player match statistics"""
        self.matches_played += 1
        if won:
            self.matches_won += 1
        self.save()
