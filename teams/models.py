from django.db import models
import random
import string
from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import transaction
from django.utils import timezone
from datetime import datetime
import json
from django.core.exceptions import ValidationError
from .image_utils import (
    optimize_profile_picture, 
    optimize_team_logo, 
    optimize_team_photo,
    validate_image_size
)

def generate_pin():
    """Generate a random 6-digit PIN"""
    return ''.join(random.choices(string.digits, k=6))

class Team(models.Model):
    """Team model for storing team information"""
    name = models.CharField(max_length=100)
    pin = models.CharField(max_length=6, unique=True, default=generate_pin)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # Subteam functionality - all optional to maintain backward compatibility
    parent_team = models.ForeignKey(
        'self', 
        null=True, 
        blank=True, 
        on_delete=models.CASCADE,
        related_name='subteams',
        help_text="Parent team if this is a subteam"
    )
    is_subteam = models.BooleanField(
        default=False,
        help_text="True if this team is a subteam of another team"
    )
    subteam_type = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        choices=[
            ('triplet', 'Triplet'),
            ('doublette', 'Doublette'),
            ('tete_a_tete', 'Tête-à-tête'),
        ],
        help_text="Type of subteam (triplet, doublette, etc.)"
    )
    
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
    
    def is_parent_team(self):
        """Check if this team has subteams"""
        return self.subteams.exists()
    
    def get_all_players(self):
        """Get all players including from subteams if this is a parent team"""
        if self.is_parent_team():
            # Return players from all subteams
            all_players = []
            for subteam in self.subteams.all():
                all_players.extend(subteam.players.all())
            return all_players
        else:
            # Return own players
            return list(self.players.all())
    
    def get_available_players_for_subteam(self):
        """Get players available for subteam assignment (from parent team)"""
        if self.parent_team:
            return self.parent_team.players.all()
        else:
            return self.players.all()
    
    def can_create_subteams(self, subteam_specs):
        """Check if team has enough players to create requested subteams"""
        total_players_needed = 0
        for spec in subteam_specs:
            if spec['type'] == 'triplet':
                total_players_needed += 3
            elif spec['type'] == 'doublette':
                total_players_needed += 2
            elif spec['type'] == 'tete_a_tete':
                total_players_needed += 1
        
        available_players = self.players.count()
        return available_players >= total_players_needed

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
    
    # Dynamic Rating System
    value = models.FloatField(
        default=100.0,
        validators=[MinValueValidator(0.0)],
        help_text="Dynamic rating value (starts at 100.0)"
    )
    rating_history = models.JSONField(
        default=list,
        blank=True,
        help_text="History of rating changes with timestamps and match details"
    )
    
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
    
    def clean(self):
        """Validate image uploads"""
        if self.profile_picture:
            if not validate_image_size(self.profile_picture, max_size_mb=3):
                raise ValidationError("Profile picture must be smaller than 3MB")
    
    def save(self, *args, **kwargs):
        """Override save to optimize images"""
        # Only optimize new uploads, not existing records
        if self.profile_picture and hasattr(self.profile_picture, 'file') and not self.pk:
            try:
                # Optimize the image
                optimized_image = optimize_profile_picture(self.profile_picture)
                # Ensure the filename doesn't have nested paths
                if optimized_image.name:
                    # Extract just the filename without any path components
                    import os
                    filename = os.path.basename(optimized_image.name)
                    optimized_image.name = filename
                self.profile_picture = optimized_image
            except Exception as e:
                # If optimization fails, keep original image
                print(f"Image optimization failed: {e}")
        super().save(*args, **kwargs)
    
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
    
    # Enhanced statistics methods for position and match format analysis
    def get_position_stats(self):
        """Return statistics grouped by playing position from MatchPlayer data"""
        try:
            from matches.models import MatchPlayer, Match
            
            # Get all MatchPlayer records for this player
            match_players = MatchPlayer.objects.filter(
                player=self.player
            ).select_related('match')
            
            position_stats = {}
            
            for mp in match_players:
                role = mp.role or 'flex'
                if role not in position_stats:
                    position_stats[role] = {
                        'matches_played': 0,
                        'matches_won': 0,
                        'win_rate': 0
                    }
                
                position_stats[role]['matches_played'] += 1
                
                # Check if this match was won
                if mp.match.status == 'completed' and mp.match.winner == self.player.team:
                    position_stats[role]['matches_won'] += 1
            
            # Calculate win rates
            for role in position_stats:
                stats = position_stats[role]
                if stats['matches_played'] > 0:
                    stats['win_rate'] = round((stats['matches_won'] / stats['matches_played']) * 100, 1)
            
            return position_stats
        except Exception:
            return {}
    
    def get_match_format_stats(self):
        """Return statistics grouped by match format from MatchPlayer data"""
        try:
            from matches.models import MatchPlayer, Match
            
            # Get all MatchPlayer records for this player
            match_players = MatchPlayer.objects.filter(
                player=self.player
            ).select_related('match')
            
            format_stats = {}
            
            for mp in match_players:
                match_format = mp.match_format or mp.match.match_type or 'unknown'
                if match_format not in format_stats:
                    format_stats[match_format] = {
                        'matches_played': 0,
                        'matches_won': 0,
                        'win_rate': 0
                    }
                
                format_stats[match_format]['matches_played'] += 1
                
                # Check if this match was won
                if mp.match.status == 'completed' and mp.match.winner == self.player.team:
                    format_stats[match_format]['matches_won'] += 1
            
            # Calculate win rates
            for format_type in format_stats:
                stats = format_stats[format_type]
                if stats['matches_played'] > 0:
                    stats['win_rate'] = round((stats['matches_won'] / stats['matches_played']) * 100, 1)
            
            return format_stats
        except Exception:
            return {}
    
    def get_role_distribution(self):
        """Return distribution of roles played"""
        try:
            from matches.models import MatchPlayer
            
            match_players = MatchPlayer.objects.filter(player=self.player)
            total_matches = match_players.count()
            
            if total_matches == 0:
                return {}
            
            role_counts = {}
            for mp in match_players:
                role = mp.role or 'flex'
                role_counts[role] = role_counts.get(role, 0) + 1
            
            # Convert to percentages
            role_distribution = {}
            for role, count in role_counts.items():
                role_distribution[role] = {
                    'count': count,
                    'percentage': round((count / total_matches) * 100, 1)
                }
            
            return role_distribution
        except Exception:
            return {}
    
    def has_enhanced_stats(self):
        """Check if player has MatchPlayer data for enhanced statistics"""
        try:
            from matches.models import MatchPlayer
            return MatchPlayer.objects.filter(player=self.player).exists()
        except Exception:
            return False
    
    def sync_statistics_from_matches(self):
        """
        Safely sync PlayerProfile statistics with actual match data.
        This method recalculates matches_played and matches_won from the Match model.
        """
        try:
            from matches.models import Match
            from django.db import transaction
            
            # Get all completed matches where this player's team participated
            completed_matches = Match.objects.filter(
                models.Q(team1=self.player.team) | models.Q(team2=self.player.team),
                status='completed'
            )
            
            matches_played = completed_matches.count()
            matches_won = completed_matches.filter(winner=self.player.team).count()
            
            # Update statistics safely with transaction
            with transaction.atomic():
                self.matches_played = matches_played
                self.matches_won = matches_won
                self.save(update_fields=['matches_played', 'matches_won'])
                
            return True
        except Exception as e:
            # Log error but don't break anything
            print(f"Error syncing statistics for {self.player}: {e}")
            return False
    
    def get_accurate_statistics(self):
        """
        Get accurate statistics by checking if sync is needed and returning current stats.
        This method ensures statistics are up-to-date without breaking existing functionality.
        """
        try:
            from matches.models import Match
            
            # Check if statistics need updating by comparing with actual match count
            actual_matches = Match.objects.filter(
                models.Q(team1=self.player.team) | models.Q(team2=self.player.team),
                status='completed'
            ).count()
            
            # If there's a discrepancy, sync statistics
            if actual_matches != self.matches_played:
                self.sync_statistics_from_matches()
            
            return {
                'matches_played': self.matches_played,
                'matches_won': self.matches_won,
                'win_rate': self.win_rate()
            }
        except Exception:
            # Fallback to current stored values if anything goes wrong
            return {
                'matches_played': self.matches_played,
                'matches_won': self.matches_won,
                'win_rate': self.win_rate()
            }

    
    # ===== DYNAMIC RATING SYSTEM METHODS =====
    # These methods are completely separate from existing functionality
    # and will not interfere with match completion workflows
    
    @property
    def level(self):
        """Return player level based on rating value"""
        if self.value <= 110:
            return 'novice'
        elif self.value <= 150:
            return 'intermediate'  
        elif self.value <= 200:
            return 'advanced'
        else:
            return 'pro'
    
    def get_level_display(self):
        """Return formatted level display with color coding"""
        level_map = {
            'novice': ('Novice', 'secondary'),
            'intermediate': ('Intermediate', 'info'),
            'advanced': ('Advanced', 'primary'), 
            'pro': ('Professional', 'success')
        }
        return level_map.get(self.level, ('Unknown', 'light'))
    
    def calculate_rating_change(self, opponent_value, own_score, opponent_score):
        """
        Calculate rating change based on match result.
        Uses a modified Elo-style system adapted for petanque scoring.
        
        Args:
            opponent_value (float): Opponent's rating value
            own_score (int): This player's team score
            opponent_score (int): Opponent team score
            
        Returns:
            float: Rating change (positive for improvement, negative for decline)
        """
        try:
            # Base calculation factors
            score_difference = own_score - opponent_score
            rating_ratio = opponent_value / max(self.value, 1.0)  # Avoid division by zero
            
            # Determine if this was a win, loss, or draw
            if score_difference > 0:  # Win
                # Winning against higher-rated opponent gives more points
                base_change = abs(score_difference) * rating_ratio * 0.5
                rating_change = min(base_change, 20.0)  # Cap maximum gain
            elif score_difference < 0:  # Loss
                # Losing to lower-rated opponent loses more points
                base_change = abs(score_difference) * (self.value / max(opponent_value, 1.0)) * 0.5
                rating_change = -min(base_change, 15.0)  # Cap maximum loss
            else:  # Draw (rare in petanque, but handle it)
                # Small adjustment based on rating difference
                rating_change = (opponent_value - self.value) * 0.1
                rating_change = max(-2.0, min(2.0, rating_change))  # Small adjustment
            
            return round(rating_change, 2)
            
        except Exception as e:
            # If calculation fails, return 0 (no rating change)
            print(f"Rating calculation error for {self.player}: {e}")
            return 0.0
    
    def update_rating(self, opponent_value, own_score, opponent_score, match_id=None, match_type='tournament'):
        """
        Update player rating based on match result.
        This method is completely separate from match completion and will not break existing workflows.
        
        Args:
            opponent_value (float): Opponent's rating value
            own_score (int): This player's team score  
            opponent_score (int): Opponent team score
            match_id (int, optional): Match ID for history tracking
            match_type (str): 'tournament' or 'friendly'
            
        Returns:
            bool: True if update successful, False otherwise
        """
        try:
            with transaction.atomic():
                # Calculate rating change
                rating_change = self.calculate_rating_change(opponent_value, own_score, opponent_score)
                
                # Store old value for history
                old_value = self.value
                
                # Apply rating change
                self.value = max(0.0, self.value + rating_change)
                
                # Add to rating history
                history_entry = {
                    'timestamp': timezone.now().isoformat(),
                    'old_value': old_value,
                    'new_value': self.value,
                    'change': rating_change,
                    'opponent_value': opponent_value,
                    'own_score': own_score,
                    'opponent_score': opponent_score,
                    'match_type': match_type
                }
                
                if match_id:
                    history_entry['match_id'] = match_id
                
                # Ensure rating_history is a list
                if not isinstance(self.rating_history, list):
                    self.rating_history = []
                
                self.rating_history.append(history_entry)
                
                # Keep only last 50 entries to prevent excessive data growth
                if len(self.rating_history) > 50:
                    self.rating_history = self.rating_history[-50:]
                
                # Save changes
                self.save()
                
                return True
                
        except Exception as e:
            # If rating update fails, log error but don't break anything
            print(f"Rating update failed for {self.player}: {e}")
            return False
    
    def get_rating_trend(self, last_n_matches=10):
        """
        Get rating trend for the last N matches.
        
        Args:
            last_n_matches (int): Number of recent matches to analyze
            
        Returns:
            dict: Trend information with direction and change
        """
        try:
            if not self.rating_history or len(self.rating_history) < 2:
                return {'trend': 'stable', 'change': 0.0, 'matches': 0}
            
            # Get last N entries
            recent_history = self.rating_history[-last_n_matches:]
            
            if len(recent_history) < 2:
                return {'trend': 'stable', 'change': 0.0, 'matches': len(recent_history)}
            
            # Calculate total change over period
            start_value = recent_history[0]['old_value']
            end_value = recent_history[-1]['new_value']
            total_change = end_value - start_value
            
            # Determine trend direction
            if total_change > 2.0:
                trend = 'rising'
            elif total_change < -2.0:
                trend = 'falling'
            else:
                trend = 'stable'
            
            return {
                'trend': trend,
                'change': round(total_change, 2),
                'matches': len(recent_history)
            }
            
        except Exception as e:
            print(f"Rating trend calculation error for {self.player}: {e}")
            return {'trend': 'stable', 'change': 0.0, 'matches': 0}



