from django.db import models
from teams.models import Team
from courts.models import Court
import math
import random # Import random for shuffling
import json

class Tournament(models.Model):
    """Tournament model for storing tournament information"""
    TOURNAMENT_FORMATS = [
        ("round_robin", "Round Robin"),
        ("knockout", "Knockout"),
        ("swiss", "Swiss System"),
        ("multi_stage", "Multi-Stage"),
    ]
    
    PLAY_FORMATS = [
        ("triplets", "Triplets (3 players)"),
        ("doublets", "Doublets (2 players)"),
        ("tete_a_tete", "Tête-à-tête (1 player)"),
        ("mixed", "Mixed Formats"),
    ]

    AUTOMATION_STATUS_CHOICES = [
        ("idle", "Idle"),
        ("processing", "Processing"),
        ("error", "Error"),
        ("completed", "Completed"),
    ]
    
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True)
    format = models.CharField(max_length=20, choices=TOURNAMENT_FORMATS, default="knockout")
    play_format = models.CharField(max_length=20, choices=PLAY_FORMATS)
    has_triplets = models.BooleanField(default=False)
    has_doublets = models.BooleanField(default=False)
    has_tete_a_tete = models.BooleanField(default=False)
    start_date = models.DateTimeField()
    end_date = models.DateTimeField()
    is_active = models.BooleanField(default=True)
    is_archived = models.BooleanField(default=False)
    is_multi_stage = models.BooleanField(default=False)
    teams = models.ManyToManyField(Team, through="TournamentTeam")
    courts = models.ManyToManyField(Court, through="TournamentCourt")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    current_round_number = models.PositiveIntegerField(null=True, blank=True, default=0, help_text="Current round being played or 0 if not started")
    automation_status = models.CharField(max_length=20, choices=AUTOMATION_STATUS_CHOICES, default="idle", help_text="Status of the automated round generation")
    
    # New field for match type configuration
    allowed_match_types = models.JSONField(
        default=dict,
        blank=True,
        help_text="Configuration for allowed match types (doublet, triplet, tete_a_tete) and mixed matches"
    )
    
    def __str__(self):
        return self.name
    
    def save(self, *args, **kwargs):
        self.is_multi_stage = (self.format == "multi_stage")
        if sum([self.has_triplets, self.has_doublets, self.has_tete_a_tete]) > 1:
            self.play_format = "mixed"
        elif self.has_triplets:
            self.play_format = "triplets"
        elif self.has_doublets:
            self.play_format = "doublets"
        elif self.has_tete_a_tete:
            self.play_format = "tete_a_tete"
            
        # Initialize allowed_match_types if empty
        if not self.allowed_match_types:
            allowed_types = []
            if self.has_triplets:
                allowed_types.append("triplet")
            if self.has_doublets:
                allowed_types.append("doublet")
            if self.has_tete_a_tete:
                allowed_types.append("tete_a_tete")
                
            self.allowed_match_types = {
                "allowed_match_types": allowed_types,
                "allow_mixed": self.play_format == "mixed"
            }
            
        super().save(*args, **kwargs)

    def generate_matches(self):
        """Generate matches for the tournament (first stage or single stage)."""
        from matches.models import Match # Import locally
        import random
        import math
        
        if self.is_multi_stage:
            first_stage = self.stages.order_by("stage_number").first()
            if first_stage:
                print(f"Generating matches for first stage ({first_stage.name}) of {self.name}")
                matches_created = first_stage.generate_stage_matches()
                return matches_created if matches_created is not None else 0
            else:
                print(f"Error: Multi-stage tournament {self.name} has no stages defined.")
                return 0

        # --- Single-Stage Logic (Fixed) --- 
        if not self.courts.exists():
            print(f"Error: No courts assigned to tournament {self.name}. Cannot generate matches.")
            return 0
            
        teams_qs = self.tournamentteam_set.filter(is_active=True).select_related("team")
        teams = list(teams_qs)
        if len(teams) < 2:
            print(f"Warning: Not enough active teams ({len(teams)}) to generate matches for {self.name}.")
            return 0
        
        print(f"Generating matches for single-stage tournament {self.name} (Format: {self.format})")
        
        # Create or get the round for single-stage tournaments
        round_obj, created = Round.objects.get_or_create(
            tournament=self,
            number=1,
            defaults={
                'name': 'Round 1',
                'stage': None,  # Single-stage tournaments don't have stages
                'number_in_stage': 1
            }
        )
        
        if created:
            print(f"Created round: {round_obj}")
        else:
            print(f"Using existing round: {round_obj}")
            # Clear existing matches for this round if regenerating
            Match.objects.filter(tournament=self, round=round_obj).delete()

        matches_created = 0
        
        if self.format == "round_robin":
            # Round-robin: each team plays against every other team once
            for i in range(len(teams)):
                for j in range(i + 1, len(teams)):
                    match = Match.objects.create(
                        tournament=self,
                        round=round_obj,
                        team1=teams[i].team,
                        team2=teams[j].team,
                        status="pending"
                    )
                    matches_created += 1
                    print(f"  Created match: {teams[i].team} vs {teams[j].team}")
                    
        elif self.format == "knockout":
            # Knockout: create brackets and matches for first round
            random.shuffle(teams)
            num_teams = len(teams)
            
            # Pair teams for first round
            for i in range(0, len(teams) - 1, 2):
                match = Match.objects.create(
                    tournament=self,
                    round=round_obj,
                    team1=teams[i].team,
                    team2=teams[i + 1].team,
                    status="pending"
                )
                matches_created += 1
                print(f"  Created match: {teams[i].team} vs {teams[i + 1].team}")
                
            # Handle odd number of teams (bye to next round)
            if len(teams) % 2 == 1:
                bye_team = teams[-1]
                print(f"  {bye_team.team} advances with a bye")
                
        elif self.format == "swiss":
            # Swiss system: pair teams randomly for first round
            teams_copy = teams.copy()
            random.shuffle(teams_copy)
            
            for i in range(0, len(teams_copy) - 1, 2):
                match = Match.objects.create(
                    tournament=self,
                    round=round_obj,
                    team1=teams_copy[i].team,
                    team2=teams_copy[i + 1].team,
                    status="pending"
                )
                matches_created += 1
                print(f"  Created match: {teams_copy[i].team} vs {teams_copy[i + 1].team}")
                
            # Handle odd number of teams (bye)
            if len(teams_copy) % 2 == 1:
                bye_team = teams_copy[-1]
                bye_team.received_bye_in_round = 1
                bye_team.save()
                print(f"  {bye_team.team} receives a bye")
        else:
            print(f"Error: Unknown tournament format '{self.format}'")
            return 0
            
        print(f"Created {matches_created} matches for {self.name}")
        
        # Set tournament status
        self.automation_status = "idle"
        self.save()
        
        # Return the number of matches created for admin feedback
        return matches_created

    def advance_to_next_stage(self):
        """
        Advances qualifying teams to the next stage and generates matches.
        Returns: (advanced: bool, matches_created: int, tournament_complete: bool)
        """
        if self.format != "multi_stage":
            return False, 0, False
            
        if self.automation_status != "idle":
            print(f"Tournament {self.name} automation is not idle (status: {self.automation_status})")
            return False, 0, False
            
        try:
            self.automation_status = "processing"
            self.save()
            
            # Get current stage
            current_stage = self._get_current_stage()
            if not current_stage:
                print(f"No current stage found for multi-stage tournament {self.name}")
                self.automation_status = "idle"
                self.save()
                return False, 0, False
                
            # Check if current stage is complete
            if not self._is_stage_complete(current_stage):
                print(f"Stage {current_stage.stage_number} is not yet complete")
                self.automation_status = "idle"
                self.save()
                return False, 0, False
                
            # Get winners from current stage
            winners = self._get_stage_winners(current_stage)
            if len(winners) < 2:
                print(f"Not enough winners ({len(winners)}) to create next stage")
                # Tournament might be complete
                self.automation_status = "completed"
                self.save()
                return False, 0, True
                
            # Create next stage
            matches_created = self._create_next_stage(winners, current_stage.stage_number + 1)
            
            # Update current round number
            self.current_round_number = current_stage.stage_number + 1
            self.automation_status = "idle"
            self.save()
            
            print(f"Advanced to stage {current_stage.stage_number + 1}, created {matches_created} matches")
            return True, matches_created, False
            
        except Exception as e:
            print(f"Error advancing tournament {self.name}: {e}")
            self.automation_status = "error"
            self.save()
            return False, 0, False

    def _get_qualifying_team_ids(self, stage):
        """Helper function to determine qualifying teams from a completed stage."""
        # This method is replaced by _get_stage_winners
        pass
    
    def _get_current_stage(self):
        """Get the current stage being played."""
        if not self.is_multi_stage:
            return None
        # Get the highest stage number that has matches
        return self.stages.filter(matches__isnull=False).order_by('-stage_number').first()
    
    def _is_stage_complete(self, stage):
        """Check if all matches in a stage are completed."""
        stage_matches = stage.matches.all()
        if not stage_matches.exists():
            return False
            
        # All matches must be completed and have winners
        for match in stage_matches:
            if match.status != "completed" or not match.winner:
                return False
        return True
    
    def _get_stage_winners(self, stage):
        """Get all winners from a completed stage."""
        winners = []
        for match in stage.matches.filter(status="completed"):
            if match.winner:
                winners.append(match.winner)
        return winners
    
    def _create_next_stage(self, winners, stage_number):
        """Create matches for the next stage with the given winners."""
        from tournaments.models import Stage
        
        # Create new stage
        new_stage = Stage.objects.create(
            tournament=self,
            stage_number=stage_number,
            name=f"Stage {stage_number}",
            format="knockout",  # Next stages are typically knockout
            num_qualifiers=1  # Winner advances (or 0 for final stage)
        )
        
        # Create matches between winners
        matches_created = 0
        for i in range(0, len(winners), 2):
            if i + 1 < len(winners):
                team1 = winners[i]
                team2 = winners[i + 1]
                
                from matches.models import Match
                match = Match.objects.create(
                    tournament=self,
                    stage=new_stage,
                    team1=team1,
                    team2=team2,
                    status="pending"
                )
                matches_created += 1
                
        return matches_created

    # === KNOCKOUT TOURNAMENT AUTOMATION ===
    
    def check_and_advance_knockout_round(self):
        """
        Check if current knockout round is complete and advance to next round.
        This method is safe to call multiple times - it only acts when needed.
        Returns: (advanced: bool, matches_created: int, tournament_complete: bool)
        """
        if self.format != "knockout":
            return False, 0, False
            
        if self.automation_status != "idle":
            print(f"Tournament {self.name} automation is not idle (status: {self.automation_status})")
            return False, 0, False
            
        try:
            self.automation_status = "processing"
            self.save()
            
            current_round = self._get_current_knockout_round()
            if not current_round:
                print(f"No current round found for knockout tournament {self.name}")
                self.automation_status = "idle"
                self.save()
                return False, 0, False
                
            # Check if current round is complete
            if not self._is_knockout_round_complete(current_round):
                print(f"Round {current_round.number} is not yet complete")
                self.automation_status = "idle"
                self.save()
                return False, 0, False
                
            print(f"Round {current_round.number} is complete! Advancing to next round...")
            
            # Get winners from current round
            winners = self._get_round_winners(current_round)
            print(f"Winners from round {current_round.number}: {[w.name for w in winners]}")
            
            # Check if tournament is complete (only 1 winner left)
            if len(winners) == 1:
                self._complete_knockout_tournament(winners[0])
                self.automation_status = "completed"
                self.save()
                print(f"Tournament {self.name} completed! Champion: {winners[0].name}")
                return True, 0, True
                
            # Create next round and matches
            matches_created = self._create_next_knockout_round(winners)
            
            self.automation_status = "idle"
            self.save()
            print(f"Advanced to next round with {matches_created} new matches")
            return True, matches_created, False
            
        except Exception as e:
            print(f"Error in knockout advancement: {e}")
            self.automation_status = "error"
            self.save()
            return False, 0, False
    
    def _get_current_knockout_round(self):
        """Get the current active round for knockout tournament."""
        if self.is_multi_stage:
            # For multi-stage knockout, get current stage's current round
            current_stage = self.stages.filter(is_active=True).first()
            if current_stage:
                return current_stage.rounds.order_by('-number').first()
        else:
            # For single-stage knockout, get the highest numbered round
            return self.rounds.order_by('-number').first()
        return None
    
    def _is_knockout_round_complete(self, round_obj):
        """Check if all matches in a knockout round are completed."""
        round_matches = round_obj.matches.all()
        if not round_matches.exists():
            return False
            
        # All matches must be completed and have winners
        for match in round_matches:
            if match.status != "completed" or not match.winner:
                return False
        return True
    
    def _get_round_winners(self, round_obj):
        """Get all winners from a completed round."""
        winners = []
        for match in round_obj.matches.filter(status="completed"):
            if match.winner:
                winners.append(match.winner)
        return winners
    
    def _create_next_knockout_round(self, winners):
        """Create the next knockout round with the given winners."""
        from matches.models import Match
        
        current_round = self._get_current_knockout_round()
        next_round_number = current_round.number + 1
        
        # Create next round
        if self.is_multi_stage:
            current_stage = self.stages.filter(is_active=True).first()
            next_round = Round.objects.create(
                tournament=self,
                stage=current_stage,
                number=next_round_number,
                name=f"Round {next_round_number}"
            )
        else:
            next_round = Round.objects.create(
                tournament=self,
                number=next_round_number,
                name=f"Round {next_round_number}"
            )
        
        # Create matches for next round
        matches_created = 0
        random.shuffle(winners)  # Randomize pairings
        
        for i in range(0, len(winners) - 1, 2):
            match = Match.objects.create(
                tournament=self,
                stage=next_round.stage if next_round.stage else None,
                round=next_round,
                team1=winners[i],
                team2=winners[i + 1],
                status="pending"
            )
            matches_created += 1
            print(f"  Created next round match: {winners[i].name} vs {winners[i + 1].name}")
        
        # Handle odd number of winners (bye)
        if len(winners) % 2 == 1:
            bye_team = winners[-1]
            print(f"  {bye_team.name} receives a bye to the following round")
            # For bye, we could create a "bye match" or handle it in the next iteration
            # For now, we'll handle it in the next round generation
        
        # Update tournament current round
        self.current_round_number = next_round_number
        self.save()
        
        return matches_created
    
    def _complete_knockout_tournament(self, champion):
        """Mark the knockout tournament as complete with the given champion."""
        print(f"Tournament {self.name} completed! Champion: {champion.name}")
        # You could add a champion field to Tournament model if needed
        # self.champion = champion
        self.current_round_number = -1  # Special value indicating completion
        # Could also set is_active = False if desired


