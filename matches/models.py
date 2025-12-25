from django.db import models
from django.utils import timezone
from courts.models import Court
from teams.models import Player

# Import the TeamMatchParticipant model
from .models_participant import TeamMatchParticipant

class Match(models.Model):
    """Match model for storing match information"""
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("pending_verification", "Pending Verification"),
        ("active", "Active"),
        ("waiting_validation", "Waiting Validation"),
        ("completed", "Completed"),
        ("cancelled", "Cancelled"),
    ]
    
    MATCH_TYPE_CHOICES = [
        ("doublet", "Doublet (2 players)"),
        ("triplet", "Triplet (3 players)"),
        ("tete_a_tete", "Tête-à-tête (1 player)"),
        ("mixed", "Mixed Format"),
        ("unknown", "Unknown Format"),
    ]
    
    tournament = models.ForeignKey("tournaments.Tournament", related_name="matches", on_delete=models.CASCADE)
    stage = models.ForeignKey("tournaments.Stage", related_name="matches", on_delete=models.CASCADE, null=True, blank=True)
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
    
    # New field to store match type for statistics
    match_type = models.CharField(max_length=20, choices=MATCH_TYPE_CHOICES, null=True, blank=True, help_text="Type of match based on player count")
    team1_player_count = models.PositiveSmallIntegerField(null=True, blank=True, help_text="Number of players from team 1")
    team2_player_count = models.PositiveSmallIntegerField(null=True, blank=True, help_text="Number of players from team 2")
    
    # Timer configuration (admin-configurable)
    time_limit_minutes = models.PositiveIntegerField(
        null=True, 
        blank=True,
        help_text="Time limit in minutes (optional). Timer starts when both teams activate the match."
    )
    timer_expired = models.BooleanField(
        default=False,
        help_text="Whether the time limit has been reached"
    )
    timer_expired_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the timer expired (if applicable)"
    )

    @property
    def is_draw(self):
        """Check if the match ended in a draw (tie)"""
        if self.team1_score is not None and self.team2_score is not None:
            return self.team1_score == self.team2_score
        return False
    
    @property
    def time_remaining_seconds(self):
        """Calculate remaining time in seconds. Returns None if no timer set."""
        if not self.time_limit_minutes or not self.start_time:
            return None
        
        if self.status not in ["active", "waiting_validation"]:
            return None
        
        # Calculate elapsed time
        elapsed = timezone.now() - self.start_time
        total_seconds = self.time_limit_minutes * 60
        remaining = total_seconds - elapsed.total_seconds()
        
        return int(max(0, remaining))  # Never negative, always integer
    
    @property
    def time_remaining_display(self):
        """Human-readable time remaining (MM:SS format)."""
        remaining = self.time_remaining_seconds
        if remaining is None:
            return None
        
        minutes = int(remaining // 60)
        seconds = int(remaining % 60)
        return f"{minutes:02d}:{seconds:02d}"
    
    @property
    def is_time_expired(self):
        """Check if timer has expired."""
        remaining = self.time_remaining_seconds
        if remaining is None:
            return False
        return remaining == 0

    def __str__(self):
        round_info = f"R{self.round.number}" if self.round else "" 
        stage_info = f"S{self.stage.stage_number}" if self.stage else ""
        return f"{self.team1.name} vs {self.team2.name} ({self.tournament.name} {stage_info} {round_info})"
    
    def complete_match(self, team1_score, team2_score):
        """Marks the match as completed and determines winner/loser."""
        # Always update scores and winner/loser, even if already completed
        self.team1_score = team1_score
        self.team2_score = team2_score
        
        # Only update status and timing if not already completed
        if self.status != "completed":
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
        
        # Release the court when match is completed
        if self.court:
            self.court.is_available = True
            self.court.save(update_fields=["is_available"])
            print(f"Released court {self.court.number} after match {self.id} completion")
            
        self.save()
        print(f"Match {self.id} completed. Winner: {self.winner}, Loser: {self.loser}")
        
        # Update mêlée player stats if this is a mêlée tournament
        self._update_melee_stats()
        
        # Trigger knockout tournament automation if applicable
        self._trigger_knockout_automation()
    
    def _update_melee_stats(self):
        """
        Update mêlée player stats after match completion.
        This method is designed to be non-breaking - if it fails, it won't affect match completion.
        """
        try:
            if self.tournament and self.tournament.is_melee:
                from tournaments.melee_stats_updater import update_melee_player_stats_from_match
                update_melee_player_stats_from_match(self)
                print(f"📊 Updated mêlée player stats for match {self.id}")
        except Exception as e:
            print(f"Warning: Mêlée stats update failed for match {self.id}: {e}")
    
    def _trigger_knockout_automation(self):
        """
        Safely trigger knockout tournament automation after match completion.
        This method is designed to be non-breaking - if it fails, it won't affect match completion.
        """
        try:
            # Only trigger for knockout tournaments
            if self.tournament.format == "knockout":
                print(f"Triggering knockout automation check for tournament {self.tournament.name}")
                advanced, matches_created, tournament_complete = self.tournament.check_and_advance_knockout_round()
                
                if tournament_complete:
                    print(f"🏆 Tournament {self.tournament.name} has been completed!")
                elif advanced:
                    print(f"✅ Advanced to next round with {matches_created} new matches")
                else:
                    print(f"ℹ️ Round not yet complete or no advancement needed")
        except Exception as e:
            # Log the error but don't let it break match completion
            print(f"Warning: Knockout automation failed for match {self.id}: {e}")
            # Could also log to a proper logging system here

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
    ROLE_CHOICES = [
        ("pointer", "Pointer"),
        ("milieu", "Milieu"),
        ("tirer", "Shooter"),
        ("flex", "Flex"),
    ]
    
    match = models.ForeignKey(Match, related_name="match_players", on_delete=models.CASCADE)
    player = models.ForeignKey(Player, related_name="match_participations", on_delete=models.CASCADE)
    team = models.ForeignKey("teams.Team", related_name="match_player_entries", on_delete=models.CASCADE)
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default="flex", help_text="Player's role in the match")
    
    # Store match type at player level for statistics
    match_format = models.CharField(max_length=20, null=True, blank=True, help_text="Format of match this player participated in")
    
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



