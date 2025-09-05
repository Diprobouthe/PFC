from django.db import models
from teams.models import Team
from tournaments.models import Tournament

class TeamTournamentSignin(models.Model):
    """Model for tracking team sign-ins to tournaments"""
    team = models.ForeignKey(Team, related_name='tournament_signins', on_delete=models.CASCADE)
    tournament = models.ForeignKey(Tournament, related_name='team_signins', on_delete=models.CASCADE)
    signed_in_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)
    
    class Meta:
        unique_together = ('team', 'tournament')
        
    def __str__(self):
        return f"{self.team.name} - {self.tournament.name}"
