import random
import string
import logging
from django.db import models
from django.utils import timezone
from datetime import timedelta
from teams.models import Player
from courts.models import Court, CourtComplex

logger = logging.getLogger(__name__)


def generate_codename():
    """Generate a unique 6-character alphanumeric codename"""
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))


def generate_match_number():
    """Generate a unique 4-digit match number"""
    return ''.join(random.choices(string.digits, k=4))


class PlayerCodename(models.Model):
    """
    Separate table for player codenames - completely parallel to existing Player model.
    This ensures zero impact on existing tournament functionality.
    """
    player = models.OneToOneField(
        Player, 
        on_delete=models.CASCADE, 
        related_name='codename_profile'
    )
    codename = models.CharField(
        max_length=6, 
        unique=True, 
        default=generate_codename,
        help_text="Unique 6-character alphanumeric code for friendly game verification"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Player Codename"
        verbose_name_plural = "Player Codenames"
        
    def __str__(self):
        return f"{self.player.name} - {self.codename}"
    
    def save(self, *args, **kwargs):
        """Ensure codename is always unique"""
        if not self.codename:
            self.codename = generate_codename()
        
        # Ensure uniqueness
        while PlayerCodename.objects.filter(codename=self.codename).exclude(pk=self.pk).exists():
            self.codename = generate_codename()
            
        super().save(*args, **kwargs)




class FriendlyGame(models.Model):
    """
    Parallel friendly game system - completely separate from tournament matches.
    Enhanced with match numbers for joining and validation tracking.
    """
    GAME_STATUS_CHOICES = [
        ('DRAFT', 'Draft'),
        ('WAITING_FOR_PLAYERS', 'Waiting for Players'),
        ('READY', 'Ready to Play'),
        ('ACTIVE', 'In Progress'),
        ('PENDING_VALIDATION', 'Pending Validation'),
        ('COMPLETED', 'Completed'),
        ('CANCELLED', 'Cancelled'),
        ('EXPIRED', 'Expired'),
    ]
    
    VALIDATION_CHOICES = [
        ('NOT_VALIDATED', 'Not Validated'),
        ('PARTIALLY_VALIDATED', 'Partially Validated'), 
        ('FULLY_VALIDATED', 'Fully Validated'),
    ]
    
    name = models.CharField(max_length=100, help_text="Friendly game name/description")
    
    # Legacy PIN system (keeping for compatibility)
    game_pin = models.CharField(
        max_length=6, 
        unique=True, 
        null=True,
        blank=True,
        help_text="Legacy 6-digit PIN for this game"
    )
    
    # New match number system
    match_number = models.CharField(
        max_length=4, 
        unique=True,
        null=True,
        blank=True,
        help_text="4-digit match number for joining"
    )
    expires_at = models.DateTimeField(
        null=True, 
        blank=True,
        help_text="When this match number expires"
    )
    
    # Validation tracking
    validation_status = models.CharField(
        max_length=20, 
        choices=VALIDATION_CHOICES, 
        default='NOT_VALIDATED',
        help_text="Validation level based on codename usage"
    )
    
    status = models.CharField(
        max_length=20, 
        choices=GAME_STATUS_CHOICES, 
        default='WAITING_FOR_PLAYERS'
    )
    
    # Game details
    target_score = models.PositiveIntegerField(default=13, help_text="Points needed to win")
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    # Scores
    black_team_score = models.PositiveIntegerField(default=0)
    white_team_score = models.PositiveIntegerField(default=0)

    # Creator / host — the player who created this game.
    # Only the creator can start the game.
    # Nullable for backwards compatibility with games created before this field.
    creator_player = models.ForeignKey(
        'teams.Player',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_friendly_games',
        help_text='Player who created this game (only they can start it)',
    )

    # ── Court assignment ─────────────────────────────────────────────────────
    court_complex = models.ForeignKey(
        CourtComplex,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='friendly_games',
        help_text='Court complex where this game is played',
    )
    court = models.ForeignKey(
        Court,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='friendly_games',
        help_text='Specific court where this game is played',
    )

    # ── Timed game (optional) ─────────────────────────────────────────────────
    is_timed = models.BooleanField(
        default=False,
        help_text='Whether this game has a time limit',
    )
    time_limit_minutes = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text='Time limit in minutes (only used when is_timed=True)',
    )
    timer_started_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text='When the timer was started (game activated)',
    )
    timer_expired = models.BooleanField(
        default=False,
        help_text='Whether the time limit has been reached',
    )

    class Meta:
        verbose_name = "Friendly Game"
        verbose_name_plural = "Friendly Games"
        
    def __str__(self):
        if self.match_number:
            return f"{self.name} (Match #{self.match_number})"
        elif self.game_pin:
            return f"{self.name} (PIN: {self.game_pin})"
        else:
            return f"{self.name}"
    
    def save(self, *args, **kwargs):
        """Generate unique identifiers and set expiration"""
        # Generate match number for new games
        if not self.match_number and not self.game_pin:
            self.match_number = self.generate_match_number()
            # Set expiration to 24 hours from now
            self.expires_at = timezone.now() + timedelta(hours=24)
            self.status = 'WAITING_FOR_PLAYERS'
        
        # Legacy: Generate game PIN if needed (for compatibility)
        if not self.game_pin and not self.match_number:
            self.game_pin = self.generate_game_pin()
            
        super().save(*args, **kwargs)
    
    def generate_match_number(self):
        """Generate unique 4-digit match number"""
        while True:
            number = generate_match_number()
            if not FriendlyGame.objects.filter(match_number=number).exists():
                return number
    
    def generate_game_pin(self):
        """Generate unique 6-digit game PIN (legacy)"""
        while True:
            pin = ''.join(random.choices(string.digits, k=6))
            if not FriendlyGame.objects.filter(game_pin=pin).exists():
                return pin
    
    def is_expired(self):
        """Check if match number has expired"""
        if self.expires_at:
            return timezone.now() > self.expires_at
        return False

    def is_pre_start_expired(self):
        """
        Returns True if the game was created more than 10 minutes ago
        and has never been started (still WAITING_FOR_PLAYERS).
        Used to auto-expire stale unstarted games.
        """
        if self.status != 'WAITING_FOR_PLAYERS':
            return False
        age_seconds = (timezone.now() - self.created_at).total_seconds()
        return age_seconds > 600  # 10 minutes

    # ── Freshness scoring ────────────────────────────────────────────────────
    @property
    def age_minutes(self):
        """Minutes since creation."""
        return (timezone.now() - self.created_at).total_seconds() / 60

    @property
    def freshness_score(self):
        """
        0-100 score indicating how fresh this game is.
        Recently created games score highest; games older than 24h score 0.

        Thresholds:
            < 30 min  → 100
            < 1 h     → 90
            < 2 h     → 70
            < 6 h     → 50
            < 12 h    → 30
            < 24 h    → 10
            >= 24 h   → 0
        """
        age = self.age_minutes
        if age < 30:
            return 100
        elif age < 60:
            return 90
        elif age < 120:
            return 70
        elif age < 360:
            return 50
        elif age < 720:
            return 30
        elif age < 1440:
            return 10
        return 0

    @property
    def is_stale(self):
        """True when the game is older than 24 hours and should be expired."""
        return self.age_minutes >= 1440
    
    def update_validation_status(self):
        """Update validation status based on player codenames"""
        players = self.players.all()
        black_validated = players.filter(team='BLACK', codename_verified=True).exists()
        white_validated = players.filter(team='WHITE', codename_verified=True).exists()
        
        if black_validated and white_validated:
            self.validation_status = 'FULLY_VALIDATED'
        elif black_validated or white_validated:
            self.validation_status = 'PARTIALLY_VALIDATED'
        else:
            self.validation_status = 'NOT_VALIDATED'
        
        self.save()
    
    def can_start(self):
        """Check if game can be started - any players can participate"""
        # Must have at least 2 players (1 per team)
        if self.players.count() < 2:
            return False, "Game needs at least 2 players (1 per team)"
        
        # Must have players on both teams
        black_players = self.players.filter(team='BLACK').count()
        white_players = self.players.filter(team='WHITE').count()
        
        if black_players == 0:
            return False, "Black team needs at least 1 player"
        if white_players == 0:
            return False, "White team needs at least 1 player"
        
        # Game can start with any players - codename validation only required for result validation
        return True, "Game ready to start"
    
    def can_validate_result(self):
        """Check if result can be validated - requires at least one verified player per team"""
        # Check if at least one player on each team has a codename (current status, not stored field)
        from .models import PlayerCodename
        
        black_has_codename = False
        white_has_codename = False
        
        for game_player in self.players.all():
            try:
                # Check if player currently has a codename
                game_player.player.codename_profile.codename
                if game_player.team == 'BLACK':
                    black_has_codename = True
                elif game_player.team == 'WHITE':
                    white_has_codename = True
            except PlayerCodename.DoesNotExist:
                continue
        
        if not black_has_codename:
            return False, "Black team needs at least one player with verified codename to validate results"
        if not white_has_codename:
            return False, "White team needs at least one player with verified codename to validate results"
        
        return True, "Result can be validated"
    
    def is_fully_validated(self):
        """Check if both teams have at least one player with verified codename for result validation"""
        return self.validation_status == 'FULLY_VALIDATED'

    # ── Timer helpers (mirrors Match.time_remaining_seconds) ──────────────────
    @property
    def time_remaining_seconds(self):
        """Remaining seconds on the timer. None if untimed or not yet started."""
        if not self.is_timed or not self.time_limit_minutes or not self.timer_started_at:
            return None
        if self.status not in ('ACTIVE', 'PENDING_VALIDATION'):
            return None
        elapsed = timezone.now() - self.timer_started_at
        total = self.time_limit_minutes * 60
        remaining = total - elapsed.total_seconds()
        return int(max(0, remaining))

    @property
    def time_remaining_display(self):
        """MM:SS formatted time remaining."""
        remaining = self.time_remaining_seconds
        if remaining is None:
            return None
        return f"{int(remaining // 60):02d}:{int(remaining % 60):02d}"

    @property
    def timer_total_seconds(self):
        """Total timer duration in seconds. Returns None if not timed."""
        if not self.is_timed or not self.time_limit_minutes:
            return None
        return self.time_limit_minutes * 60

    @property
    def is_time_expired(self):
        """True when the timed game clock has run out."""
        remaining = self.time_remaining_seconds
        if remaining is None:
            return False
        return remaining == 0


