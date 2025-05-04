from django.db import models
from teams.models import Team
from courts.models import Court
import math
import random # Import random for shuffling

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
        super().save(*args, **kwargs)

    def generate_matches(self):
        """Generate matches for the tournament (first stage or single stage)."""
        from matches.models import Match # Import locally
        
        if self.is_multi_stage:
            first_stage = self.stages.order_by("stage_number").first()
            if first_stage:
                print(f"Generating matches for first stage ({first_stage.name}) of {self.name}")
                first_stage.generate_stage_matches()
            else:
                print(f"Error: Multi-stage tournament {self.name} has no stages defined.")
            return

        # --- Existing Single-Stage Logic --- 
        if not self.courts.exists():
            print(f"Error: No courts assigned to tournament {self.name}. Cannot generate matches.")
            return
            
        teams_qs = self.tournamentteam_set.filter(is_active=True).select_related("team")
        teams = list(teams_qs)
        if len(teams) < 2:
            print(f"Warning: Not enough active teams ({len(teams)}) to generate matches for {self.name}.")
            return
        
        # Set current round to 1 and status to idle before generating
        self.current_round_number = 1
        self.automation_status = "idle"
        self.save()
        
        # Clear existing matches/brackets for the first round if regenerating
        Match.objects.filter(tournament=self, round_number=1).delete()
        print(f"Generating matches for single-stage tournament {self.name} (Format: {self.format}, Round: {self.current_round_number})")

        if self.format == "round_robin":
            # Round-robin: each team plays against every other team once
            for i in range(len(teams)):
                for j in range(i + 1, len(teams)):
                    Match.objects.create(
                        tournament=self,
                        round_number=self.current_round_number,
                        team1=teams[i].team,
                        team2=teams[j].team,
                    )
        elif self.format == "knockout":
            # Knockout: create brackets and matches for first round
            random.shuffle(teams)
            num_teams = len(teams)
            num_rounds_needed = math.ceil(math.log2(num_teams)) if num_teams > 0 else 0
            target_teams_in_round1 = 2 ** num_rounds_needed
            byes = target_teams_in_round1 - num_teams
            matches_in_first_round = (num_teams - byes) // 2 # Matches only between non-bye teams

            print(f"  Teams: {num_teams}, Rounds: {num_rounds_needed}, Byes: {byes}, Matches in R1: {matches_in_first_round}")

            # --- Create the Round object for Round 1 ---
            first_round, created = Round.objects.get_or_create(
                tournament=self,
                number=1, # Overall round number
                # Assuming single-stage knockout for now, no stage link needed
                # stage=None,
                # number_in_stage=1
            )
            if created:
                print(f"  Created Round object for Round 1.")
            else:
                print(f"  Found existing Round object for Round 1. Clearing its matches.")
                first_round.matches.all().delete() # Clear matches if round existed

            teams_receiving_byes = teams[:byes]
            teams_playing_matches = teams[byes:]

            # Handle Byes (Mark them in TournamentTeam)
            for i in range(byes):
                tt = teams_receiving_byes[i]
                print(f"  Assigning Bye to {tt.team.name} in Round 1")
                tt.received_bye_in_round = first_round.number # Use the round number from the object
                tt.swiss_points += 3 # Assuming 3 points for a bye win (though points aren't typical for knockout)
                tt.save()
                # Optionally create a placeholder "match" or just track advancement

            # Handle Matches
            match_count = 0
            for i in range(0, len(teams_playing_matches), 2):
                if i + 1 < len(teams_playing_matches):
                    team1_tt = teams_playing_matches[i]
                    team2_tt = teams_playing_matches[i+1]
                    print(f"  Assigning Match {team1_tt.team.name} vs {team2_tt.team.name} in Round {first_round.number}")
                    Match.objects.create(
                        tournament=self,
                        round=first_round, # <<< CORRECT: Link to the Round object
                        team1=team1_tt.team,
                        team2=team2_tt.team,
                        status="pending"
                        # stage=None # Assuming single-stage knockout
                    )
                    match_count += 1
                else:
                     # This case should ideally not happen if byes are calculated correctly
                     print(f"  Warning: Odd number of teams playing matches ({len(teams_playing_matches)}), team {teams_playing_matches[i].team.name} left over.")
            print(f"  Created {match_count} matches for Round 1.")
        
        elif self.format == "swiss":
            # Swiss system: first round is random pairings
            random.shuffle(teams)
            bye_team_tt = None
            if len(teams) % 2 != 0:
                # Assign bye to the last team after shuffling (or lowest seed if seeding exists)
                bye_team_tt = teams.pop()
                print(f"  Assigning Bye to {bye_team_tt.team.name} in Swiss Round 1")
                bye_team_tt.received_bye_in_round = self.current_round_number
                bye_team_tt.swiss_points += 3 # Assuming 3 points for a bye win
                bye_team_tt.save()
                # Optionally track opponents played for bye team?

            for i in range(0, len(teams), 2):
                team1_tt = teams[i]
                team2_tt = teams[i + 1]
                Match.objects.create(
                    tournament=self,
                    round_number=self.current_round_number,
                    team1=team1_tt.team,
                    team2=team2_tt.team,
                    status="pending"
                )
                # Track opponents
                team1_tt.opponents_played.add(team2_tt.team)
                team2_tt.opponents_played.add(team1_tt.team)

        # Court assignment is now handled by the signal/task system when matches are created/activated
        # self.assign_courts_to_matches() # Remove direct call
        print(f"Match generation complete for {self.name}, Round {self.current_round_number}.")

    # Removed assign_courts_to_matches method as it's handled by signals/tasks

    def advance_to_next_stage(self):
        """Advances qualifying teams to the next stage and generates matches."""
        # ... (rest of the multi-stage logic remains the same for now)
        pass

    def _get_qualifying_team_ids(self, stage):
        """Helper function to determine qualifying teams from a completed stage."""
        # ... (rest of the multi-stage logic remains the same for now)
        pass


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
        from matches.models import Match # Import locally
        
        # Ensure we have the correct tournament and stage context
        tournament = self.tournament
        stage = self
        
        # Determine active teams for this stage
        teams_in_stage_tt = list(TournamentTeam.objects.filter(tournament=tournament, current_stage_number=stage.stage_number, is_active=True).select_related("team"))
        teams_in_stage = [tt.team for tt in teams_in_stage_tt]
        
        if len(teams_in_stage_tt) < 2:
            print(f"Warning: Not enough active teams ({len(teams_in_stage_tt)}) in stage {stage.stage_number} to generate matches for {tournament.name}.")
            # Potentially mark stage/tournament as complete or error
            return

        # Determine the round number for these matches
        # This needs refinement - how do we track rounds *within* a stage?
        # Let's assume the first round generated for a stage is round 1 *within that stage*.
        # The overall round number might need separate tracking or calculation.
        
        # --- Create or get the Round object --- 
        # We need a robust way to determine the correct overall round number and number_in_stage
        # Simplistic approach: Assume this is the first round of this stage
        overall_round_num = tournament.current_round_number + 1 # Increment overall tournament round
        round_in_stage_num = 1 # Assuming first round of this stage
        
        # Check if a Round object already exists for this number in the tournament
        current_round, created = Round.objects.get_or_create(
            tournament=tournament, 
            number=overall_round_num, 
            defaults={
                "stage": stage,
                "number_in_stage": round_in_stage_num,
                "is_completed": False
            }
        )
        if not created:
            # If it exists, ensure it's linked to the correct stage and number_in_stage
            current_round.stage = stage
            current_round.number_in_stage = round_in_stage_num
            current_round.is_completed = False # Ensure it's not marked completed
            current_round.save()
        else:
            print(f"Created Round {current_round.number} (Stage {stage.stage_number}, Round {current_round.number_in_stage}) for {tournament.name}")
            # Update tournament's current round number only if a new round is created
            tournament.current_round_number = overall_round_num
            tournament.automation_status = "idle"
            tournament.save()

        # Clear existing matches for this specific round if regenerating
        Match.objects.filter(tournament=tournament, round=current_round).delete()
        print(f"Generating matches for {tournament.name}, Stage {stage.stage_number} ({stage.format}), Round {current_round.number} (Round in Stage {current_round.number_in_stage})")

        # --- Generate Matches based on Stage Format --- 
        if stage.format == "round_robin":
            for i in range(len(teams_in_stage_tt)):
                for j in range(i + 1, len(teams_in_stage_tt)):
                    Match.objects.create(
                        tournament=tournament,
                        stage=stage,
                        round=current_round, # Link to the Round object
                        team1=teams_in_stage_tt[i].team,
                        team2=teams_in_stage_tt[j].team,
                        status="pending"
                    )
        
        elif stage.format == "knockout":
            # Knockout logic for the stage
            teams_to_play_tt = list(teams_in_stage_tt) # Copy list
            random.shuffle(teams_to_play_tt)
            num_teams = len(teams_to_play_tt)
            num_rounds_needed = math.ceil(math.log2(num_teams)) if num_teams > 0 else 0
            target_teams_in_round = 2 ** num_rounds_needed
            byes = target_teams_in_round - num_teams
            matches_in_round = (num_teams - byes) // 2
            
            print(f"  Stage {stage.stage_number} Knockout: Teams={num_teams}, Rounds={num_rounds_needed}, Byes={byes}, Matches={matches_in_round}")
            
            teams_receiving_byes_tt = teams_to_play_tt[:byes]
            teams_playing_matches_tt = teams_to_play_tt[byes:]

            # Handle Byes
            for tt in teams_receiving_byes_tt:
                print(f"  Assigning Bye to {tt.team.name} in Stage {stage.stage_number}, Round {current_round.number}")
                tt.received_bye_in_round = current_round.number # Use overall round number
                tt.swiss_points += 3 # Keep points consistent?
                tt.save()

            # Handle Matches
            match_count = 0
            for i in range(0, len(teams_playing_matches_tt), 2):
                if i + 1 < len(teams_playing_matches_tt):
                    team1_tt = teams_playing_matches_tt[i]
                    team2_tt = teams_playing_matches_tt[i+1]
                    print(f"  Assigning Match {team1_tt.team.name} vs {team2_tt.team.name} in Stage {stage.stage_number}, Round {current_round.number}")
                    Match.objects.create(
                        tournament=tournament,
                        stage=stage,
                        round=current_round, # Link to the Round object
                        team1=team1_tt.team,
                        team2=team2_tt.team,
                        status="pending"
                    )
                    match_count += 1
                else:
                     print(f"  Warning: Odd number of teams playing matches ({len(teams_playing_matches_tt)}) in stage knockout.")
            print(f"  Created {match_count} matches for Stage {stage.stage_number}, Round {current_round.number}.")
        
        elif stage.format == "swiss":
            # Swiss logic for the stage
            teams_to_play_tt = list(teams_in_stage_tt) # Copy list
            random.shuffle(teams_to_play_tt)
            bye_team_tt = None
            if len(teams_to_play_tt) % 2 != 0:
                bye_team_tt = teams_to_play_tt.pop()
                print(f"  Assigning Bye to {bye_team_tt.team.name} in Stage {stage.stage_number}, Swiss Round {current_round.number}")
                bye_team_tt.received_bye_in_round = current_round.number
                bye_team_tt.swiss_points += 3
                bye_team_tt.save()

            for i in range(0, len(teams_to_play_tt), 2):
                team1_tt = teams_to_play_tt[i]
                team2_tt = teams_to_play_tt[i + 1]
                Match.objects.create(
                    tournament=tournament,
                    stage=stage,
                    round=current_round, # Link to the Round object
                    team1=team1_tt.team,
                    team2=team2_tt.team,
                    status="pending"
                )
                team1_tt.opponents_played.add(team2_tt.team)
                team2_tt.opponents_played.add(team1_tt.team)

        # Add other formats like 'poule' if needed
        else:
            print(f"Error: Stage format '{stage.format}' not implemented for match generation in stage {stage.stage_number}.")
            # Consider raising an error or setting tournament status
            return
            
        print(f"Match generation complete for {tournament.name}, Stage {stage.stage_number}, Round {current_round.number}.")

