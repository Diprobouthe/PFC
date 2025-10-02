from django.db import models
from teams.models import Player, Team


class TeamMatchParticipant(models.Model):
    """
    Model for tracking actual player participation in team matches.
    This is the source of truth for who played in each match, replacing
    the flawed approach of attributing wins/losses to all team roster members.
    """
    match = models.ForeignKey(
        'matches.Match', 
        related_name="participants", 
        on_delete=models.CASCADE,
        help_text="The match this participation record belongs to"
    )
    team = models.ForeignKey(
        Team, 
        related_name="match_participations", 
        on_delete=models.CASCADE,
        help_text="The team this player participated for"
    )
    player = models.ForeignKey(
        Player, 
        related_name="team_match_participations", 
        on_delete=models.CASCADE,
        help_text="The player who participated"
    )
    
    # Position and role information
    position = models.CharField(
        max_length=20,
        choices=[
            ('pointer', 'Pointer'),
            ('milieu', 'Milieu'), 
            ('tirer', 'Tirer'),
            ('flex', 'Flex'),
            ('substitute', 'Substitute'),
        ],
        default='milieu',
        help_text="Player's position/role in the match"
    )
    
    # Participation tracking
    played = models.BooleanField(
        default=True,
        help_text="Whether the player actually played (True) or was DNP (False)"
    )
    is_substitute = models.BooleanField(
        default=False,
        help_text="Whether this player was a substitute who came in during the match"
    )
    
    # Playing time/sets (optional for future use)
    minutes_played = models.PositiveIntegerField(
        null=True, 
        blank=True,
        help_text="Minutes played (optional, for future use)"
    )
    sets_played = models.PositiveIntegerField(
        null=True, 
        blank=True,
        help_text="Number of sets played (optional, for future use)"
    )
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ('match', 'player')
        verbose_name = "Team Match Participant"
        verbose_name_plural = "Team Match Participants"
        ordering = ['match', 'team', 'position']
    
    def __str__(self):
        status = "Played" if self.played else "DNP"
        sub_indicator = " (Sub)" if self.is_substitute else ""
        return f"{self.player.name} - {self.match} ({status}{sub_indicator})"
    
    @property
    def match_result_for_player(self):
        """
        Get the match result from this player's perspective.
        Returns 'win', 'loss', 'draw', or None if match not completed.
        """
        if not self.played:
            return None  # DNP players don't get win/loss attribution
        
        match = self.match
        if match.status != 'completed' or match.winner is None:
            return None
        
        if match.winner == self.team:
            return 'win'
        elif match.loser == self.team:
            return 'loss'
        else:
            return 'draw'  # Shouldn't happen in petanque, but handle gracefully
    
    @property
    def did_win(self):
        """Returns True if this player won the match, False otherwise"""
        return self.match_result_for_player == 'win'
    
    @property
    def did_lose(self):
        """Returns True if this player lost the match, False otherwise"""
        return self.match_result_for_player == 'loss'
    
    @classmethod
    def create_from_match_players(cls, match):
        """
        Create TeamMatchParticipant records from existing MatchPlayer records.
        This is used for migrating existing data.
        """
        from matches.models import MatchPlayer
        
        participants_created = 0
        
        # Get all MatchPlayer records for this match
        match_players = MatchPlayer.objects.filter(match=match)
        
        for match_player in match_players:
            # Create or update participant record
            participant, created = cls.objects.get_or_create(
                match=match,
                player=match_player.player,
                defaults={
                    'team': match_player.team,
                    'position': match_player.role,
                    'played': True,  # Assume all MatchPlayer records represent actual play
                    'is_substitute': False,  # Can't determine from existing data
                }
            )
            
            if created:
                participants_created += 1
        
        return participants_created
    
    @classmethod
    def get_player_statistics(cls, player):
        """
        Calculate accurate player statistics based on actual participation.
        This replaces the flawed team roster-based calculation.
        """
        # Get all participations where player actually played
        participations = cls.objects.filter(
            player=player, 
            played=True
        ).select_related('match')
        
        stats = {
            'matches_played': 0,
            'matches_won': 0,
            'matches_lost': 0,
            'matches_drawn': 0,
            'win_rate': 0.0,
        }
        
        for participation in participations:
            if participation.match.status == 'completed':
                stats['matches_played'] += 1
                
                result = participation.match_result_for_player
                if result == 'win':
                    stats['matches_won'] += 1
                elif result == 'loss':
                    stats['matches_lost'] += 1
                elif result == 'draw':
                    stats['matches_drawn'] += 1
        
        # Calculate win rate
        if stats['matches_played'] > 0:
            stats['win_rate'] = round(
                (stats['matches_won'] / stats['matches_played']) * 100, 1
            )
        
        return stats
    
    @classmethod
    def handle_walkover_forfeit(cls, match, lineup_team1=None, lineup_team2=None):
        """
        Handle walkover/forfeit scenarios according to the requirements:
        - Count W/L only for players listed in the line-up
        - If no line-up was submitted, do not attribute to any player
        """
        # Clear any existing participation records for this match
        cls.objects.filter(match=match).delete()
        
        # Only create records if lineups were provided
        if lineup_team1:
            for player in lineup_team1:
                cls.objects.create(
                    match=match,
                    team=match.team1,
                    player=player,
                    position='flex',  # Default position for walkover
                    played=True,  # Count as played for walkover
                    is_substitute=False
                )
        
        if lineup_team2:
            for player in lineup_team2:
                cls.objects.create(
                    match=match,
                    team=match.team2,
                    player=player,
                    position='flex',  # Default position for walkover
                    played=True,  # Count as played for walkover
                    is_substitute=False
                )
    
    @classmethod
    def handle_bye(cls, match):
        """
        Handle BYE scenarios: no attribution to any player.
        """
        # Remove any existing participation records
        cls.objects.filter(match=match).delete()
        # Don't create any new records - BYE means no one played

