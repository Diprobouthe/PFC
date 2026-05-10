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
    """Model for individual team entries in a leaderboard with Swiss support"""
    leaderboard = models.ForeignKey(Leaderboard, related_name='entries', on_delete=models.CASCADE)
    team = models.ForeignKey(Team, related_name='leaderboard_entries', on_delete=models.CASCADE)
    position = models.PositiveIntegerField()
    matches_played = models.PositiveIntegerField(default=0)
    matches_won = models.PositiveIntegerField(default=0)
    matches_lost = models.PositiveIntegerField(default=0)
    points_scored = models.PositiveIntegerField(default=0)
    points_conceded = models.PositiveIntegerField(default=0)
    
    # Swiss-specific fields (populated for Swiss tournaments)
    swiss_points = models.IntegerField(default=0, help_text="Swiss tournament points (3 per win)")
    buchholz_score = models.FloatField(default=0.0, help_text="Buchholz tie-breaker score")

    # Multi-stage tracking fields
    stage_reached = models.PositiveIntegerField(
        default=1,
        help_text="Highest stage number this team reached in the tournament"
    )
    tournament_status = models.CharField(
        max_length=30,
        default='active',
        help_text="Team status: active, eliminated, champion, finalist, semi-finalist"
    )

    class Meta:
        unique_together = ('leaderboard', 'team')
        ordering = ['position']
    
    def __str__(self):
        return f"{self.team.name} - Position {self.position}"
    
    @property
    def point_difference(self):
        return self.points_scored - self.points_conceded
    
    @property
    def is_swiss_tournament(self):
        """Check if this entry is for a Swiss tournament"""
        from .swiss_ranking import is_swiss_tournament
        return is_swiss_tournament(self.leaderboard.tournament)

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
    
    # Swiss-specific statistics
    total_swiss_points = models.IntegerField(default=0, help_text="Total Swiss points across all tournaments")
    swiss_tournaments_played = models.PositiveIntegerField(default=0, help_text="Number of Swiss tournaments participated in")
    
    last_updated = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"Statistics for {self.team.name}"
    
    @property
    def win_percentage(self):
        if self.total_matches_played == 0:
            return 0
        return (self.total_matches_won / self.total_matches_played) * 100
    
    @property
    def average_swiss_points(self):
        """Average Swiss points per Swiss tournament"""
        if self.swiss_tournaments_played == 0:
            return 0
        return self.total_swiss_points / self.swiss_tournaments_played

class MatchStatistics(models.Model):
    """Model for storing detailed match statistics"""
    match = models.OneToOneField(Match, related_name='statistics', on_delete=models.CASCADE)
    team1_points_by_round = models.JSONField(default=list)
    team2_points_by_round = models.JSONField(default=list)
    match_duration_minutes = models.PositiveIntegerField(null=True, blank=True)
    notes = models.TextField(blank=True, null=True)
    
    def __str__(self):
        return f"Statistics for {self.match}"