class FriendlyGamePlayer(models.Model):
    """
    Player participation in friendly games with codename verification.
    Statistics only recorded when codename is verified.
    """
    TEAM_CHOICES = [
        ('BLACK', 'Black Team'),
        ('WHITE', 'White Team'),
    ]
    
    POSITION_CHOICES = [
        ('TIRER', 'Tirer'),
        ('POINTEUR', 'Pointeur'),
        ('MILIEU', 'Milieu'),
    ]
    
    game = models.ForeignKey(FriendlyGame, on_delete=models.CASCADE, related_name='players')
    player = models.ForeignKey(Player, on_delete=models.CASCADE)
    team = models.CharField(max_length=10, choices=TEAM_CHOICES)
    position = models.CharField(max_length=10, choices=POSITION_CHOICES)
    
    # Codename verification
    provided_codename = models.CharField(
        max_length=6, 
        blank=True, 
        help_text="Codename provided during game creation"
    )
    codename_verified = models.BooleanField(
        default=False,
        help_text="True if provided codename matches player's actual codename"
    )
    
    # Statistics (only recorded if codename_verified=True)
    points_scored = models.PositiveIntegerField(default=0)
    games_won = models.PositiveIntegerField(default=0)
    games_lost = models.PositiveIntegerField(default=0)
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = "Friendly Game Player"
        verbose_name_plural = "Friendly Game Players"
        unique_together = ['game', 'player']
        
    def __str__(self):
        verified_status = "✓" if self.codename_verified else "✗"
        return f"{self.player.name} ({self.team}) {verified_status}"
    
    def verify_codename(self):
        """Check if provided codename matches player's actual codename"""
        try:
            player_codename = self.player.codename_profile.codename
            self.codename_verified = (self.provided_codename == player_codename)
        except PlayerCodename.DoesNotExist:
            self.codename_verified = False
        self.save()
        return self.codename_verified