class TeamProfile(models.Model):
    """
    Extended profile information for teams.
    This parallel model allows adding team enhancements (pictures, badges, dynamic values)
    without modifying the core Team model, ensuring compatibility with the upcoming
    Team Management Interface.
    """
    team = models.OneToOneField(
        Team, 
        on_delete=models.CASCADE,
        related_name='profile'
    )
    
    # ===== PICTURES =====
    logo_svg = models.FileField(
        upload_to='team_logos/', 
        blank=True, 
        null=True,
        help_text="Team logo in SVG format (vector graphics, scalable)"
    )
    team_photo_jpg = models.ImageField(
        upload_to='team_photos/', 
        blank=True, 
        null=True,
        help_text="Team photo in JPG format (group photo, team picture)"
    )
    
    # ===== DYNAMIC VALUES =====
    team_value = models.FloatField(
        default=100.0,
        validators=[MinValueValidator(0.0)],
        help_text="Dynamic team rating value (starts at 100.0, like player ratings)"
    )
    value_history = models.JSONField(
        default=list,
        blank=True,
        help_text="History of team value changes with timestamps and match details"
    )
    
    # ===== BADGES & ACHIEVEMENTS =====
    badges = models.JSONField(
        default=list,
        blank=True,
        help_text="List of earned badges (tournament wins, achievements, milestones)"
    )
    achievements = models.JSONField(
        default=dict,
        blank=True,
        help_text="Achievement data and progress tracking"
    )
    
    # ===== TEAM MANAGEMENT COMPATIBILITY =====
    is_friendly_team = models.BooleanField(
        default=False,
        help_text="True if this is the special 'Friendly Team' for unassigned players"
    )
    profile_type = models.CharField(
        max_length=20,
        choices=[
            ('full', 'Full Profile'),
            ('sub_team', 'Sub-team Profile'),
            ('friendly', 'Friendly Team Profile'),
            ('minimal', 'Minimal Profile')
        ],
        default='full',
        help_text="Type of profile for different team categories"
    )
    
    # ===== STATISTICS =====
    matches_played = models.PositiveIntegerField(default=0)
    matches_won = models.PositiveIntegerField(default=0)
    tournaments_participated = models.PositiveIntegerField(default=0)
    tournaments_won = models.PositiveIntegerField(default=0)
    
    # ===== METADATA =====
    description = models.TextField(
        blank=True, 
        null=True,
        help_text="Team description, motto, or about information"
    )
    founded_date = models.DateField(
        blank=True, 
        null=True,
        help_text="Date when the team was founded"
    )
    motto = models.CharField(
        max_length=200, 
        blank=True, 
        null=True,
        help_text="Team motto or slogan"
    )
    
    # ===== TIMESTAMPS =====
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Team Profile"
        verbose_name_plural = "Team Profiles"
    
    def __str__(self):
        return f"Profile for {self.team.name}"
    
    # ===== STATISTICS METHODS =====
    def win_rate(self):
        """Calculate and return the team's win rate as a percentage"""
        if self.matches_played == 0:
            return 0
        return round((self.matches_won / self.matches_played) * 100, 1)
    
    def update_match_stats(self, won=False):
        """Update team match statistics (safe for player transfers)"""
        self.matches_played += 1
        if won:
            self.matches_won += 1
        self.save()
    
    def sync_statistics_from_matches(self):
        """
        Safely sync TeamProfile statistics with actual match data.
        This method recalculates matches_played and matches_won from the Match model.
        """
        try:
            from matches.models import Match
            from django.db import transaction
            
            # Get all completed matches where this team participated
            completed_matches = Match.objects.filter(
                models.Q(team1=self.team) | models.Q(team2=self.team),
                status='completed'
            )
            
            matches_played = completed_matches.count()
            matches_won = completed_matches.filter(winner=self.team).count()
            
            # Update statistics safely with transaction
            with transaction.atomic():
                self.matches_played = matches_played
                self.matches_won = matches_won
                self.save(update_fields=['matches_played', 'matches_won'])
                
            return True
        except Exception as e:
            # Log error but don't break anything
            print(f"Error syncing statistics for team {self.team.name}: {e}")
            return False
    
    def get_accurate_statistics(self):
        """
        Get accurate statistics by checking if sync is needed and returning current stats.
        This method ensures statistics are up-to-date without breaking existing functionality.
        """
        try:
            from matches.models import Match
            
            # Check if statistics need updating by comparing with actual match count
            actual_matches = Match.objects.filter(
                models.Q(team1=self.team) | models.Q(team2=self.team),
                status='completed'
            ).count()
            
            # If there's a discrepancy, sync statistics
            if actual_matches != self.matches_played:
                self.sync_statistics_from_matches()
            
            return {
                'matches_played': self.matches_played,
                'matches_won': self.matches_won,
                'win_rate': self.win_rate()
            }
        except Exception:
            # Fallback to current stored values if anything goes wrong
            return {
                'matches_played': self.matches_played,
                'matches_won': self.matches_won,
                'win_rate': self.win_rate()
            }
    
    # ===== DYNAMIC RATING SYSTEM =====
    @property
    def level(self):
        """Return team level based on rating value"""
        if self.team_value <= 110:
            return 'developing'
        elif self.team_value <= 150:
            return 'competitive'  
        elif self.team_value <= 200:
            return 'elite'
        else:
            return 'champion'
    
    def get_level_display(self):
        """Return formatted level display with color coding"""
        level_map = {
            'developing': ('Developing', 'secondary'),
            'competitive': ('Competitive', 'info'),
            'elite': ('Elite', 'primary'), 
            'champion': ('Champion', 'success')
        }
        return level_map.get(self.level, ('Unknown', 'light'))
    
    # ===== TEAM MANAGEMENT INTERFACE COMPATIBILITY =====
    def get_effective_logo(self):
        """Get logo, with inheritance from parent team for sub-teams"""
        if self.logo_svg:
            return self.logo_svg.url
        
        # For sub-teams, try to inherit parent team logo
        if self.team.is_subteam and self.team.parent_team:
            parent_profile = getattr(self.team.parent_team, 'profile', None)
            if parent_profile and parent_profile.logo_svg:
                return parent_profile.logo_svg.url
        
        return None
    
    def get_effective_photo(self):
        """Get team photo, with fallback logic for sub-teams"""
        if self.team_photo_jpg:
            return self.team_photo_jpg.url
        
        # Sub-teams use their own photos, no inheritance for group photos
        return None
    
    def is_management_visible(self):
        """Check if this team should be visible in management interface"""
        # Hide friendly team from normal management UI
        if self.is_friendly_team:
            return False
        return True
    
    def can_have_players_transferred(self):
        """Check if players can be transferred to/from this team"""
        # Friendly team is always available for transfers
        if self.is_friendly_team:
            return True
        
        # Regular teams can participate in transfers
        if self.profile_type in ['full', 'sub_team']:
            return True
        
        return False
    
    def calculate_team_value_from_players(self):
        """
        Calculate team value based on current player roster.
        This method is transfer-safe and updates when players move.
        """
        try:
            total_player_value = 0
            player_count = 0
            
            # Get all players currently in this team
            for player in self.team.players.all():
                player_profile = getattr(player, 'profile', None)
                if player_profile:
                    total_player_value += player_profile.value
                    player_count += 1
                else:
                    # Default value for players without profiles
                    total_player_value += 100.0
                    player_count += 1
            
            if player_count == 0:
                return 100.0  # Default team value
            
            # Team value is average of player values with team bonus
            average_player_value = total_player_value / player_count
            team_bonus = min(player_count * 5, 50)  # Bonus for team size, capped at 50
            
            return round(average_player_value + team_bonus, 2)
            
        except Exception as e:
            print(f"Error calculating team value for {self.team.name}: {e}")
            return self.team_value  # Return current value if calculation fails
    
    def update_team_value(self, save=True):
        """
        Update team value based on current roster.
        Called when players are transferred to/from team.
        """
        try:
            new_value = self.calculate_team_value_from_players()
            old_value = self.team_value
            
            if abs(new_value - old_value) > 0.1:  # Only update if significant change
                # Record the change in history
                change_record = {
                    'timestamp': timezone.now().isoformat(),
                    'old_value': old_value,
                    'new_value': new_value,
                    'reason': 'roster_change',
                    'change': round(new_value - old_value, 2)
                }
                
                # Add to history (keep last 50 entries)
                if not self.value_history:
                    self.value_history = []
                self.value_history.append(change_record)
                if len(self.value_history) > 50:
                    self.value_history = self.value_history[-50:]
                
                self.team_value = new_value
                
                if save:
                    self.save()
                
                return True
            
            return False
            
        except Exception as e:
            print(f"Error updating team value for {self.team.name}: {e}")
            return False
    
    # ===== BADGE SYSTEM =====
    def add_badge(self, badge_name, badge_data=None):
        """Add a badge to the team"""
        if not self.badges:
            self.badges = []
        
        badge_entry = {
            'name': badge_name,
            'earned_at': timezone.now().isoformat(),
            'data': badge_data or {}
        }
        
        # Avoid duplicate badges
        existing_badges = [b['name'] for b in self.badges]
        if badge_name not in existing_badges:
            self.badges.append(badge_entry)
            self.save()
            return True
        
        return False
    
    def get_badge_display(self):
        """Get formatted badge display for templates"""
        if not self.badges:
            return []
        
        badge_display = []
        for badge in self.badges:
            # Get tournament name from badge data
            tournament_name = badge.get('data', {}).get('tournament_name', 'Unknown Tournament')
            position = badge.get('data', {}).get('position', '')
            
            # Create display name with tournament info
            badge_type = badge['name']
            if badge_type == 'tournament_1st_place':
                display_name = f"🥇 1st Place - {tournament_name}"
            elif badge_type == 'tournament_2nd_place':
                display_name = f"🥈 2nd Place - {tournament_name}"
            elif badge_type == 'tournament_3rd_place':
                display_name = f"🥉 3rd Place - {tournament_name}"
            elif badge_type == 'tournament_last_place':
                display_name = f"🎯 Participant - {tournament_name}"
            else:
                display_name = f"{badge_type.replace('_', ' ').title()} - {tournament_name}"
            
            badge_display.append({
                'name': badge['name'],
                'display_name': display_name,
                'tournament_name': tournament_name,
                'position': position,
                'earned_at': badge.get('earned_at', ''),
                'data': badge.get('data', {})
            })
        
        return badge_display
    
    # ===== FRIENDLY TEAM SPECIAL METHODS =====
    @classmethod
    def get_or_create_friendly_team_profile(cls):
        """Get or create the profile for the Friendly Team"""
        try:
            # Find or create the Friendly Team
            friendly_team, created = Team.objects.get_or_create(
                name="Friendly Team",
                defaults={
                    'pin': '000000'  # Special PIN for system team
                }
            )
            
            # Get or create its profile
            profile, profile_created = cls.objects.get_or_create(
                team=friendly_team,
                defaults={
                    'is_friendly_team': True,
                    'profile_type': 'friendly',
                    'team_value': 100.0,
                    'description': 'System team for unassigned players'
                }
            )
            
            return profile
            
        except Exception as e:
            print(f"Error creating Friendly Team profile: {e}")
            return None
    
    def sync_with_team_management(self):
        """
        Sync profile data with team management changes.
        Called when team structure changes (players added/removed, sub-teams created).
        """
        try:
            # Update team value based on current roster
            self.update_team_value(save=False)
            
            # Update statistics if needed
            # (This would integrate with match results when available)
            
            # Save all changes
            self.save()
            
            return True
            
        except Exception as e:
            print(f"Error syncing profile for {self.team.name}: {e}")
            return False



