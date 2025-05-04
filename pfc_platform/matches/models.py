from django.db import models
from django.utils import timezone # Import timezone
from courts.models import Court
from teams.models import Player

class Match(models.Model):
    """Match model for storing match information"""
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("pending_verification", "Pending Verification"),
        ("active", "Active"),
        ("waiting_validation", "Waiting Validation"),
        ("completed", "Completed"),
        ("cancelled", "Cancelled"), # Add cancelled status
    ]
    
    tournament = models.ForeignKey("tournaments.Tournament", related_name="matches", on_delete=models.CASCADE)
    stage = models.ForeignKey("tournaments.Stage", related_name="matches", on_delete=models.CASCADE, null=True, blank=True) # Link to Stage
    round = models.ForeignKey("tournaments.Round", related_name="matches", on_delete=models.CASCADE, null=True, blank=True)
    bracket = models.ForeignKey("tournaments.Bracket", related_name="matches", on_delete=models.CASCADE, null=True, blank=True)
    team1 = models.ForeignKey("teams.Team", related_name="matches_as_team1", on_delete=models.CASCADE)
    team2 = models.ForeignKey("teams.Team", related_name="matches_as_team2", on_delete=models.CASCADE)
    team1_score = models.PositiveIntegerField(null=True, blank=True)
    team2_score = models.PositiveIntegerField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    court = models.ForeignKey(Court, related_name="matches", on_delete=models.SET_NULL, null=True, blank=True)
    proposed_court = models.ForeignKey(Court, related_name="proposed_matches", on_delete=models.SET_NULL, null=True, blank=True, help_text="Court proposed by the first activating team when no courts were free")
    scheduled_time = models.DateTimeField(null=True, blank=True)
    start_time = models.DateTimeField(null=True, blank=True)
    end_time = models.DateTimeField(null=True, blank=True)
    duration = models.DurationField(null=True, blank=True)
    waiting_for_court = models.BooleanField(default=False, help_text="Indicates if match is waiting for a court to become available")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # Add field to store winner/loser for progression
    winner = models.ForeignKey("teams.Team", related_name="won_matches", on_delete=models.SET_NULL, null=True, blank=True)
    loser = models.ForeignKey("teams.Team", related_name="lost_matches", on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self):
        round_info = f"R{self.round.number}" if self.round else "" 
        stage_info = f"S{self.stage.stage_number}" if self.stage else ""
        return f"{self.team1.name} vs {self.team2.name} ({self.tournament.name} {stage_info} {round_info})"
    
    # Refactor verify_team_pin to handle initiation/validation separately
    # This logic was moved to matches/views.py match_activate view
    # Keep a simplified version or remove if activation logic is fully in the view
    
    def complete_match(self, team1_score, team2_score):
        """Marks the match as completed and determines winner/loser."""
        if self.status == "completed":
            print(f"Match {self.id} is already completed.")
            return

        self.team1_score = team1_score
        self.team2_score = team2_score
        self.status = "completed"
        self.end_time = timezone.now()
        if self.start_time:
            self.duration = self.end_time - self.start_time
        
        if team1_score > team2_score:
            self.winner = self.team1
            self.loser = self.team2
        elif team2_score > team1_score:
            self.winner = self.team2
            self.loser = self.team1
        else:
            # Handle draws if applicable, otherwise mark as needing resolution
            self.winner = None
            self.loser = None
            print(f"Warning: Match {self.id} ended in a draw ({team1_score}-{team2_score}). Winner/Loser not set.")
            
        self.save()
        print(f"Match {self.id} completed. Winner: {self.winner}, Loser: {self.loser}")
        
        # Potentially trigger leaderboard update or stage advancement check here
        # self.tournament.check_stage_completion(self.stage)

class MatchActivation(models.Model):
    """Model for tracking match activation attempts by teams"""
    match = models.ForeignKey(Match, related_name="activations", on_delete=models.CASCADE)
    team = models.ForeignKey("teams.Team", related_name="match_activations", on_delete=models.CASCADE)
    activated_at = models.DateTimeField(auto_now_add=True)
    pin_used = models.CharField(max_length=6)
    is_initiator = models.BooleanField(default=False) # Track who initiated vs validated
    
    class Meta:
        unique_together = ("match", "team")
        ordering = ["activated_at"]
    
    def __str__(self):
        action = "initiated" if self.is_initiator else "validated"
        return f"{self.team.name} {action} match {self.match.id}"

class MatchPlayer(models.Model):
    """Model for tracking players participating in a match"""
    match = models.ForeignKey(Match, related_name="match_players", on_delete=models.CASCADE)
    player = models.ForeignKey(Player, related_name="match_participations", on_delete=models.CASCADE)
    team = models.ForeignKey("teams.Team", related_name="match_player_entries", on_delete=models.CASCADE)
    
    class Meta:
        unique_together = ("match", "player")
    
    def __str__(self):
        return f"{self.player.name} in {self.match}"

class MatchResult(models.Model):
    """Model for storing match results and validation"""
    match = models.OneToOneField(Match, related_name="result", on_delete=models.CASCADE)
    submitted_by = models.ForeignKey("teams.Team", related_name="submitted_results", on_delete=models.CASCADE)
    validated_by = models.ForeignKey("teams.Team", related_name="validated_results", on_delete=models.CASCADE, null=True, blank=True)
    photo_evidence = models.ImageField(upload_to="match_evidence/", null=True, blank=True)
    notes = models.TextField(blank=True, null=True)
    submitted_at = models.DateTimeField(auto_now_add=True)
    validated_at = models.DateTimeField(null=True, blank=True)
    
    def __str__(self):
        return f"Result for {self.match}"

class NextOpponentRequest(models.Model):
    """Model for tracking next opponent requests"""
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("accepted", "Accepted"),
        ("rejected", "Rejected"),
        ("expired", "Expired"),
    ]
    
    tournament = models.ForeignKey("tournaments.Tournament", related_name="opponent_requests", on_delete=models.CASCADE)
    requesting_team = models.ForeignKey("teams.Team", related_name="requested_opponents", on_delete=models.CASCADE)
    target_team = models.ForeignKey("teams.Team", related_name="received_requests", on_delete=models.CASCADE)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="pending")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.requesting_team.name} requested {self.target_team.name}"

