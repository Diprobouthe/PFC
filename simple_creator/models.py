from django.db import models
from django.utils import timezone
from datetime import datetime, timedelta
from tournaments.models import Tournament
from courts.models import CourtComplex


class TournamentScenario(models.Model):
    """Defines tournament scenarios (Fair, Madness, etc.)"""
    name = models.CharField(max_length=50, unique=True)
    display_name = models.CharField(max_length=100)
    description = models.TextField()
    is_free = models.BooleanField(default=False)
    requires_voucher = models.BooleanField(default=True)
    max_doubles_players = models.IntegerField(default=12)
    max_triples_players = models.IntegerField(default=18)
    
    # Tournament configuration
    tournament_type = models.CharField(max_length=20, choices=[
        ('swiss', 'Swiss'),
        ('round_robin', 'Round Robin'),
    ])
    num_rounds = models.IntegerField(default=3)
    matches_per_team = models.IntegerField(default=3)
    draft_type = models.CharField(max_length=20, choices=[
        ('balance', 'Balance Draft'),
        ('snake', 'Snake Draft'),
        ('random', 'Random Draft'),
    ])
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"{self.display_name} ({'Free' if self.is_free else 'Voucher Required'})"


class VoucherCode(models.Model):
    """Voucher codes for paid tournament scenarios"""
    code = models.CharField(max_length=20, unique=True)
    scenario = models.ForeignKey(TournamentScenario, on_delete=models.CASCADE)
    is_used = models.BooleanField(default=False)
    used_at = models.DateTimeField(null=True, blank=True)
    used_for_tournament = models.ForeignKey(Tournament, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        status = "Used" if self.is_used else "Available"
        return f"{self.code} - {self.scenario.display_name} ({status})"
    
    def use_voucher(self, tournament):
        """Mark voucher as used for a specific tournament"""
        self.is_used = True
        self.used_at = timezone.now()
        self.used_for_tournament = tournament
        self.save()


class SimpleTournament(models.Model):
    """Simple tournament created through the user interface"""
    tournament = models.OneToOneField(Tournament, on_delete=models.CASCADE)
    scenario = models.ForeignKey(TournamentScenario, on_delete=models.CASCADE)
    format_type = models.CharField(max_length=10, choices=[
        ('doubles', 'Doubles'),
        ('triples', 'Triples'),
    ])
    court_complex = models.ForeignKey(CourtComplex, on_delete=models.CASCADE)
    voucher_used = models.ForeignKey(VoucherCode, null=True, blank=True, on_delete=models.SET_NULL)
    
    # Auto-generated fields
    auto_start_date = models.DateTimeField()
    auto_end_date = models.DateTimeField()
    team_pins_generated = models.BooleanField(default=False)
    
    # Cleanup tracking
    is_completed = models.BooleanField(default=False)
    badges_assigned = models.BooleanField(default=False)
    players_restored = models.BooleanField(default=False)
    mele_teams_deleted = models.BooleanField(default=False)
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"{self.scenario.display_name} - {self.format_type.title()} ({self.tournament.name})"
    
    @classmethod
    def get_auto_dates(cls):
        """Generate automatic start and end dates (next day)"""
        tomorrow = timezone.now().date() + timedelta(days=1)
        start_date = timezone.make_aware(datetime.combine(tomorrow, datetime.min.time().replace(hour=9)))
        end_date = timezone.make_aware(datetime.combine(tomorrow, datetime.min.time().replace(hour=18)))
        return start_date, end_date
    
    def get_max_players(self):
        """Get maximum players based on format"""
        if self.format_type == 'doubles':
            return self.scenario.max_doubles_players
        else:
            return self.scenario.max_triples_players
    
    def check_completion(self):
        """Check if tournament is completed and trigger cleanup if needed"""
        if not self.is_completed and self.tournament.is_tournament_complete():
            self.is_completed = True
            self.save()
            self.auto_cleanup()
    
    def auto_cleanup(self):
        """Automatically cleanup tournament after completion"""
        if not self.is_completed:
            return
        
        try:
            # Assign badges (if system supports it)
            if not self.badges_assigned:
                # TODO: Implement badge assignment when system supports it
                self.badges_assigned = True
            
            # Restore players to original teams
            if not self.players_restored:
                self.tournament.restore_melee_players_to_original_teams()
                self.players_restored = True
            
            # Delete empty MELE teams
            if not self.mele_teams_deleted:
                # Delete only the mele teams created for this tournament
                mele_teams = self.tournament.teams.filter(name__startswith='Mêlée Team')
                for team in mele_teams:
                    if team.players.count() == 0:  # Only delete if empty
                        team.delete()
                self.mele_teams_deleted = True
            
            self.save()
            
        except Exception as e:
            # Log error but don't break the system
            print(f"Error during auto cleanup for tournament {self.tournament.id}: {e}")
