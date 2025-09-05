from django.db import models
from django.contrib.auth.models import User
from tournaments.models import Tournament
from teams.models import Team
from court_management.models import CourtComplex
import uuid
import logging

logger = logging.getLogger(__name__)


class TournamentScenario(models.Model):
    """Predefined tournament scenarios for simple tournament creation."""
    
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField()
    is_free = models.BooleanField(default=True)
    max_players_doubles = models.IntegerField(default=12)
    max_players_triples = models.IntegerField(default=18)
    
    # Tournament configuration
    format_type = models.CharField(max_length=20, choices=[
        ('swiss', 'Swiss System'),
        ('partial_robin', 'Partial Round Robin'),
        ('knockout', 'Knockout'),
    ])
    num_rounds = models.IntegerField(default=3)
    matches_per_team = models.IntegerField(null=True, blank=True)  # For partial round robin
    team_building_method = models.CharField(max_length=20, choices=[
        ('balance', 'Balance Draft'),
        ('snake', 'Snake Draft'),
        ('random', 'Random'),
    ])
    
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)
    
    class Meta:
        ordering = ['name']
    
    def __str__(self):
        return f"{self.name} ({'Free' if self.is_free else 'Voucher Required'})"


class VoucherCode(models.Model):
    """Voucher codes for paid tournament scenarios."""
    
    code = models.CharField(max_length=20, unique=True)
    scenario = models.ForeignKey(TournamentScenario, on_delete=models.CASCADE)
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='created_vouchers')
    created_at = models.DateTimeField(auto_now_add=True)
    
    # Usage tracking
    is_used = models.BooleanField(default=False)
    used_by = models.CharField(max_length=100, blank=True)  # User identifier (could be email, name, etc.)
    used_at = models.DateTimeField(null=True, blank=True)
    used_for_tournament = models.ForeignKey(Tournament, on_delete=models.SET_NULL, null=True, blank=True)
    
    # Optional expiration
    expires_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        status = "Used" if self.is_used else "Available"
        return f"{self.code} - {self.scenario.name} ({status})"
    
    def is_valid(self):
        """Check if voucher is valid for use."""
        if self.is_used:
            return False
        if self.expires_at and self.expires_at < timezone.now():
            return False
        return True


class SimpleTournament(models.Model):
    """Simple tournament created through the user interface."""
    
    # Basic info
    name = models.CharField(max_length=200)
    scenario = models.ForeignKey(TournamentScenario, on_delete=models.CASCADE)
    format = models.CharField(max_length=10, choices=[
        ('doubles', 'Doubles'),
        ('triples', 'Triples'),
    ])
    
    # Court assignment
    court_complex = models.ForeignKey(CourtComplex, on_delete=models.CASCADE)
    assigned_courts = models.ManyToManyField('court_management.Court', blank=True)
    
    # Voucher tracking
    voucher_used = models.ForeignKey(VoucherCode, on_delete=models.SET_NULL, null=True, blank=True)
    
    # Tournament reference
    tournament = models.OneToOneField(Tournament, on_delete=models.CASCADE)
    
    # Status tracking
    status = models.CharField(max_length=20, choices=[
        ('created', 'Created'),
        ('active', 'Active'),
        ('completed', 'Completed'),
        ('cleaned_up', 'Cleaned Up'),
    ], default='created')
    
    # Metadata
    created_by = models.CharField(max_length=100)  # User identifier
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    # Team tracking for cleanup
    created_teams = models.ManyToManyField(Team, blank=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.name} - {self.scenario.name} ({self.status})"
    
    def get_team_pins(self):
        """Get all team PINs for this tournament."""
        teams = self.created_teams.all()
        return {team.name: team.pin for team in teams}
    
    def is_complete(self):
        """Check if tournament is complete."""
        return self.tournament.is_tournament_complete()
    
    def auto_complete(self):
        """Automatically complete tournament and clean up."""
        if not self.is_complete():
            return False
        
        try:
            # Assign badges (if badge system exists)
            self._assign_badges()
            
            # Return players to original teams
            self.tournament.restore_melee_players_to_original_teams()
            
            # Delete empty mêlée teams
            self._cleanup_melee_teams()
            
            # Update status
            self.status = 'cleaned_up'
            self.completed_at = timezone.now()
            self.save()
            
            logger.info(f"Auto-completed tournament: {self.name}")
            return True
            
        except Exception as e:
            logger.error(f"Error auto-completing tournament {self.name}: {e}")
            return False
    
    def _assign_badges(self):
        """Assign badges to tournament winners."""
        # TODO: Implement badge assignment logic
        # This would depend on the badge system implementation
        pass
    
    def _cleanup_melee_teams(self):
        """Delete empty mêlée teams created for this tournament."""
        for team in self.created_teams.all():
            if team.name.startswith('Mêlée Team') and team.players.count() == 0:
                logger.info(f"Deleting empty mêlée team: {team.name}")
                team.delete()


# Create default scenarios
def create_default_scenarios():
    """Create default tournament scenarios."""
    scenarios = [
        {
            'name': 'Fair',
            'description': 'Free tournament with 3 Swiss rounds and balanced team building',
            'is_free': True,
            'format_type': 'swiss',
            'num_rounds': 3,
            'team_building_method': 'balance',
        },
        {
            'name': 'Madness',
            'description': 'Premium tournament with 3 games per team (partial round robin) and snake draft',
            'is_free': False,
            'format_type': 'partial_robin',
            'matches_per_team': 3,
            'team_building_method': 'snake',
        },
    ]
    
    for scenario_data in scenarios:
        scenario, created = TournamentScenario.objects.get_or_create(
            name=scenario_data['name'],
            defaults=scenario_data
        )
        if created:
            logger.info(f"Created scenario: {scenario.name}")