# ===== LIVE SCOREBOARD SYSTEM =====
# This system provides real-time score tracking for matches without interfering
# with any existing functionality or core logic.

class LiveScoreboard(models.Model):
    """
    Live scoreboard for real-time score tracking during matches.
    Works for both tournament matches and friendly games.
    IMPORTANT: This is completely separate from official scoring and never affects match results.
    """
    # Match references - one will be set, the other will be null
    tournament_match = models.OneToOneField(
        Match, 
        on_delete=models.CASCADE, 
        null=True, 
        blank=True,
        related_name="live_scoreboard",
        help_text="Tournament match this scoreboard tracks"
    )
    friendly_game = models.OneToOneField(
        "friendly_games.FriendlyGame",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="live_scoreboard",
        help_text="Friendly game this scoreboard tracks"
    )
    
    # Live scores (unofficial)
    team1_score = models.PositiveIntegerField(default=0, help_text="Live score for team 1/black team")
    team2_score = models.PositiveIntegerField(default=0, help_text="Live score for team 2/white team")
    
    # Scorekeeper information
    current_scorekeeper_codename = models.CharField(
        max_length=50, 
        blank=True,
        help_text="Codename of current scorekeeper (for authentication)"
    )
    
    # Status and metadata
    is_active = models.BooleanField(
        default=True,
        help_text="Whether live scoring is currently active"
    )
    last_updated_by = models.CharField(
        max_length=50,
        blank=True,
        help_text="Codename of last person to update scores"
    )
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Live Scoreboard"
        verbose_name_plural = "Live Scoreboards"
    
    def __str__(self):
        if self.tournament_match:
            return f"Live Scoreboard: {self.tournament_match}"
        elif self.friendly_game:
            return f"Live Scoreboard: {self.friendly_game}"
        else:
            return f"Live Scoreboard #{self.id}"
    
    def get_match_name(self):
        """Get a display name for the match being tracked"""
        if self.tournament_match:
            return str(self.tournament_match)
        elif self.friendly_game:
            return str(self.friendly_game)
        else:
            return "Unknown Match"
    
    def get_team1_name(self):
        """Get team 1/black team name"""
        if self.tournament_match:
            return self.tournament_match.team1.name
        elif self.friendly_game:
            return "Black Team"
        else:
            return "Team 1"
    
    def get_team2_name(self):
        """Get team 2/white team name"""
        if self.tournament_match:
            return self.tournament_match.team2.name
        elif self.friendly_game:
            return "White Team"
        else:
            return "Team 2"
    
    def get_match_status(self):
        """Get the status of the underlying match"""
        if self.tournament_match:
            return self.tournament_match.status
        elif self.friendly_game:
            return self.friendly_game.status
        else:
            return "unknown"
    
    def is_match_active(self):
        """Check if the underlying match is in an active state"""
        if self.tournament_match:
            return self.tournament_match.status in ["active", "pending_verification"]
        elif self.friendly_game:
            return self.friendly_game.status in ["ACTIVE", "READY"]
        else:
            return False
    
    def get_last_updated_by_name(self):
        """Get the player name from the codename for display purposes"""
        if not self.last_updated_by:
            return None
        
        try:
            from friendly_games.models import PlayerCodename
            player_codename = PlayerCodename.objects.get(codename=self.last_updated_by)
            return player_codename.player.name
        except PlayerCodename.DoesNotExist:
            # If codename not found, return None to hide the update info
            return None
        except Exception:
            # For any other error, return None to hide the update info
            return None
    
    def update_scores(self, team1_score, team2_score, scorekeeper_codename):
        """
        Update live scores with validation.
        This method includes basic validation but never affects official results.
        """
        # Validate score ranges (0-13 for petanque)
        if not (0 <= team1_score <= 13 and 0 <= team2_score <= 13):
            raise ValueError("Scores must be between 0 and 13")
        
        # Update scores
        self.team1_score = team1_score
        self.team2_score = team2_score
        self.last_updated_by = scorekeeper_codename
        self.current_scorekeeper_codename = scorekeeper_codename
        
        # Auto-deactivate if match reaches 13 points
        if team1_score >= 13 or team2_score >= 13:
            self.is_active = False
        
        self.save()
    
    def get_team1_players(self):
        """Get players for team 1/black team"""
        if self.tournament_match:
            # For tournament matches, get players from MatchPlayer entries
            from matches.models import MatchPlayer
            match_players = MatchPlayer.objects.filter(
                match=self.tournament_match,
                team=self.tournament_match.team1
            ).select_related('player')
            return match_players
        elif self.friendly_game:
            # For friendly games, get black team players
            return self.friendly_game.players.filter(team='BLACK')
        return []
    
    def get_team2_players(self):
        """Get players for team 2/white team"""
        if self.tournament_match:
            # For tournament matches, get players from MatchPlayer entries
            from matches.models import MatchPlayer
            match_players = MatchPlayer.objects.filter(
                match=self.tournament_match,
                team=self.tournament_match.team2
            ).select_related('player')
            return match_players
        elif self.friendly_game:
            # For friendly games, get white team players
            return self.friendly_game.players.filter(team='WHITE')
        return []

    def reset_scores(self, scorekeeper_codename):
        """Reset scores to 0-0"""
        self.team1_score = 0
        self.team2_score = 0
        self.last_updated_by = scorekeeper_codename
        self.is_active = True
        self.save()


