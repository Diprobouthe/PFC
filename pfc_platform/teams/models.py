from django.db import models
import random
import string
from django.conf import settings

def generate_pin():
    """Generate a random 6-digit PIN"""
    return ''.join(random.choices(string.digits, k=6))

class Team(models.Model):
    """Team model for storing team information"""
    name = models.CharField(max_length=100)
    pin = models.CharField(max_length=6, unique=True, default=generate_pin)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return self.name
    
    def get_pin(self, user=None):
        """
        Return the PIN only if the user is staff, otherwise return masked PIN
        This method should be used instead of directly accessing the pin field
        """
        if user and user.is_staff:
            return self.pin
        return "******"  # Masked PIN for non-staff users

class Player(models.Model):
    """Player model for storing player information"""
    name = models.CharField(max_length=100)
    team = models.ForeignKey(Team, related_name='players', on_delete=models.CASCADE)
    is_captain = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.name} ({self.team.name})"

class TeamAvailability(models.Model):
    """Model for tracking team availability for tournaments"""
    team = models.ForeignKey(Team, related_name='availabilities', on_delete=models.CASCADE)
    available_from = models.DateTimeField()
    available_to = models.DateTimeField()
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.team.name} - {self.available_from.date()} to {self.available_to.date()}"