class TeamProfile(models.Model):
    """
    Extended profile information for teams.
    This parallel model allows adding team enhancements (pictures, badges, dynamic values)
    without modifying the core Team model. Designed to work with existing team structure
    including the existing Friendly Team and upcoming Team Management Interface.
    """
    team = models.OneToOneField(
        Team, 
        on_delete=models.CASCADE,
        related_name='profile'
    )
    
    # ===== PICTURES =====
    logo_svg = models.FileField(
        upload_to='team_logos/', 
        blank=True, 
        null=True,
        help_text="Team logo in SVG format (vector graphics, scalable)"
    )
    team_photo_jpg = models.ImageField(
        upload_to='team_photos/', 
        blank=True, 
        null=True,
        help_text="Team photo in JPG format (group photo, team picture)"
    )
    
    # ===== DYNAMIC VALUES =====
    team_value = models.FloatField(
        default=100.0,
        validators=[MinValueValidator(0.0)],
        help_text="Dynamic team rating value (starts at 100.0, like player ratings)"
    )
    value_history = models.JSONField(
        default=list,
        blank=True,
        help_text="History of team value changes with timestamps and match details"
    )
    
    # ===== BADGES & ACHIEVEMENTS =====
    badges = models.JSONField(
        default=list,
        blank=True,
        help_text="List of earned badges (tournament wins, achievements, milestones)"
    )
    achievements = models.JSONField(
        default=dict,
        blank=True,
        help_text="Achievement data and progress tracking"
    )
    
    # ===== TEAM MANAGEMENT COMPATIBILITY =====
    # Note: is_friendly_team is for identification only, NOT for creating/modifying Friendly Team
    is_friendly_team = models.BooleanField(
        default=False,
        help_text="True if this profile belongs to the existing Friendly Team (read-only identification)"
    )
    profile_type = models.CharField(
        max_length=20,
        choices=[
            ('full', 'Full Profile'),
            ('sub_team', 'Sub-team Profile'),
            ('friendly', 'Friendly Team Profile'),
            ('minimal', 'Minimal Profile')
        ],
        default='full',
        help_text="Type of profile for different team categories"
    )
    
    # ===== STATISTICS =====
    matches_played = models.PositiveIntegerField(default=0)
    matches_won = models.PositiveIntegerField(default=0)
    tournaments_participated = models.PositiveIntegerField(default=0)
    tournaments_won = models.PositiveIntegerField(default=0)
    
    # ===== METADATA =====
    description = models.TextField(
        blank=True, 
        null=True,
        help_text="Team description, motto, or about information"
    )
    founded_date = models.DateField(
        blank=True, 
        null=True,
        help_text="Date when the team was founded"
    )
    motto = models.CharField(
        max_length=200, 
        blank=True, 
        null=True,
        help_text="Team motto or slogan"
    )
    
    # ===== TIMESTAMPS =====
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Team Profile"
        verbose_name_plural = "Team Profiles"
    
    def __str__(self):
        return f"Profile for {self.team.name}"
    
    # ===== STATISTICS METHODS =====
    def win_rate(self):
        """Calculate and return the team's win rate as a percentage"""
        if self.matches_played == 0:
            return 0
        return round((self.matches_won / self.matches_played) * 100, 1)
    
    def update_match_stats(self, won=False):
        """Update team match statistics (safe for player transfers)"""
        self.matches_played += 1
        if won:
            self.matches_won += 1
        self.save()
    
    def sync_statistics_from_matches(self):
        """
        Safely sync TeamProfile statistics with actual match data.
        This method recalculates matches_played and matches_won from the Match model.
        """
        try:
            from matches.models import Match
            from django.db import transaction
            
            # Get all completed matches where this team participated
            completed_matches = Match.objects.filter(
                models.Q(team1=self.team) | models.Q(team2=self.team),
                status='completed'
            )
            
            matches_played = completed_matches.count()
            matches_won = completed_matches.filter(winner=self.team).count()
            
            # Update statistics safely with transaction
            with transaction.atomic():
                self.matches_played = matches_played
                self.matches_won = matches_won
                self.save(update_fields=['matches_played', 'matches_won'])
                
            return True
        except Exception as e:
            # Log error but don't break anything
            print(f"Error syncing statistics for team {self.team.name}: {e}")
            return False
    
    def get_accurate_statistics(self):
        """
        Get accurate statistics by checking if sync is needed and returning current stats.
        This method ensures statistics are up-to-date without breaking existing functionality.
        """
        try:
            from matches.models import Match
            
            # Check if statistics need updating by comparing with actual match count
            actual_matches = Match.objects.filter(
                models.Q(team1=self.team) | models.Q(team2=self.team),
                status='completed'
            ).count()
            
            # If there's a discrepancy, sync statistics
            if actual_matches != self.matches_played:
                self.sync_statistics_from_matches()
            
            return {
                'matches_played': self.matches_played,
                'matches_won': self.matches_won,
                'win_rate': self.win_rate()
            }
        except Exception:
            # Fallback to current stored values if anything goes wrong
            return {
                'matches_played': self.matches_played,
                'matches_won': self.matches_won,
                'win_rate': self.win_rate()
            }
    
    # ===== DYNAMIC RATING SYSTEM =====
    @property
    def level(self):
        """Return team level based on rating value"""
        if self.team_value <= 110:
            return 'developing'
        elif self.team_value <= 150:
            return 'competitive'  
        elif self.team_value <= 200:
            return 'elite'
        else:
            return 'champion'
    
    def get_level_display(self):
        """Return formatted level display with color coding"""
        level_map = {
            'developing': ('Developing', 'secondary'),
            'competitive': ('Competitive', 'info'),
            'elite': ('Elite', 'primary'), 
            'champion': ('Champion', 'success')
        }
        return level_map.get(self.level, ('Unknown', 'light'))
    
    # ===== TEAM MANAGEMENT INTERFACE COMPATIBILITY =====
    def get_effective_logo(self):
        """Get logo, with inheritance from parent team for sub-teams"""
        if self.logo_svg:
            return self.logo_svg.url
        
        # For sub-teams, try to inherit parent team logo
        if self.team.is_subteam and self.team.parent_team:
            parent_profile = getattr(self.team.parent_team, 'profile', None)
            if parent_profile and parent_profile.logo_svg:
                return parent_profile.logo_svg.url
        
        return None
    
    def get_effective_photo(self):
        """Get team photo, with fallback logic for sub-teams"""
        if self.team_photo_jpg:
            return self.team_photo_jpg.url
        
        # Sub-teams use their own photos, no inheritance for group photos
        return None
    
    def is_management_visible(self):
        """Check if this team should be visible in management interface"""
        # Hide friendly team from normal management UI (it's handled separately)
        if self.is_friendly_team:
            return False
        return True
    
    def can_have_players_transferred(self):
        """Check if players can be transferred to/from this team"""
        # This works with existing Friendly Team structure, doesn't modify it
        if self.is_friendly_team:
            return True  # Friendly team is source for player transfers
        
        # Regular teams can participate in transfers
        if self.profile_type in ['full', 'sub_team']:
            return True
        
        return False
    
    def calculate_team_value_from_players(self):
        """
        Calculate team value based on current player roster.
        This method is transfer-safe and updates when players move.
        Works with existing team structure without modifications.
        """
        try:
            total_player_value = 0
            player_count = 0
            
            # Get all players currently in this team (uses existing team.players relationship)
            for player in self.team.players.all():
                player_profile = getattr(player, 'profile', None)
                if player_profile:
                    total_player_value += player_profile.value
                    player_count += 1
                else:
                    # Default value for players without profiles
                    total_player_value += 100.0
                    player_count += 1
            
            if player_count == 0:
                return 100.0  # Default team value
            
            # Team value is average of player values with team bonus
            average_player_value = total_player_value / player_count
            team_bonus = min(player_count * 5, 50)  # Bonus for team size, capped at 50
            
            return round(average_player_value + team_bonus, 2)
            
        except Exception as e:
            print(f"Error calculating team value for {self.team.name}: {e}")
            return self.team_value  # Return current value if calculation fails
    
    def update_team_value(self, save=True):
        """
        Update team value based on current roster.
        Called when players are transferred to/from team.
        Works with existing player transfer logic without interfering.
        """
        try:
            new_value = self.calculate_team_value_from_players()
            old_value = self.team_value
            
            if abs(new_value - old_value) > 0.1:  # Only update if significant change
                # Record the change in history
                change_record = {
                    'timestamp': timezone.now().isoformat(),
                    'old_value': old_value,
                    'new_value': new_value,
                    'reason': 'roster_change',
                    'change': round(new_value - old_value, 2)
                }
                
                # Add to history (keep last 50 entries)
                if not self.value_history:
                    self.value_history = []
                self.value_history.append(change_record)
                if len(self.value_history) > 50:
                    self.value_history = self.value_history[-50:]
                
                self.team_value = new_value
                
                if save:
                    self.save()
                
                return True
            
            return False
            
        except Exception as e:
            print(f"Error updating team value for {self.team.name}: {e}")
            return False
    
    # ===== BADGE SYSTEM =====
    def add_badge(self, badge_name, badge_data=None):
        """Add a badge to the team"""
        if not self.badges:
            self.badges = []
        
        badge_entry = {
            'name': badge_name,
            'earned_at': timezone.now().isoformat(),
            'data': badge_data or {}
        }
        
        # Avoid duplicate badges
        existing_badges = [b['name'] for b in self.badges]
        if badge_name not in existing_badges:
            self.badges.append(badge_entry)
            self.save()
            return True
        
        return False
    
    def get_badge_display(self):
        """Get formatted badge display for templates"""
        if not self.badges:
            return []
        
        badge_display = []
        for badge in self.badges:
            # Get tournament name from badge data
            tournament_name = badge.get('data', {}).get('tournament_name', 'Unknown Tournament')
            position = badge.get('data', {}).get('position', '')
            
            # Create display name with tournament info
            badge_type = badge['name']
            if badge_type == 'tournament_1st_place':
                display_name = f"🥇 1st Place - {tournament_name}"
            elif badge_type == 'tournament_2nd_place':
                display_name = f"🥈 2nd Place - {tournament_name}"
            elif badge_type == 'tournament_3rd_place':
                display_name = f"🥉 3rd Place - {tournament_name}"
            elif badge_type == 'tournament_last_place':
                display_name = f"🎯 Participant - {tournament_name}"
            else:
                display_name = f"{badge_type.replace('_', ' ').title()} - {tournament_name}"
            
            badge_display.append({
                'name': badge['name'],
                'display_name': display_name,
                'tournament_name': tournament_name,
                'position': position,
                'earned_at': badge.get('earned_at', ''),
                'data': badge.get('data', {})
            })
        
        return badge_display
    
    # ===== FRIENDLY TEAM DETECTION (READ-ONLY) =====
    @classmethod
    def detect_friendly_team(cls):
        """
        Detect if there's an existing Friendly Team and return it.
        This method does NOT create or modify anything, only detects.
        """
        try:
            # Look for team named "Friendly Team" or similar variations
            friendly_team_names = ['Friendly Team', 'Friendly Games', 'Unassigned Players', 'Free Agents']
            
            for name in friendly_team_names:
                try:
                    team = Team.objects.get(name__iexact=name)
                    return team
                except Team.DoesNotExist:
                    continue
            
            return None
            
        except Exception as e:
            print(f"Error detecting Friendly Team: {e}")
            return None
    
    def sync_with_team_management(self):
        """
        Sync profile data with team management changes.
        Called when team structure changes (players added/removed, sub-teams created).
        Works with existing team management without interfering.
        """
        try:
            # Update team value based on current roster
            self.update_team_value(save=False)
            
            # Update statistics if needed
            # (This would integrate with match results when available)
            
            # Save all changes
            self.save()
            
            return True
            
        except Exception as e:
            print(f"Error syncing profile for {self.team.name}: {e}")
            return False



