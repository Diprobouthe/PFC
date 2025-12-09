"""
Models for tracking player partnerships in Mêlée tournaments
"""

from django.db import models
from teams.models import Player
from tournaments.models import Tournament


class MeleePartnership(models.Model):
    """
    Track which players have played together as teammates in mêlée tournaments.
    This helps with analytics and future shuffling algorithms.
    """
    tournament = models.ForeignKey(
        Tournament,
        on_delete=models.CASCADE,
        related_name='melee_partnerships',
        help_text="The tournament where this partnership occurred"
    )
    player1 = models.ForeignKey(
        Player,
        on_delete=models.CASCADE,
        related_name='partnerships_as_player1',
        help_text="First player in the partnership"
    )
    player2 = models.ForeignKey(
        Player,
        on_delete=models.CASCADE,
        related_name='partnerships_as_player2',
        help_text="Second player in the partnership"
    )
    round_number = models.PositiveIntegerField(
        help_text="Round number when this partnership was formed"
    )
    team_name = models.CharField(
        max_length=100,
        help_text="Name of the mêlée team they were on together"
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="When this partnership was recorded"
    )
    
    class Meta:
        ordering = ['tournament', 'round_number', 'team_name']
        indexes = [
            models.Index(fields=['tournament', 'round_number']),
            models.Index(fields=['player1', 'player2']),
        ]
        # Ensure we don't record the same partnership twice in the same round
        unique_together = ['tournament', 'round_number', 'player1', 'player2']
    
    def __str__(self):
        return f"{self.player1.name} & {self.player2.name} - {self.team_name} (Round {self.round_number})"
    
    @classmethod
    def record_partnerships_for_round(cls, tournament, round_number):
        """
        Record all partnerships for a specific round in a tournament.
        
        Args:
            tournament: Tournament object
            round_number: The round number to record partnerships for
        """
        from tournaments.models import TournamentTeam
        
        # Get all mêlée teams in this tournament
        tournament_teams = TournamentTeam.objects.filter(
            tournament=tournament,
            team__name__startswith="Mêlée Team"
        ).select_related('team')
        
        partnerships_created = 0
        
        for tt in tournament_teams:
            team = tt.team
            players = list(team.players.all())
            
            # Record partnerships for all pairs in this team
            for i in range(len(players)):
                for j in range(i + 1, len(players)):
                    player1 = players[i]
                    player2 = players[j]
                    
                    # Always store in consistent order (lower ID first)
                    if player1.id > player2.id:
                        player1, player2 = player2, player1
                    
                    # Create partnership record (or skip if already exists)
                    partnership, created = cls.objects.get_or_create(
                        tournament=tournament,
                        round_number=round_number,
                        player1=player1,
                        player2=player2,
                        defaults={
                            'team_name': team.name
                        }
                    )
                    
                    if created:
                        partnerships_created += 1
        
        return partnerships_created
    
    @classmethod
    def get_partnership_count(cls, tournament, player1, player2):
        """
        Get the number of times two players have been teammates in a tournament.
        
        Args:
            tournament: Tournament object
            player1: First Player object
            player2: Second Player object
            
        Returns:
            int: Number of rounds they've been teammates
        """
        # Ensure consistent ordering
        if player1.id > player2.id:
            player1, player2 = player2, player1
        
        return cls.objects.filter(
            tournament=tournament,
            player1=player1,
            player2=player2
        ).count()
    
    @classmethod
    def get_player_partnership_history(cls, tournament, player):
        """
        Get all partnerships for a specific player in a tournament.
        
        Args:
            tournament: Tournament object
            player: Player object
            
        Returns:
            QuerySet of MeleePartnership objects
        """
        return cls.objects.filter(
            tournament=tournament
        ).filter(
            models.Q(player1=player) | models.Q(player2=player)
        ).select_related('player1', 'player2')


class MeleeShuffleHistory(models.Model):
    """
    Track when players were shuffled between teams in mêlée tournaments.
    """
    tournament = models.ForeignKey(
        Tournament,
        on_delete=models.CASCADE,
        related_name='shuffle_history',
        help_text="The tournament where shuffling occurred"
    )
    round_number = models.PositiveIntegerField(
        help_text="Round number after which shuffling occurred"
    )
    shuffle_type = models.CharField(
        max_length=20,
        choices=[
            ('automatic', 'Automatic (after round completion)'),
            ('manual', 'Manual (admin triggered)'),
        ],
        default='manual',
        help_text="How the shuffle was triggered"
    )
    shuffled_at = models.DateTimeField(
        auto_now_add=True,
        help_text="When the shuffle occurred"
    )
    shuffled_by = models.ForeignKey(
        'auth.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="Admin user who triggered the shuffle (for manual shuffles)"
    )
    players_shuffled = models.PositiveIntegerField(
        default=0,
        help_text="Number of players that were shuffled"
    )
    notes = models.TextField(
        blank=True,
        help_text="Optional notes about the shuffle"
    )
    
    class Meta:
        ordering = ['-shuffled_at']
        verbose_name_plural = "Mêlée shuffle histories"
    
    def __str__(self):
        return f"{self.tournament.name} - Round {self.round_number} ({self.shuffle_type})"