# --- Tournament Team Model --- 
class TournamentTeam(models.Model):
    """Intermediate model for teams participating in a tournament with specific attributes."""
    tournament = models.ForeignKey(Tournament, on_delete=models.CASCADE)
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    is_active = models.BooleanField(default=True, help_text="Whether the team is currently active in the tournament")
    seeding_position = models.PositiveIntegerField(null=True, blank=True)
    current_stage_number = models.PositiveIntegerField(default=1, help_text="The stage number the team is currently in (for multi-stage)")
    # Swiss System specific fields
    swiss_points = models.IntegerField(default=0, help_text="Points accumulated in Swiss format")
    buchholz_score = models.FloatField(default=0.0, help_text="Sum of opponents scores (Buchholz tie-breaker)")
    opponents_played = models.ManyToManyField(Team, related_name="played_against_in_tournament", blank=True)
    received_bye_in_round = models.PositiveIntegerField(null=True, blank=True, help_text="Round number in which the team received a bye")
    # Add other format-specific fields as needed (e.g., group_id for poules)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("tournament", "team")
        ordering = ["-swiss_points", "-buchholz_score", "seeding_position", "id"] # Default ordering for Swiss

    def __str__(self):
        return f"{self.team.name} in {self.tournament.name}"

    def update_swiss_stats(self):
        """Recalculates Swiss points and Buchholz score based on completed matches."""
        from matches.models import Match # Import locally
        
        points = 0
        opp_scores_sum = 0
        opponents = self.opponents_played.all()

        # Points from matches
        matches_as_team1 = Match.objects.filter(tournament=self.tournament, team1=self.team, status="completed")
        matches_as_team2 = Match.objects.filter(tournament=self.tournament, team2=self.team, status="completed")
        
        for match in matches_as_team1:
            if match.winner == self.team:
                points += 3
            elif match.is_draw:
                points += 1
            # Add opponent's score for Buchholz
            if match.team2:
                 opponent_tt = TournamentTeam.objects.filter(tournament=self.tournament, team=match.team2).first()
                 if opponent_tt: opp_scores_sum += opponent_tt.swiss_points

        for match in matches_as_team2:
            if match.winner == self.team:
                points += 3
            elif match.is_draw:
                points += 1
            # Add opponent's score for Buchholz
            if match.team1:
                 opponent_tt = TournamentTeam.objects.filter(tournament=self.tournament, team=match.team1).first()
                 if opponent_tt: opp_scores_sum += opponent_tt.swiss_points

        # Points from byes
        if self.received_bye_in_round is not None:
            points += 3 # Add points for the bye received
            # How to handle Buchholz for a bye? Often counts as playing against oneself or a fixed value.
            # Simple approach: Add own score to Buchholz sum if bye received.
            # opp_scores_sum += points # Or maybe self.swiss_points before recalculation?
            # Let's refine Buchholz later if needed.

        self.swiss_points = points
        # Buchholz needs careful calculation - requires opponent scores *after* they are updated.
        # It's better calculated globally after all points are updated for the round.
        # self.buchholz_score = opp_scores_sum # Temporarily store sum, recalculate globally later.
        self.save()

    # We might need a separate task/function to calculate Buchholz globally after all points are updated.