class SubTeam(models.Model):
    """
    SubTeam model for organizing players within a team
    Allows teams to create sub-groups like Triplet A, Triplet B, etc.
    """
    parent_team = models.ForeignKey(
        Team, 
        on_delete=models.CASCADE, 
        related_name='sub_teams',
        help_text="The main team this sub-team belongs to"
    )
    name = models.CharField(
        max_length=50,
        help_text="Name of the sub-team (e.g., 'Triplet A', 'Doublette 1')"
    )
    sub_team_type = models.CharField(
        max_length=20,
        choices=[
            ('triplet', 'Triplet (3 players)'),
            ('doublette', 'Doublette (2 players)'),
            ('tete_a_tete', 'Tête-à-tête (1 player)'),
            ('custom', 'Custom'),
        ],
        default='triplet',
        help_text="Type of sub-team formation"
    )
    max_players = models.PositiveIntegerField(
        default=3,
        help_text="Maximum number of players allowed in this sub-team"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ['parent_team', 'name']
        ordering = ['name']
    
    def __str__(self):
        return f"{self.parent_team.name} - {self.name}"
    
    def get_players(self):
        """Get all players assigned to this sub-team"""
        return self.player_assignments.all()
    
    def get_player_count(self):
        """Get current number of players in this sub-team"""
        return self.player_assignments.count()
    
    def can_add_player(self):
        """Check if sub-team can accept more players"""
        return self.get_player_count() < self.max_players
    
    def get_available_slots(self):
        """Get number of available slots in this sub-team"""
        return self.max_players - self.get_player_count()
    
    def is_full(self):
        """Check if sub-team is at maximum capacity"""
        return self.get_player_count() >= self.max_players
    
    def get_formation_display(self):
        """Get human-readable formation description"""
        formations = {
            'triplet': 'Triplet Formation (3 players)',
            'doublette': 'Doublette Formation (2 players)', 
            'tete_a_tete': 'Tête-à-tête Formation (1 player)',
            'custom': 'Custom Formation'
        }
        return formations.get(self.sub_team_type, 'Unknown Formation')


class SubTeamPlayerAssignment(models.Model):
    """
    Assignment of players to sub-teams within their main team
    Ensures players can only be assigned to sub-teams of their own team
    """
    sub_team = models.ForeignKey(
        SubTeam, 
        on_delete=models.CASCADE, 
        related_name='player_assignments'
    )
    player = models.ForeignKey(
        Player, 
        on_delete=models.CASCADE, 
        related_name='sub_team_assignments'
    )
    position = models.CharField(
        max_length=20,
        choices=[
            ('tirer', 'Tireur'),
            ('pointeur', 'Pointeur'),
            ('milieu', 'Milieu'),
            ('any', 'Any Position'),
        ],
        default='any',
        help_text="Player's position in this sub-team"
    )
    assigned_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ['sub_team', 'player']
        ordering = ['assigned_at']
    
    def __str__(self):
        return f"{self.player.name} → {self.sub_team.name}"
    
    def clean(self):
        """Validate that player belongs to the sub-team's parent team"""
        from django.core.exceptions import ValidationError
        if self.player.team != self.sub_team.parent_team:
            raise ValidationError(
                f"Player {self.player.name} must be a member of {self.sub_team.parent_team.name} "
                f"to be assigned to sub-team {self.sub_team.name}"
            )
    
    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)