# No Round model was shown in previous context, assuming it's needed for automation
class Round(models.Model):
    """Represents a round within a tournament or stage."""
    tournament = models.ForeignKey(Tournament, related_name="rounds", on_delete=models.CASCADE)
    stage = models.ForeignKey(Stage, related_name="rounds", null=True, blank=True, on_delete=models.CASCADE)
    number = models.PositiveIntegerField(help_text="Overall round number in the tournament")
    number_in_stage = models.PositiveIntegerField(null=True, blank=True, help_text="Round number within the current stage (if multi-stage)")
    is_completed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("tournament", "number") # Ensure unique round numbers per tournament
        ordering = ["number"]

    def __str__(self):
        if self.stage:
            return f"Round {self.number} (Stage {self.stage.stage_number}, Round {self.number_in_stage}) - {self.tournament.name}"
        else:
            return f"Round {self.number} - {self.tournament.name}"

# Bracket model was mentioned but not shown, assuming simple structure
class Bracket(models.Model):
    """Represents a position in a knockout bracket."""
    tournament = models.ForeignKey(Tournament, on_delete=models.CASCADE)
    round = models.ForeignKey(Round, on_delete=models.CASCADE)
    position = models.PositiveIntegerField()
    # winner = models.ForeignKey(Team, null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        unique_together = ("round", "position")
        ordering = ["round__number", "position"]

    def __str__(self):
        return f"Bracket {self.position} - Round {self.round.number} - {self.tournament.name}"