class FriendlyGameStatistics(models.Model):
    """
    Aggregated statistics for players across all friendly games.
    Only includes data from verified participations.
    """
    player = models.OneToOneField(
        Player, 
        on_delete=models.CASCADE, 
        related_name='friendly_stats'
    )
    
    # Overall statistics
    total_games = models.PositiveIntegerField(default=0)
    total_wins = models.PositiveIntegerField(default=0)
    total_losses = models.PositiveIntegerField(default=0)
    total_points = models.PositiveIntegerField(default=0)
    
    # Position-specific statistics
    pointer_games = models.PositiveIntegerField(default=0)
    milieu_games = models.PositiveIntegerField(default=0)
    tirer_games = models.PositiveIntegerField(default=0)
    flex_games = models.PositiveIntegerField(default=0)
    
    last_updated = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Friendly Game Statistics"
        verbose_name_plural = "Friendly Game Statistics"
        
    def __str__(self):
        return f"{self.player.name} - Friendly Stats"
    
    @property
    def win_rate(self):
        """Calculate win rate percentage"""
        if self.total_games == 0:
            return 0
        return round((self.total_wins / self.total_games) * 100, 1)
    
    def update_statistics(self):
        """Recalculate statistics from all verified game participations.

        codename_verified=True covers both:
        - Players who typed their own codename during game creation/join
        - Players added via QR scan (HMAC-verified identity, set at creation time)
        """
        verified_participations = FriendlyGamePlayer.objects.filter(
            player=self.player,
            codename_verified=True,  # True for both codename-typed AND QR-verified players
            game__status='COMPLETED'
        )
        
        self.total_games = verified_participations.count()
        self.total_wins = verified_participations.aggregate(
            total=models.Sum('games_won')
        )['total'] or 0
        self.total_losses = verified_participations.aggregate(
            total=models.Sum('games_lost')
        )['total'] or 0
        self.total_points = verified_participations.aggregate(
            total=models.Sum('points_scored')
        )['total'] or 0
        
        # Position-specific counts
        self.pointer_games = verified_participations.filter(position='POINTER').count()
        self.milieu_games = verified_participations.filter(position='MILIEU').count()
        self.tirer_games = verified_participations.filter(position='TIRER').count()
        self.flex_games = verified_participations.filter(position='FLEX').count()
        
        self.save()