# Add methods to existing Team model for player management
def get_friendly_team(self):
    """
    Detect and return the Friendly Team (read-only)
    This is the special team that contains unaffiliated players
    """
    try:
        # Look for team with common friendly team indicators
        friendly_candidates = Team.objects.filter(
            models.Q(name__icontains='friendly') |
            models.Q(name__icontains='unaffiliated') |
            models.Q(name__icontains='pool') |
            models.Q(name__icontains='available')
        ).first()
        
        if friendly_candidates:
            return friendly_candidates
            
        # Fallback: look for team with most players (likely the friendly team)
        teams_by_player_count = Team.objects.annotate(
            player_count=models.Count('players')
        ).order_by('-player_count')
        
        if teams_by_player_count.exists():
            return teams_by_player_count.first()
            
    except Exception:
        pass
    
    return None

def get_available_players_for_recruitment(self):
    """Get players available for recruitment (from Friendly Team only)"""
    friendly_team = self.get_friendly_team()
    if friendly_team and friendly_team != self:
        return friendly_team.players.all()
    return Player.objects.none()

def can_recruit_player(self, player):
    """Check if a player can be recruited to this team"""
    friendly_team = self.get_friendly_team()
    if not friendly_team:
        return False
    
    # Player must be in Friendly Team to be recruited
    return player.team == friendly_team

