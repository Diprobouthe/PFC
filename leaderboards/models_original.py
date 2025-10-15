from django.db import models
from teams.models import Team
from tournaments.models import Tournament
from matches.models import Match

class Leaderboard(models.Model):
    """Leaderboard model for storing tournament standings"""
    tournament = models.OneToOneField(Tournament, related_name='leaderboard', on_delete=models.CASCADE)
    last_updated = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"Leaderboard for {self.tournament.name}"

class LeaderboardEntry(models.Model):
    """Model for individual team entries in a leaderboard"""
    leaderboard = models.ForeignKey(Leaderboard, related_name='entries', on_delete=models.CASCADE)
    team = models.ForeignKey(Team, related_name='leaderboard_entries', on_delete=models.CASCADE)
    position = models.PositiveIntegerField()
    matches_played = models.PositiveIntegerField(default=0)
    matches_won = models.PositiveIntegerField(default=0)
    matches_lost = models.PositiveIntegerField(default=0)
    points_scored = models.PositiveIntegerField(default=0)
    points_conceded = models.PositiveIntegerField(default=0)
    
    class Meta:
        unique_together = ('leaderboard', 'team')
        ordering = ['position']
    
    def __str__(self):
        return f"{self.team.name} - Position {self.position}"
    
    @property
    def point_difference(self):
        return self.points_scored - self.points_conceded

class TeamStatistics(models.Model):
    """Model for storing comprehensive team statistics"""
    team = models.OneToOneField(Team, related_name='statistics', on_delete=models.CASCADE)
    total_matches_played = models.PositiveIntegerField(default=0)
    total_matches_won = models.PositiveIntegerField(default=0)
    total_matches_lost = models.PositiveIntegerField(default=0)
    total_points_scored = models.PositiveIntegerField(default=0)
    total_points_conceded = models.PositiveIntegerField(default=0)
    tournaments_participated = models.PositiveIntegerField(default=0)
    tournaments_won = models.PositiveIntegerField(default=0)
    last_updated = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"Statistics for {self.team.name}"
    
    @property
    def win_percentage(self):
        if self.total_matches_played == 0:
            return 0
        return (self.total_matches_won / self.total_matches_played) * 100

class MatchStatistics(models.Model):
    """Model for storing detailed match statistics"""
    match = models.OneToOneField(Match, related_name='statistics', on_delete=models.CASCADE)
    team1_points_by_round = models.JSONField(default=list)
    team2_points_by_round = models.JSONField(default=list)
    match_duration_minutes = models.PositiveIntegerField(null=True, blank=True)
    notes = models.TextField(blank=True, null=True)
    
    def __str__(self):
        return f"Statistics for {self.match}"