# --- Tournament Court Model --- 
class TournamentCourt(models.Model):
    """Intermediate model for assigning specific courts to a tournament."""
    tournament = models.ForeignKey(Tournament, on_delete=models.CASCADE)
    court = models.ForeignKey(Court, on_delete=models.CASCADE)
    assigned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("tournament", "court")

    def __str__(self):
        return f"Court {self.court.number} for {self.tournament.name}"


# --- Multi-Stage Models (Simplified - No Round model shown previously) ---
class Stage(models.Model):
    """Model for individual stages within a multi-stage tournament"""
    STAGE_FORMATS = [
        ("swiss", "Swiss System"),
        ("poule", "Poules/Groups"),
        ("knockout", "Knockout"),
        ("round_robin", "Round Robin"),
    ]
    
    tournament = models.ForeignKey(Tournament, related_name="stages", on_delete=models.CASCADE)
    stage_number = models.PositiveIntegerField()
    name = models.CharField(max_length=100, blank=True)
    format = models.CharField(max_length=20, choices=STAGE_FORMATS)
    num_qualifiers = models.PositiveIntegerField(help_text="Number of teams advancing FROM this stage (0 for final stage)")
    num_rounds_in_stage = models.PositiveIntegerField(default=1, help_text="Number of rounds within this stage (e.g., for Swiss)")
    # settings = models.JSONField(null=True, blank=True) # For group size, etc.
    is_complete = models.BooleanField(default=False)
    
    class Meta:
        unique_together = ("tournament", "stage_number")
        ordering = ["stage_number"]
        
    def __str__(self):
        return f"Stage {self.stage_number}: {self.name or self.get_format_display()} ({self.tournament.name})"

    def save(self, *args, **kwargs):
        if not self.name:
            self.name = f"Stage {self.stage_number} - {self.get_format_display()}"
        super().save(*args, **kwargs)

    def generate_stage_matches(self):
        """Generate matches for this specific stage based on its format."""
        from matches.models import Match
        import random
        import math
        
        print(f"Generating matches for {self}")
        
        # Get active teams for this stage
        teams_qs = self.tournament.tournamentteam_set.filter(
            is_active=True, 
            current_stage_number=self.stage_number
        ).select_related("team")
        teams = list(teams_qs)
        
        if len(teams) < 2:
            print(f"Warning: Not enough active teams ({len(teams)}) for stage {self.stage_number}")
            return 0
            
        print(f"Found {len(teams)} teams for stage {self.stage_number}")
        
        # Check if tournament has courts
        if not self.tournament.courts.exists():
            print(f"Error: No courts assigned to tournament {self.tournament.name}")
            return 0
            
        # Get or create the round for this stage
        round_obj, created = Round.objects.get_or_create(
            tournament=self.tournament,
            stage=self,
            number_in_stage=1,
            defaults={
                'number': self._get_next_round_number(),
                'name': f"Round 1"
            }
        )
        
        if created:
            print(f"Created round: {round_obj}")
        else:
            print(f"Using existing round: {round_obj}")
            # Clear existing matches for this round if regenerating
            Match.objects.filter(tournament=self.tournament, round=round_obj).delete()
        
        # Generate matches based on stage format and return match count
        matches_created = 0
        if self.format == "round_robin":
            matches_created = self._generate_round_robin_matches(teams, round_obj)
        elif self.format == "swiss":
            matches_created = self._generate_swiss_matches(teams, round_obj)
        elif self.format == "knockout":
            matches_created = self._generate_knockout_matches(teams, round_obj)
        elif self.format == "poule":
            matches_created = self._generate_poule_matches(teams, round_obj)
        else:
            print(f"Error: Unknown stage format '{self.format}'")
            return 0
            
        print(f"Created {matches_created} matches for {self}")
        return matches_created
            
    def _get_next_round_number(self):
        """Get the next available round number for the tournament."""
        last_round = self.tournament.rounds.order_by('-number').first()
        return (last_round.number + 1) if last_round else 1
        
    def _generate_round_robin_matches(self, teams, round_obj):
        """Generate round-robin matches where each team plays every other team."""
        from matches.models import Match
        
        print(f"Generating round-robin matches for {len(teams)} teams")
        matches_created = 0
        
        for i in range(len(teams)):
            for j in range(i + 1, len(teams)):
                match = Match.objects.create(
                    tournament=self.tournament,
                    round=round_obj,
                    team1=teams[i].team,
                    team2=teams[j].team,
                    status="pending"
                )
                matches_created += 1
                print(f"  Created match: {teams[i].team} vs {teams[j].team}")
                
        print(f"Created {matches_created} round-robin matches")
        return matches_created
        
    def _generate_swiss_matches(self, teams, round_obj):
        """Generate Swiss system matches for the first round."""
        from matches.models import Match
        
        print(f"Generating Swiss matches for {len(teams)} teams")
        
        # For first round, pair teams randomly or by seeding
        teams_copy = teams.copy()
        random.shuffle(teams_copy)  # Random pairing for first round
        
        matches_created = 0
        for i in range(0, len(teams_copy) - 1, 2):
            match = Match.objects.create(
                tournament=self.tournament,
                round=round_obj,
                team1=teams_copy[i].team,
                team2=teams_copy[i + 1].team,
                status="pending"
            )
            matches_created += 1
            print(f"  Created match: {teams_copy[i].team} vs {teams_copy[i + 1].team}")
            
        # Handle odd number of teams (bye)
        if len(teams_copy) % 2 == 1:
            bye_team = teams_copy[-1]
            bye_team.received_bye_in_round = round_obj.number_in_stage
            bye_team.save()
            print(f"  {bye_team.team} receives a bye")
            
        print(f"Created {matches_created} Swiss matches")
        return matches_created
        
    def _generate_knockout_matches(self, teams, round_obj):
        """Generate knockout matches with proper bracket structure."""
        from matches.models import Match
        
        print(f"Generating knockout matches for {len(teams)} teams")
        
        # Shuffle teams for random bracket
        teams_copy = teams.copy()
        random.shuffle(teams_copy)
        
        matches_created = 0
        # Pair teams for first round
        for i in range(0, len(teams_copy) - 1, 2):
            match = Match.objects.create(
                tournament=self.tournament,
                round=round_obj,
                team1=teams_copy[i].team,
                team2=teams_copy[i + 1].team,
                status="pending"
            )
            matches_created += 1
            print(f"  Created match: {teams_copy[i].team} vs {teams_copy[i + 1].team}")
            
        # Handle odd number of teams (bye to next round)
        if len(teams_copy) % 2 == 1:
            bye_team = teams_copy[-1]
            print(f"  {bye_team.team} advances with a bye")
            
        print(f"Created {matches_created} knockout matches")
        return matches_created
        
    def _generate_poule_matches(self, teams, round_obj):
        """Generate poule/group matches."""
        # For now, treat as round-robin within groups
        # This can be enhanced later to create actual groups
        return self._generate_round_robin_matches(teams, round_obj)