def recruit_player(self, player):
    """
    Recruit a player from Friendly Team to this team
    Returns (success: bool, message: str)
    """
    if not self.can_recruit_player(player):
        return False, f"Player {player.name} can only be recruited from Friendly Team"
    
    try:
        with transaction.atomic():
            player.team = self
            player.save()
            return True, f"Player {player.name} successfully recruited to {self.name}"
    except Exception as e:
        return False, f"Error recruiting player: {str(e)}"

def release_player(self, player):
    """
    Release a player from this team back to Friendly Team
    Returns (success: bool, message: str)
    """
    if player.team != self:
        return False, f"Player {player.name} is not a member of {self.name}"
    
    friendly_team = self.get_friendly_team()
    if not friendly_team:
        return False, "Friendly Team not found - cannot release player"
    
    try:
        with transaction.atomic():
            # Remove from any sub-teams first
            SubTeamPlayerAssignment.objects.filter(player=player).delete()
            
            # Move to Friendly Team
            player.team = friendly_team
            player.is_captain = False  # Remove captain status when released
            player.save()
            
            return True, f"Player {player.name} released to Friendly Team"
    except Exception as e:
        return False, f"Error releasing player: {str(e)}"

def get_main_roster(self):
    """Get players in main team roster (excluding sub-team-only assignments)"""
    return self.players.all()

def get_unassigned_players(self):
    """Get players in main roster who are not assigned to any sub-team"""
    assigned_player_ids = SubTeamPlayerAssignment.objects.filter(
        sub_team__parent_team=self
    ).values_list('player_id', flat=True)
    
    return self.players.exclude(id__in=assigned_player_ids)

# Add these methods to the Team model
Team.get_friendly_team = get_friendly_team
Team.get_available_players_for_recruitment = get_available_players_for_recruitment
Team.can_recruit_player = can_recruit_player
Team.recruit_player = recruit_player
Team.release_player = release_player
Team.get_main_roster = get_main_roster
Team.get_unassigned_players = get_unassigned_players