class ScoreUpdate(models.Model):
    """
    Log of all score updates for audit trail and potential scorekeeper rating.
    This provides a complete history of live score changes.
    """
    scoreboard = models.ForeignKey(
        LiveScoreboard, 
        on_delete=models.CASCADE, 
        related_name='score_updates',
        help_text="Scoreboard this update belongs to"
    )
    
    # Score values at time of update
    team1_score = models.PositiveIntegerField(help_text="Team 1 score at time of update")
    team2_score = models.PositiveIntegerField(help_text="Team 2 score at time of update")
    
    # Update metadata
    scorekeeper_codename = models.CharField(
        max_length=50,
        help_text="Codename of person who made this update"
    )
    update_type = models.CharField(
        max_length=20,
        choices=[
            ('increment', 'Score Increment'),
            ('correction', 'Score Correction'),
            ('reset', 'Score Reset'),
        ],
        default='increment',
        help_text="Type of score update"
    )
    
    # Timestamp
    timestamp = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = "Score Update"
        verbose_name_plural = "Score Updates"
        ordering = ['-timestamp']
    
    def __str__(self):
        return f"{self.team1_score}-{self.team2_score} by {self.scorekeeper_codename} at {self.timestamp}"
    
    def get_scorekeeper_name(self):
        """Get the player name from the scorekeeper codename for display purposes"""
        if not self.scorekeeper_codename:
            return None
        
        try:
            from friendly_games.models import PlayerCodename
            player_codename = PlayerCodename.objects.get(codename=self.scorekeeper_codename)
            return player_codename.player.name
        except PlayerCodename.DoesNotExist:
            # If codename not found, return None to hide the update info
            return None
        except Exception:
            # For any other error, return None to hide the update info
            return None


class ScorekeeperRating(models.Model):
    """
    Optional rating system for scorekeepers based on accuracy.
    Players can rate the accuracy of live updates after matches end.
    """
    scoreboard = models.ForeignKey(
        LiveScoreboard,
        on_delete=models.CASCADE,
        related_name='scorekeeper_ratings',
        help_text="Scoreboard being rated"
    )
    
    # Rating details
    rater_codename = models.CharField(
        max_length=50,
        help_text="Codename of person giving the rating"
    )
    accuracy_rating = models.PositiveIntegerField(
        choices=[
            (1, 'Very Inaccurate'),
            (2, 'Inaccurate'),
            (3, 'Somewhat Accurate'),
            (4, 'Accurate'),
            (5, 'Very Accurate'),
        ],
        help_text="Rating of scorekeeper accuracy (1-5)"
    )
    
    # Optional feedback
    feedback = models.TextField(
        blank=True,
        help_text="Optional feedback about the live scoring"
    )
    
    # Timestamp
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = "Scorekeeper Rating"
        verbose_name_plural = "Scorekeeper Ratings"
        unique_together = ['scoreboard', 'rater_codename']  # One rating per person per scoreboard
    
    def __str__(self):
        return f"Rating {self.accuracy_rating}/5 for {self.scoreboard} by {self.rater_codename}"