class Round(models.Model):
    """Model for tournament rounds"""
    tournament = models.ForeignKey(Tournament, related_name="rounds", on_delete=models.CASCADE)
    stage = models.ForeignKey(Stage, related_name="rounds", on_delete=models.CASCADE, null=True, blank=True)
    number = models.PositiveIntegerField(help_text="Overall round number in the tournament")
    number_in_stage = models.PositiveIntegerField(default=1, help_text="Round number within the current stage")
    name = models.CharField(max_length=100, blank=True)
    is_complete = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ("tournament", "number")
        ordering = ["number"]
        
    def __str__(self):
        stage_info = f" (Stage {self.stage.stage_number})" if self.stage else ""
        return f"Round {self.number}{stage_info} - {self.tournament.name}"
        
    def save(self, *args, **kwargs):
        if not self.name:
            self.name = f"Round {self.number}"
        super().save(*args, **kwargs)

class Bracket(models.Model):
    """Model for knockout tournament brackets"""
    tournament = models.ForeignKey(Tournament, related_name="brackets", on_delete=models.CASCADE)
    stage = models.ForeignKey(Stage, related_name="brackets", on_delete=models.CASCADE, null=True, blank=True)
    round = models.ForeignKey(Round, related_name="brackets", on_delete=models.CASCADE)
    position = models.PositiveIntegerField(help_text="Position in the bracket (e.g., 1, 2, 3...)")
    name = models.CharField(max_length=100, blank=True)
    parent_bracket = models.ForeignKey("self", related_name="child_brackets", on_delete=models.SET_NULL, null=True, blank=True)
    
    class Meta:
        unique_together = ("tournament", "round", "position")
        ordering = ["round", "position"]
        
    def __str__(self):
        return f"Bracket {self.position} - Round {self.round.number} ({self.tournament.name})"