class FriendlyGameResult(models.Model):
    """
    Model for storing friendly game results and validation - similar to tournament MatchResult.
    Enables two-step validation process: submit → validate → complete.
    """
    VALIDATION_ACTION_CHOICES = [
        ('agree', 'Agree with Result'),
        ('disagree', 'Disagree with Result'),
    ]
    
    game = models.OneToOneField(
        FriendlyGame, 
        related_name="result", 
        on_delete=models.CASCADE
    )
    
    # Team that submitted the result (BLACK or WHITE)
    submitted_by_team = models.CharField(
        max_length=10,
        choices=[('BLACK', 'Black Team'), ('WHITE', 'White Team')],
        help_text="Which team submitted the result"
    )
    
    # Team that validated the result (BLACK or WHITE)
    validated_by_team = models.CharField(
        max_length=10,
        choices=[('BLACK', 'Black Team'), ('WHITE', 'White Team')],
        null=True,
        blank=True,
        help_text="Which team validated the result"
    )
    
    # Validation action taken by the validating team
    validation_action = models.CharField(
        max_length=10,
        choices=VALIDATION_ACTION_CHOICES,
        null=True,
        blank=True,
        help_text="Action taken by validating team"
    )
    
    # Optional codenames for validation (for statistics)
    submitter_codename = models.CharField(
        max_length=6,
        blank=True,
        help_text="Codename of player who submitted result"
    )
    
    validator_codename = models.CharField(
        max_length=6,
        blank=True,
        help_text="Codename of player who validated result"
    )
    
    # Verification status for codenames
    submitter_verified = models.BooleanField(
        default=False,
        help_text="Whether submitter codename was verified"
    )
    
    validator_verified = models.BooleanField(
        default=False,
        help_text="Whether validator codename was verified"
    )
    
    # Additional validation fields
    notes = models.TextField(
        blank=True,
        help_text="Optional notes about the result"
    )
    
    # Timestamps
    submitted_at = models.DateTimeField(auto_now_add=True)
    validated_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        verbose_name = "Friendly Game Result"
        verbose_name_plural = "Friendly Game Results"
    
    def __str__(self):
        return f"Result for {self.game.name} (#{self.game.match_number})"
    
    def get_other_team(self):
        """Get the team that should validate this result"""
        if self.submitted_by_team == 'BLACK':
            return 'WHITE'
        else:
            return 'BLACK'
    
    def is_pending_validation(self):
        """Check if result is waiting for validation"""
        return self.validated_by_team is None
    
    def validate_result(self, validating_team, action, validator_codename=None):
        """
        Validate the result with the given action and optional codename.
        Final validation status depends on both teams' codename participation.
        """
        from django.utils import timezone
        from courts.timezone_utils import get_court_local_now
        
        # Use court-local time if the game has a court complex assigned
        _result_complex = self.game.court_complex if self.game else None
        _result_now = get_court_local_now(_result_complex) if _result_complex else timezone.now()
        
        self.validated_by_team = validating_team
        self.validation_action = action
        self.validated_at = _result_now
        
        if validator_codename:
            self.validator_codename = validator_codename
            # Verify the codename belongs to a player from the validating team
            try:
                # Find players from the validating team
                validating_players = self.game.players.filter(team=validating_team)
                for game_player in validating_players:
                    try:
                        player_codename = game_player.player.codename_profile
                        if player_codename.codename == validator_codename:
                            self.validator_verified = True
                            # Also mark the game player as verified
                            game_player.codename_verified = True
                            game_player.provided_codename = validator_codename
                            game_player.save()
                            break
                    except PlayerCodename.DoesNotExist:
                        continue
            except Exception:
                pass
        
        self.save()
        
        # Update game status based on validation action
        if action == 'agree':
            self.game.status = 'COMPLETED'
            self.game.completed_at = _result_now
            self.game.save()
            
            # Update game validation status based on THREE-TIER system
            self._update_three_tier_validation_status()
            
            # CRITICAL FIX: Update player win/loss statistics
            self._update_player_win_loss_statistics()
            
            # ===== RATING SYSTEM INTEGRATION =====
            # Update player ratings after successful friendly game completion
            # This is completely separate from game completion and won't affect it if it fails
            try:
                from matches.rating_integration import update_friendly_game_ratings
                rating_result = update_friendly_game_ratings(self.game)
                if rating_result["success"]:
                    logger.info(f"Friendly game {self.game.id} rating updates: {rating_result.get('reason', 'completed successfully')}")
                else:
                    logger.warning(f"Friendly game {self.game.id} rating updates failed: {rating_result.get('reason', 'unknown error')}")
            except Exception as e:
                logger.error(f"Rating system error for friendly game {self.game.id}: {e}")
                # Continue with normal game completion - rating failures don't break games
            # ===== END RATING SYSTEM INTEGRATION =====
            
        elif action == 'disagree':
            # Disagreement resets the game to ACTIVE and removes the result
            self.game.status = 'ACTIVE'
            self.game.save()
            # Delete this result so a new one can be submitted
            self.delete()
    
    def _update_three_tier_validation_status(self):
        """
        Update game validation status based on both teams' codename participation:
        - FULLY_VALIDATED: Both submitter AND validator provided valid codenames
        - PARTIALLY_VALIDATED: Only one team provided valid codename
        - NOT_VALIDATED: Neither team provided codenames
        """
        # Check if both submitter and validator provided valid codenames
        both_verified = self.submitter_verified and self.validator_verified
        
        # Check if at least one team provided a valid codename
        one_verified = self.submitter_verified or self.validator_verified
        
        if both_verified:
            self.game.validation_status = 'FULLY_VALIDATED'
        elif one_verified:
            self.game.validation_status = 'PARTIALLY_VALIDATED'
        else:
            self.game.validation_status = 'NOT_VALIDATED'
        
        self.game.save()
    
    def _update_player_win_loss_statistics(self):
        """
        Update player win/loss statistics based on the final game score.
        This is the CRITICAL FIX for the win/loss logic issue.
        """
        # Determine which team won based on scores
        black_score = self.game.black_team_score
        white_score = self.game.white_team_score
        
        if black_score > white_score:
            winning_team = 'BLACK'
            losing_team = 'WHITE'
        elif white_score > black_score:
            winning_team = 'WHITE'
            losing_team = 'BLACK'
        else:
            # Tie game - no wins or losses recorded
            return
        
        # Update winning team players
        winning_players = FriendlyGamePlayer.objects.filter(
            game=self.game,
            team=winning_team
        )
        for player in winning_players:
            player.games_won = 1
            player.games_lost = 0
            player.save()
        
        # Update losing team players
        losing_players = FriendlyGamePlayer.objects.filter(
            game=self.game,
            team=losing_team
        )
        for player in losing_players:
            player.games_won = 0
            player.games_lost = 1
            player.save()
        
        # Update aggregated statistics for all players in this game
        all_players = FriendlyGamePlayer.objects.filter(game=self.game)
        for game_player in all_players:
            try:
                stats, created = FriendlyGameStatistics.objects.get_or_create(
                    player=game_player.player
                )
                stats.update_statistics()
            except Exception:
                # Continue if there's an error with one player's stats
                continue

