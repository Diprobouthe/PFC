from django.db import models
from teams.models import Team
from courts.models import Court
import math
import random # Import random for shuffling
import json
import logging

# Get logger for tournaments app
logger = logging.getLogger('tournaments')

class Tournament(models.Model):
    """Tournament model for storing tournament information"""
    TOURNAMENT_FORMATS = [
        ("round_robin", "Round Robin"),
        ("knockout", "Knockout"),
        ("swiss", "Swiss System"),
        ("smart_swiss", "Smart Swiss System"),
        ("wtf", "WTF (πετΑ Index)"),
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
    
    # Mêlée Mode fields
    is_melee = models.BooleanField(
        default=False,
        help_text="Enable Mêlée mode for individual player registration"
    )
    melee_format = models.CharField(
        max_length=20,
        choices=[
            ("doublets", "Doublettes (2 players)"),
            ("triplets", "Triplettes (3 players)"),
        ],
        blank=True,
        null=True,
        help_text="Team format for Mêlée mode (only used when is_melee=True)"
    )
    melee_teams_generated = models.BooleanField(
        default=False,
        help_text="Whether Mêlée teams have been automatically generated"
    )
    shuffle_players_after_round = models.BooleanField(
        default=False,
        help_text="Automatically shuffle players between mêlée teams after each round completes"
    )
    max_participants = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Maximum number of individual players allowed to register (for Mêlée tournaments)"
    )
    
    # Advertisement Banner fields
    banner_image = models.ImageField(
        upload_to='tournament_banners/',
        blank=True,
        null=True,
        help_text="Banner image for advertisement (max 2MB, jpg/png/svg)"
    )
    banner_target_url = models.URLField(
        blank=True,
        null=True,
        help_text="Target URL where banner click should redirect (must be http/https)"
    )
    banner_enabled = models.BooleanField(
        default=False,
        help_text="Enable/disable banner display on tournament overview page"
    )
    banner_alt_text = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        help_text="Alternative text for banner image (for accessibility)"
    )
    
    # Default timer configuration for all matches in this tournament
    default_time_limit_minutes = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Default time limit in minutes for all matches in this tournament (optional). Applied automatically when matches are created."
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
                logger.info(f"Generating matches for first stage ({first_stage.name}) of {self.name}")
                matches_created = first_stage.generate_stage_matches()
                return matches_created if matches_created is not None else 0
            else:
                logger.error(f"Multi-stage tournament {self.name} has no stages defined.")
                return 0

        # --- Single-Stage Logic (Fixed) --- 
        if not self.courts.exists():
            logger.error(f"No courts assigned to tournament {self.name}. Cannot generate matches.")
            return 0
            
        teams_qs = self.tournamentteam_set.filter(is_active=True).select_related("team")
        teams = list(teams_qs)
        if len(teams) < 2:
            logger.warning(f"Not enough active teams ({len(teams)}) to generate matches for {self.name}.")
            return 0
        
        logger.info(f"Generating matches for single-stage tournament {self.name} (Format: {self.format})")
        
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
            logger.info(f"Created round: {round_obj}")
        else:
            logger.info(f"Using existing round: {round_obj}")
            # Clear only pending/scheduled matches for this round if regenerating - preserve completed matches
            Match.objects.filter(
                tournament=self, 
                round=round_obj,
                status__in=['pending', 'scheduled']
            ).delete()

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
                        status="pending",
                        time_limit_minutes=self.default_time_limit_minutes
                    )
                    matches_created += 1
                    logger.debug(f"Created match: {teams[i].team} vs {teams[j].team}")
                    
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
                    status="pending",
                    time_limit_minutes=self.default_time_limit_minutes
                )
                matches_created += 1
                logger.debug(f"Created match: {teams[i].team} vs {teams[i + 1].team}")
                
            # Handle odd number of teams (bye to next round)
            if len(teams) % 2 == 1:
                bye_team = teams[-1]
                logger.info(f"{bye_team.team} advances with a bye")
                
        elif self.format == "swiss" or self.format == "smart_swiss":
            # Swiss system: pair teams randomly for first round
            # Both regular Swiss and Smart Swiss use random pairing for round 1
            teams_copy = teams.copy()
            random.shuffle(teams_copy)
            
            for i in range(0, len(teams_copy) - 1, 2):
                match = Match.objects.create(
                    tournament=self,
                    round=round_obj,
                    team1=teams_copy[i].team,
                    team2=teams_copy[i + 1].team,
                    status="pending",
                    time_limit_minutes=self.default_time_limit_minutes
                )
                matches_created += 1
                logger.debug(f"Created match: {teams_copy[i].team} vs {teams_copy[i + 1].team}")
                
            # Handle odd number of teams (bye)
            if len(teams_copy) % 2 == 1:
                bye_team = teams_copy[-1]
                bye_team.received_bye_in_round = 1
                bye_team.save()
                logger.info(f"{bye_team.team} receives a bye")
                
        elif self.format == "wtf":
            # WTF system: pair teams randomly for first round
            # WTF uses random pairing for round 1, then πετΑ Index-based pairing
            teams_copy = teams.copy()
            random.shuffle(teams_copy)
            
            for i in range(0, len(teams_copy) - 1, 2):
                match = Match.objects.create(
                    tournament=self,
                    round=round_obj,
                    team1=teams_copy[i].team,
                    team2=teams_copy[i + 1].team,
                    status="pending",
                    time_limit_minutes=self.default_time_limit_minutes
                )
                matches_created += 1
                logger.debug(f"Created WTF match: {teams_copy[i].team} vs {teams_copy[i + 1].team}")
                
            # Handle odd number of teams (bye)
            if len(teams_copy) % 2 == 1:
                bye_team = teams_copy[-1]
                bye_team.received_bye_in_round = 1
                bye_team.save()
                logger.info(f"{bye_team.team} receives a bye")
        else:
            logger.error(f"Unknown tournament format '{self.format}'")
            return 0
            
        logger.info(f"Created {matches_created} matches for {self.name}")
        
        # Set tournament status and current round number
        self.automation_status = "idle"
        if matches_created > 0 and not self.current_round_number:
            self.current_round_number = 1
            logger.info(f"Set current_round_number to 1 for {self.name}")
        self.save()
        
        # Return the number of matches created for admin feedback
        return matches_created

    def generate_melee_teams(self, algorithm='random'):
        """
        Generate teams automatically from individual Mêlée player registrations.
        
        Args:
            algorithm (str): Team generation algorithm to use
                - 'random': Random assignment (default)
                - 'balanced': Balance teams by skill level
                - 'snake_draft': Snake draft style assignment
        """
        if not self.is_melee:
            raise ValueError("Tournament is not configured for Mêlée mode")
        
        # Check if teams have already been generated
        if self.melee_teams_generated:
            logger.warning(f"Teams already generated for tournament {self.name}")
            return 0
        
        # Clear any existing mêlée teams for this tournament to prevent duplicates
        self._clear_existing_melee_teams()
        
        # Get all registered MeleePlayer objects for this tournament
        melee_players = list(self.melee_players.all())
        
        if not melee_players:
            logger.warning(f"No players registered for Mêlée tournament {self.name}")
            return 0
        
        # Determine team size based on play format
        if self.melee_format == 'tete_a_tete':
            team_size = 1
        elif self.melee_format == 'doublets':
            team_size = 2
        elif self.melee_format == 'triplets':
            team_size = 3
        else:
            team_size = 2  # default to doublets
        
        # Check if we have enough players
        if len(melee_players) < team_size:
            logger.error(f"Not enough players ({len(melee_players)}) for team size {team_size}")
            return 0
        
        # Generate teams based on algorithm
        if algorithm == 'balanced':
            teams_created = self._generate_balanced_teams(melee_players, team_size)
        elif algorithm == 'snake_draft':
            teams_created = self._generate_snake_draft_teams(melee_players, team_size)
        else:  # default to random
            teams_created = self._generate_random_teams(melee_players, team_size)
        
        # Mark teams as generated
        self.melee_teams_generated = True
        self.save()
        
        # Record partnerships for Round 1
        from tournaments.partnership_models import MeleePartnership
        partnerships_created = MeleePartnership.record_partnerships_for_round(self, round_number=1)
        logger.info(f"Recorded {partnerships_created} partnerships for Round 1")
        
        # Sync team assignments with partnerships to ensure consistency
        from tournaments.sync_team_assignments import sync_team_assignments_with_partnerships
        sync_result = sync_team_assignments_with_partnerships(self, round_number=1)
        if sync_result['success']:
            logger.info(f"Synced team assignments: {sync_result['message']}")
        else:
            logger.warning(f"Failed to sync team assignments: {sync_result['message']}")
        
        logger.info(f"Generated {teams_created} Mêlée teams for tournament {self.name} using {algorithm} algorithm")
        return teams_created

    def _clear_existing_melee_teams(self):
        """Clear any existing mêlée teams for this tournament"""
        # Get all TournamentTeam objects for this tournament where the team name starts with "Mêlée Team"
        from .models import TournamentTeam
        tournament_teams = TournamentTeam.objects.filter(
            tournament=self,
            team__name__startswith="Mêlée Team"
        )
        
        for tournament_team in tournament_teams:
            team = tournament_team.team
            
            # Restore players to their original teams before deleting the mêlée team
            players_in_team = team.players.all()
            for player in players_in_team:
                # Find the MeleePlayer record to get original team
                try:
                    melee_player = self.melee_players.get(player=player)
                    if melee_player.original_team:
                        player.team = melee_player.original_team
                        player.save()
                        logger.info(f"Restored player {player.name} to original team {melee_player.original_team.name}")
                        
                        # Refresh the player's session
                        from pfc_core.session_refresh import refresh_player_team_session
                        refresh_player_team_session(player)
                except:
                    logger.warning(f"Could not restore player {player.name} to original team")
            
            # Delete the tournament team association
            tournament_team.delete()
            
            # Delete the mêlée team itself
            team.delete()
            logger.info(f"Deleted mêlée team: {team.name}")

    def _generate_random_teams(self, melee_players, team_size):
        """Generate teams using random assignment"""
        import random
        random.shuffle(melee_players)
        
        teams_created = 0
        current_team_players = []
        
        for melee_player in melee_players:
            current_team_players.append(melee_player)
            
            # Create team when we have enough players
            if len(current_team_players) == team_size:
                team_name = f"Mêlée Team {teams_created + 1}"
                team = self._create_team_from_players(current_team_players, team_name)
                teams_created += 1
                current_team_players = []
                
                logger.info(f"Created random Mêlée team: {team_name}")
        
        # Handle remaining players (if any)
        if current_team_players:
            logger.warning(f"{len(current_team_players)} players left over and not assigned to teams")
        
        return teams_created
    
    def _generate_balanced_teams(self, melee_players, team_size):
        """Generate teams balanced by skill level and rating"""
        # Get player ratings and skill levels
        player_data = []
        for mp in melee_players:
            try:
                profile = mp.player.profile
                rating = profile.value
                skill_level = profile.skill_level
            except:
                # Default values if profile doesn't exist
                rating = 100.0
                skill_level = 1
            
            player_data.append({
                'melee_player': mp,
                'rating': rating,
                'skill_level': skill_level
            })
        
        # Sort players by rating (descending)
        player_data.sort(key=lambda x: x['rating'], reverse=True)
        
        # Calculate number of complete teams
        num_teams = len(melee_players) // team_size
        teams = [[] for _ in range(num_teams)]
        
        # Distribute players to balance team strength
        for i, player in enumerate(player_data[:num_teams * team_size]):
            team_index = i % num_teams
            teams[team_index].append(player['melee_player'])
        
        # Create teams
        teams_created = 0
        for i, team_players in enumerate(teams):
            if len(team_players) == team_size:
                team_name = f"Mêlée Team {i + 1}"
                team = self._create_team_from_players(team_players, team_name)
                teams_created += 1
                
                # Calculate team average rating for logging
                avg_rating = sum(pd['rating'] for pd in player_data if pd['melee_player'] in team_players) / team_size
                logger.info(f"Created balanced Mêlée team: {team_name} (avg rating: {avg_rating:.1f})")
        
        # Handle remaining players
        remaining = len(melee_players) % team_size
        if remaining > 0:
            logger.warning(f"{remaining} players left over and not assigned to teams")
        
        return teams_created
    
    def _generate_snake_draft_teams(self, melee_players, team_size):
        """Generate teams using snake draft algorithm"""
        # Get player ratings
        player_data = []
        for mp in melee_players:
            try:
                rating = mp.player.profile.value
            except:
                rating = 100.0
            
            player_data.append({
                'melee_player': mp,
                'rating': rating
            })
        
        # Sort players by rating (descending)
        player_data.sort(key=lambda x: x['rating'], reverse=True)
        
        # Calculate number of complete teams
        num_teams = len(melee_players) // team_size
        teams = [[] for _ in range(num_teams)]
        
        # Snake draft assignment
        for round_num in range(team_size):
            for team_index in range(num_teams):
                player_index = round_num * num_teams + team_index
                if player_index < len(player_data):
                    # Reverse direction on odd rounds (snake pattern)
                    if round_num % 2 == 1:
                        actual_team_index = num_teams - 1 - team_index
                    else:
                        actual_team_index = team_index
                    
                    teams[actual_team_index].append(player_data[player_index]['melee_player'])
        
        # Create teams
        teams_created = 0
        for i, team_players in enumerate(teams):
            if len(team_players) == team_size:
                team_name = f"Mêlée Team {i + 1}"
                team = self._create_team_from_players(team_players, team_name)
                teams_created += 1
                
                # Calculate team average rating for logging
                avg_rating = sum(pd['rating'] for pd in player_data if pd['melee_player'] in team_players) / team_size
                logger.info(f"Created snake draft Mêlée team: {team_name} (avg rating: {avg_rating:.1f})")
        
        # Handle remaining players
        remaining = len(melee_players) % team_size
        if remaining > 0:
            logger.warning(f"{remaining} players left over and not assigned to teams")
        
        return teams_created
    
    def _create_team_from_players(self, melee_players, team_name):
        """Helper method to create a team from a list of MeleePlayer objects"""
        from teams.models import Team, Player
        
        # Create the mêlée team for tournament purposes
        team = Team.objects.create(name=team_name)
        
        # Transfer players to the mêlée team temporarily, storing original team for restoration
        for mp in melee_players:
            original_player = mp.player
            
            # Store the original team if not already stored
            if not mp.original_team:
                mp.original_team = original_player.team
            
            # Transfer the player to the mêlée team
            original_player.team = team
            original_player.save()
            
            # Update the MeleePlayer record to track the assigned team
            mp.assigned_team = team
            mp.save()
            
            logger.info(f"Transferred player {original_player.name} from {mp.original_team.name if mp.original_team else 'No Team'} to mêlée team {team_name}")
            
            # Refresh the player's session so they don't need to logout/login
            from pfc_core.session_refresh import refresh_player_team_session
            refresh_player_team_session(original_player)
        
        # Add team to tournament
        TournamentTeam.objects.create(tournament=self, team=team)
        
        return team

    def restore_melee_players_to_original_teams(self):
        """Restore all mêlée players to their original teams after tournament completion"""
        if not self.is_melee:
            logger.warning(f"Tournament {self.name} is not a mêlée tournament")
            return 0
        
        restored_count = 0
        for mp in self.melee_players.all():
            if mp.original_team and mp.player.team != mp.original_team:
                old_melee_team = mp.player.team
                mp.player.team = mp.original_team
                mp.player.save()
                
                logger.info(f"Restored player {mp.player.name} from {old_melee_team.name} back to {mp.original_team.name}")
                
                # Refresh the player's session so they don't need to logout/login
                from pfc_core.session_refresh import refresh_player_team_session
                refresh_player_team_session(mp.player)
                
                restored_count += 1
        
        logger.info(f"Restored {restored_count} players to their original teams for tournament {self.name}")
        return restored_count

    def is_tournament_complete(self):
        """Check if the tournament is complete (all matches finished)"""
        from matches.models import Match
        
        # Check if there are any pending or active matches
        pending_matches = Match.objects.filter(
            tournament=self,
            status__in=['pending', 'pending_verification', 'active', 'waiting_validation']
        ).count()
        
        # Tournament is complete if no pending matches exist
        return pending_matches == 0

    def auto_restore_players_on_completion(self):
        """Automatically restore mêlée players if tournament is complete"""
        if self.is_melee and self.is_tournament_complete():
            restored_count = self.restore_melee_players_to_original_teams()
            if restored_count > 0:
                logger.info(f"Auto-restored {restored_count} players for completed tournament {self.name}")
            return restored_count
        return 0

    def advance_to_next_stage(self):
        """
        Advances qualifying teams to the next stage and generates matches.
        Returns: (advanced: bool, matches_created: int, tournament_complete: bool)
        """
        if self.format != "multi_stage":
            return False, 0, False
            
        if self.automation_status != "idle":
            logger.warning(f"Tournament {self.name} automation is not idle (status: {self.automation_status})")
            return False, 0, False
            
        try:
            self.automation_status = "processing"
            self.save()
            
            # Get current stage
            current_stage = self._get_current_stage()
            if not current_stage:
                logger.error(f"No current stage found for multi-stage tournament {self.name}")
                self.automation_status = "idle"
                self.save()
                return False, 0, False
                
            # Check if current stage is complete
            if not self._is_stage_complete(current_stage):
                logger.info(f"Stage {current_stage.stage_number} is not yet complete")
                self.automation_status = "idle"
                self.save()
                return False, 0, False
                
            # Get winners from current stage
            winners = self._get_stage_winners(current_stage)
            if len(winners) < 2:
                logger.warning(f"Not enough winners ({len(winners)}) to create next stage")
                # Tournament might be complete
                self.automation_status = "completed"
                self.save()
                
                # Assign tournament badges
                try:
                    from .completion import check_and_complete_tournament
                    check_and_complete_tournament(self)
                    logger.info(f"Tournament badges assigned for completed multi-stage tournament {self.id}")
                except Exception as e:
                    logger.exception(f"Error assigning badges for completed multi-stage tournament {self.id}: {e}")
                
                return False, 0, True
                
            # Create next stage
            matches_created = self._create_next_stage(winners, current_stage.stage_number + 1)
            
            # Update current round number
            self.current_round_number = current_stage.stage_number + 1
            self.automation_status = "idle"
            self.save()
            
            logger.info(f"Advanced to stage {current_stage.stage_number + 1}, created {matches_created} matches")
            return True, matches_created, False
            
        except Exception as e:
            logger.error(f"Error advancing tournament {self.name}: {e}")
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
        # Get the highest stage number that has rounds with matches
        return self.stages.filter(rounds__matches__isnull=False).order_by('-stage_number').first()
    
    def _is_stage_complete(self, stage):
        """Check if all required rounds in a stage are completed."""
        # FIXED: Check if all required rounds exist and are complete, not just matches
        
        required_rounds = stage.num_rounds_in_stage
        logger.info(f"Checking stage {stage.stage_number} completion: requires {required_rounds} rounds")
        
        # Count completed rounds in this stage
        completed_rounds = 0
        for round_num in range(1, required_rounds + 1):
            try:
                # Import Round here to avoid circular imports
                from tournaments.models import Round
                round_obj = Round.objects.get(stage=stage, number_in_stage=round_num)
                if round_obj.is_complete:
                    completed_rounds += 1
                    logger.debug(f"Round {round_num} in stage {stage.stage_number} is complete")
                else:
                    logger.debug(f"Round {round_num} in stage {stage.stage_number} is not complete")
                    break  # If any round is incomplete, stage is not complete
            except Round.DoesNotExist:
                logger.debug(f"Round {round_num} in stage {stage.stage_number} does not exist yet")
                break  # If round doesn't exist, stage is not complete
        
        is_complete = completed_rounds >= required_rounds
        logger.info(f"Stage {stage.stage_number} completion check: {completed_rounds}/{required_rounds} rounds complete = {is_complete}")
        return is_complete
    
    def _get_stage_winners(self, stage):
        """Get qualifying teams from a completed stage based on stage format."""
        from matches.models import Match
        
        if stage.format == "swiss":
            # For Swiss tournaments, get top teams based on Swiss points and rankings
            logger.info(f"Getting Swiss qualifiers for stage {stage.stage_number} (format: {stage.format})")
            
            # Get all teams in this stage, ordered by Swiss points
            stage_teams = self.tournamentteam_set.filter(
                is_active=True,
                current_stage_number=stage.stage_number
            ).order_by("-swiss_points", "-buchholz_score", "id")
            
            # Get the top qualifying teams based on num_qualifiers
            num_qualifiers = stage.num_qualifiers
            if num_qualifiers <= 0:
                # If num_qualifiers is 0 or negative, take all teams (for final stage)
                qualifiers = [tt.team for tt in stage_teams]
            else:
                # Take the top N teams
                qualifiers = [tt.team for tt in stage_teams[:num_qualifiers]]
            
            logger.info(f"Swiss stage {stage.stage_number}: {len(qualifiers)} teams qualify out of {len(stage_teams)} total")
            return qualifiers
            
        elif stage.format == "round_robin":
            # For round robin tournaments, calculate standings based on wins and points
            logger.info(f"Getting round robin qualifiers for stage {stage.stage_number} (format: {stage.format})")
            
            # Calculate team standings from match results
            teams_stats = {}
            stage_matches = Match.objects.filter(round__stage=stage, status="completed")
            
            # Initialize all teams in this stage
            stage_teams = self.tournamentteam_set.filter(
                is_active=True,
                current_stage_number=stage.stage_number
            )
            for tt in stage_teams:
                teams_stats[tt.team.id] = {
                    'team': tt.team,
                    'wins': 0,
                    'losses': 0,
                    'points_for': 0,
                    'points_against': 0
                }
            
            # Calculate stats from matches
            for match in stage_matches:
                if match.team1.id in teams_stats and match.team2.id in teams_stats:
                    teams_stats[match.team1.id]['points_for'] += match.team1_score
                    teams_stats[match.team1.id]['points_against'] += match.team2_score
                    teams_stats[match.team2.id]['points_for'] += match.team2_score
                    teams_stats[match.team2.id]['points_against'] += match.team1_score
                    
                    if match.team1_score > match.team2_score:
                        teams_stats[match.team1.id]['wins'] += 1
                        teams_stats[match.team2.id]['losses'] += 1
                    else:
                        teams_stats[match.team2.id]['wins'] += 1
                        teams_stats[match.team1.id]['losses'] += 1
            
            # Sort teams by wins (descending), then by points difference (descending)
            sorted_teams = sorted(
                teams_stats.values(),
                key=lambda x: (x['wins'], x['points_for'] - x['points_against'], x['points_for']),
                reverse=True
            )
            
            # Get the top qualifying teams based on num_qualifiers
            num_qualifiers = stage.num_qualifiers
            if num_qualifiers <= 0:
                # If num_qualifiers is 0 or negative, take all teams (for final stage)
                qualifiers = [team_stat['team'] for team_stat in sorted_teams]
            else:
                # Take the top N teams
                qualifiers = [team_stat['team'] for team_stat in sorted_teams[:num_qualifiers]]
            
            logger.info(f"Round robin stage {stage.stage_number}: {len(qualifiers)} teams qualify out of {len(sorted_teams)} total")
            for i, team in enumerate(qualifiers, 1):
                logger.info(f"  {i}. {team.name}")
            
            return qualifiers
            
        else:
            # For knockout and other formats, get match winners
            logger.info(f"Getting match winners for stage {stage.stage_number} (format: {stage.format})")
            winners = []
            stage_matches = Match.objects.filter(round__stage=stage, status="completed")
            for match in stage_matches:
                if match.winner:
                    winners.append(match.winner)
            
            logger.info(f"Stage {stage.stage_number}: {len(winners)} match winners found")
            return winners
    
    def _create_next_stage(self, winners, stage_number):
        """Create matches for the next stage with the given winners."""
        from tournaments.models import Stage
        
        # Get the format from the previous stage to preserve tournament design
        previous_stage = self.stages.filter(stage_number=stage_number-1).first()
        if previous_stage:
            stage_format = previous_stage.format
            num_qualifiers = previous_stage.num_qualifiers
            logger.info(f"Preserving stage format '{stage_format}' from previous stage for stage {stage_number}")
        else:
            # Fallback to knockout if no previous stage found
            stage_format = "knockout"
            num_qualifiers = 1
            logger.warning(f"No previous stage found for stage {stage_number}, defaulting to knockout format")
        
        # Get or create the next stage
        next_stage, created = Stage.objects.get_or_create(
            tournament=self,
            stage_number=stage_number,
            defaults={
                'name': f"Stage {stage_number}",
                'format': stage_format,  # ✅ FIXED: Preserve original format instead of hardcoding knockout
                'num_qualifiers': num_qualifiers  # Preserve qualifiers from previous stage
            }
        )
        
        # Create a round for this stage
        from tournaments.models import Round
        round_obj, round_created = Round.objects.get_or_create(
            tournament=self,
            stage=next_stage,
            number_in_stage=1,
            defaults={
                'number': self._get_next_round_number(),
                'name': f"Round 1"
            }
        )
        
        # Clear only pending/scheduled matches if regenerating - preserve completed matches
        if not round_created:
            from matches.models import Match
            Match.objects.filter(
                tournament=self, 
                round=round_obj,
                status__in=['pending', 'scheduled']
            ).delete()
        
        # Create matches between winners
        matches_created = 0
        for i in range(0, len(winners), 2):
            if i + 1 < len(winners):
                team1 = winners[i]
                team2 = winners[i + 1]
                
                from matches.models import Match
                match = Match.objects.create(
                    tournament=self,
                    round=round_obj,
                    team1=team1,
                    team2=team2,
                    status="pending",
                    time_limit_minutes=self.default_time_limit_minutes
                )
                matches_created += 1
                
        # Update teams' current stage number
        for winner in winners:
            tournament_team = self.tournamentteam_set.filter(team=winner).first()
            if tournament_team:
                tournament_team.current_stage_number = stage_number
                tournament_team.save()
                
        return matches_created

    def _get_next_round_number(self):
        """Get the next available round number for the tournament."""
        last_round = self.rounds.order_by('-number').first()
        return (last_round.number + 1) if last_round else 1

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
            logger.info(f"Tournament {self.name} automation is not idle (status: {self.automation_status})")
            return False, 0, False
            
        try:
            self.automation_status = "processing"
            self.save()
            
            current_round = self._get_current_knockout_round()
            if not current_round:
                logger.error(f"No current round found for knockout tournament {self.name}")
                self.automation_status = "idle"
                self.save()
                return False, 0, False
                
            # Check if current round is complete
            if not self._is_knockout_round_complete(current_round):
                logger.info(f"Round {current_round.number} is not yet complete")
                self.automation_status = "idle"
                self.save()
                return False, 0, False
                
            logger.info(f"Round {current_round.number} is complete! Advancing to next round...")
            
            # Get winners from current round
            winners = self._get_round_winners(current_round)
            logger.info(f"Winners from round {current_round.number}: {[w.name for w in winners]}")
            
            # Check if tournament is complete (only 1 winner left)
            if len(winners) == 1:
                self._complete_knockout_tournament(winners[0])
                self.automation_status = "completed"
                self.save()
                logger.info(f"Tournament {self.name} completed! Champion: {winners[0].name}")
                return True, 0, True
                
            # Create next round and matches
            matches_created = self._create_next_knockout_round(winners)
            
            self.automation_status = "idle"
            self.save()
            logger.info(f"Advanced to next round with {matches_created} new matches")
            return True, matches_created, False
            
        except Exception as e:
            logger.error(f"Error in knockout advancement: {e}")
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
                status="pending",
                time_limit_minutes=self.default_time_limit_minutes
            )
            matches_created += 1
            logger.debug(f"Created next round match: {winners[i].name} vs {winners[i + 1].name}")
        
        # Handle odd number of winners (bye)
        if len(winners) % 2 == 1:
            bye_team = winners[-1]
            logger.debug(f"{bye_team.name} receives a bye to the following round")
            # For bye, we could create a "bye match" or handle it in the next iteration
            # For now, we'll handle it in the next round generation
        
        # Update tournament current round
        self.current_round_number = next_round_number
        self.save()
        
        return matches_created
    
    def _complete_knockout_tournament(self, champion):
        """Mark the knockout tournament as complete with the given champion."""
        logger.info(f"Tournament {self.name} completed! Champion: {champion.name}")
        # You could add a champion field to Tournament model if needed
        # self.champion = champion
        self.current_round_number = -1  # Special value indicating completion
        # Could also set is_active = False if desired


# --- Mêlée Player Model ---
class MeleePlayer(models.Model):
    """Model for individual player registration in Mêlée tournaments"""
    tournament = models.ForeignKey(Tournament, on_delete=models.CASCADE, related_name='melee_players')
    player = models.ForeignKey('teams.Player', on_delete=models.CASCADE)
    registered_at = models.DateTimeField(auto_now_add=True)
    assigned_team = models.ForeignKey('teams.Team', on_delete=models.SET_NULL, null=True, blank=True, 
                                     related_name='assigned_melee_players',
                                     help_text="Auto-generated team this player was assigned to")
    original_team = models.ForeignKey('teams.Team', on_delete=models.SET_NULL, null=True, blank=True,
                                     related_name='original_melee_players',
                                     help_text="Original team before mêlée assignment for restoration")
    
    class Meta:
        unique_together = ('tournament', 'player')
        verbose_name = "Mêlée Player"
        verbose_name_plural = "Mêlée Players"
    
    def __str__(self):
        return f"{self.player.name} in {self.tournament.name}"

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
            # No draws in petanque - if not winner, then 0 points
            # Add opponent's score for Buchholz
            if match.team2:
                 opponent_tt = TournamentTeam.objects.filter(tournament=self.tournament, team=match.team2).first()
                 if opponent_tt: opp_scores_sum += opponent_tt.swiss_points

        for match in matches_as_team2:
            if match.winner == self.team:
                points += 3
            # No draws in petanque - if not winner, then 0 points
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
        ("smart_swiss", "Smart Swiss System"),
        ("wtf", "WTF (πετΑ Index)"),
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
    
    # New field for Incomplete Round Robin
    num_matches_per_team = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Number of matches per team for Incomplete Round Robin format (leave blank for full Round Robin)"
    )
    
    # settings = models.JSONField(null=True, blank=True) # For group size, etc.
    is_complete = models.BooleanField(default=False)
    
    class Meta:
        unique_together = ("tournament", "stage_number")
        ordering = ["stage_number"]
    
    def check_and_update_completion(self):
        """Check if all matches in this stage are completed and update is_complete status"""
        from matches.models import Match
        
        # Get all matches for this stage
        stage_matches = Match.objects.filter(round__stage=self)
        total_matches = stage_matches.count()
        
        if total_matches == 0:
            # No matches in this stage yet
            return False
            
        completed_matches = stage_matches.filter(status='completed').count()
        
        # Update completion status
        was_complete = self.is_complete
        self.is_complete = (completed_matches == total_matches)
        
        if self.is_complete != was_complete:
            self.save()
            logger.info(f"Updated {self} completion status: {self.is_complete} ({completed_matches}/{total_matches} matches completed)")
        
        return self.is_complete
        
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
        
        logger.info(f"Generating matches for {self}")
        
        # Get active teams for this stage
        teams_qs = self.tournament.tournamentteam_set.filter(
            is_active=True, 
            current_stage_number=self.stage_number
        ).select_related("team")
        teams = list(teams_qs)
        
        if len(teams) < 2:
            logger.warning(f" Not enough active teams ({len(teams)}) for stage {self.stage_number}")
            return 0
            
        logger.info(f"Found {len(teams)} teams for stage {self.stage_number}")
        
        # Check if tournament has courts
        if not self.tournament.courts.exists():
            logger.error(f" No courts assigned to tournament {self.tournament.name}")
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
            logger.info(f"Created round: {round_obj}")
        else:
            logger.info(f"Using existing round: {round_obj}")
            # Clear only pending/scheduled matches for this round if regenerating - preserve completed matches
            Match.objects.filter(
                tournament=self.tournament, 
                round=round_obj,
                status__in=['pending', 'scheduled']
            ).delete()
        
        # Generate matches based on stage format and return match count
        matches_created = 0
        if self.format == "round_robin":
            matches_created = self._generate_round_robin_matches(teams, round_obj)
        elif self.format == "swiss":
            matches_created = self._generate_swiss_matches(teams, round_obj)
        elif self.format == "smart_swiss":
            matches_created = self._generate_smart_swiss_matches(teams, round_obj)
        elif self.format == "wtf":
            matches_created = self._generate_wtf_matches(teams, round_obj)
        elif self.format == "knockout":
            matches_created = self._generate_knockout_matches(teams, round_obj)
        elif self.format == "poule":
            matches_created = self._generate_poule_matches(teams, round_obj)
        else:
            logger.error(f" Unknown stage format '{self.format}'")
            return 0
            
        logger.info(f"Created {matches_created} matches for {self}")
        
        # Update tournament current_round_number if this is the first round
        if matches_created > 0 and not self.tournament.current_round_number:
            self.tournament.current_round_number = 1
            self.tournament.save()
            logger.info(f"Set current_round_number to 1 for {self.tournament.name}")
        
        return matches_created
            
    def _get_next_round_number(self):
        """Get the next available round number for the tournament."""
        last_round = self.tournament.rounds.order_by('-number').first()
        return (last_round.number + 1) if last_round else 1
        
    def _generate_round_robin_matches(self, teams, round_obj):
        """Generate round-robin matches where each team plays every other team."""
        from matches.models import Match
        
        # Check if this is a partial round robin (limited matches per team)
        if self.num_matches_per_team:
            logger.info(f"Generating partial round-robin matches for {len(teams)} teams (max {self.num_matches_per_team} matches per team)")
            return self._generate_partial_round_robin_matches(teams, round_obj)
        
        # Full round robin - each team plays every other team
        logger.info(f"Generating full round-robin matches for {len(teams)} teams")
        matches_created = 0
        
        for i in range(len(teams)):
            for j in range(i + 1, len(teams)):
                match = Match.objects.create(
                    tournament=self.tournament,
                    round=round_obj,
                    team1=teams[i].team,
                    team2=teams[j].team,
                    status="pending",
                    time_limit_minutes=self.tournament.default_time_limit_minutes
                )
                matches_created += 1
                logger.debug(f"Created match: {teams[i].team} vs {teams[j].team}")
                
        logger.info(f"Created {matches_created} round-robin matches")
        return matches_created
    
    def _generate_partial_round_robin_matches(self, teams, round_obj):
        """Generate partial round-robin matches using circle method with parent-child constraint.
        
        Algorithm:
        1. Generate full round robin using circle method
        2. Identify forbidden pairs (parent-child relationships)
        3. Filter out rounds containing forbidden pairs
        4. Select first N clean rounds where N = matches_per_team
        """
        from matches.models import Match
        import random
        
        matches_per_team = self.num_matches_per_team
        num_teams = len(teams)
        
        logger.info(f"Generating Smart Robin using circle method: {matches_per_team} matches per team for {num_teams} teams")
        
        # Calculate total matches needed
        total_team_matches = num_teams * matches_per_team
        total_matches = total_team_matches // 2
        logger.info(f"Target: {total_matches} total matches ({total_team_matches} team-matches)")
        
        # Identify forbidden pairs (parent-child relationships)
        forbidden_pairs = set()
        for i in range(num_teams):
            for j in range(i + 1, num_teams):
                team1, team2 = teams[i], teams[j]
                
                is_forbidden = False
                reason = ""
                
                # Check if teams share the same parent
                if (team1.team.parent_team and team2.team.parent_team and 
                    team1.team.parent_team.id == team2.team.parent_team.id):
                    is_forbidden = True
                    reason = f"same parent: {team1.team.parent_team.name}"
                
                # Check if team1 is parent of team2
                elif team2.team.parent_team and team2.team.parent_team.id == team1.team.id:
                    is_forbidden = True
                    reason = f"{team1.team.name} is parent of {team2.team.name}"
                
                # Check if team2 is parent of team1
                elif team1.team.parent_team and team1.team.parent_team.id == team2.team.id:
                    is_forbidden = True
                    reason = f"{team2.team.name} is parent of {team1.team.name}"
                
                if is_forbidden:
                    forbidden_pairs.add((team1.team.id, team2.team.id))
                    forbidden_pairs.add((team2.team.id, team1.team.id))  # Both directions
                    logger.info(f"Forbidden pair: {team1.team.name} vs {team2.team.name} ({reason})")
        
        logger.info(f"Found {len(forbidden_pairs)//2} forbidden parent-child pairs")
        
        # Generate full round robin using circle method
        def generate_full_round_robin(teams):
            """Generate full round robin using circle method."""
            n = len(teams)
            if n % 2 == 1:
                teams = teams + [None]  # Add dummy team for odd number
                n += 1
            
            rounds = []
            for round_num in range(n - 1):
                round_matches = []
                for i in range(n // 2):
                    team1_idx = i
                    team2_idx = n - 1 - i
                    
                    if teams[team1_idx] is not None and teams[team2_idx] is not None:
                        round_matches.append((teams[team1_idx], teams[team2_idx]))
                
                rounds.append(round_matches)
                
                # Rotate teams (keep first team fixed, rotate others)
                teams = [teams[0]] + [teams[-1]] + teams[1:-1]
            
            return rounds
        
        # Generate all rounds
        all_rounds = generate_full_round_robin(teams.copy())
        logger.info(f"Generated {len(all_rounds)} rounds using circle method")
        
        # Filter out rounds containing forbidden pairs
        clean_rounds = []
        for round_num, round_matches in enumerate(all_rounds):
            has_forbidden = False
            for team1, team2 in round_matches:
                if (team1.team.id, team2.team.id) in forbidden_pairs:
                    has_forbidden = True
                    logger.info(f"Round {round_num + 1} contains forbidden pair: {team1.team.name} vs {team2.team.name}")
                    break
            
            if not has_forbidden:
                clean_rounds.append((round_num + 1, round_matches))
                logger.info(f"Round {round_num + 1} is clean with {len(round_matches)} matches")
        
        logger.info(f"Found {len(clean_rounds)} clean rounds out of {len(all_rounds)} total rounds")
        
        # Check if we have enough clean rounds
        if len(clean_rounds) < matches_per_team:
            logger.error(f"Not enough clean rounds! Need {matches_per_team}, but only have {len(clean_rounds)}")
            logger.error("Falling back to allowing some forbidden pairs...")
            
            # Fall back to using all rounds if necessary
            selected_rounds = all_rounds[:matches_per_team]
            selected_round_info = [(i+1, round_matches) for i, round_matches in enumerate(selected_rounds)]
        else:
            # Select first N clean rounds
            selected_round_info = clean_rounds[:matches_per_team]
        
        logger.info(f"Selected {len(selected_round_info)} rounds for the tournament")
        
        # Create matches from selected rounds
        matches_created = 0
        cross_parent_matches = 0
        same_parent_matches = 0
        team_match_counts = {team.team.id: 0 for team in teams}
        
        for round_num, round_matches in selected_round_info:
            logger.info(f"Creating matches for Round {round_num}:")
            
            for team1, team2 in round_matches:
                match = Match.objects.create(
                    tournament=self.tournament,
                    round=round_obj,
                    team1=team1.team,
                    team2=team2.team,
                    status="pending",
                    time_limit_minutes=self.tournament.default_time_limit_minutes
                )
                matches_created += 1
                
                # Update team match counts
                team_match_counts[team1.team.id] += 1
                team_match_counts[team2.team.id] += 1
                
                # Check if this is a forbidden pair
                is_forbidden = (team1.team.id, team2.team.id) in forbidden_pairs
                if is_forbidden:
                    same_parent_matches += 1
                    pairing_type = "⚠️ SAME-PARENT"
                else:
                    cross_parent_matches += 1
                    pairing_type = "✅ CROSS-PARENT"
                
                # Log parent team info for verification
                parent1 = team1.team.parent_team.name if team1.team.parent_team else "None"
                parent2 = team2.team.parent_team.name if team2.team.parent_team else "None"
                logger.info(f"  Match {match.id}: {team1.team.name} (parent: {parent1}) vs {team2.team.name} (parent: {parent2}) - {pairing_type}")
        
        # Log the final distribution
        logger.info(f"Smart Robin Results:")
        logger.info(f"  Total matches created: {matches_created}")
        logger.info(f"  Cross-parent matches: {cross_parent_matches} ✅")
        logger.info(f"  Same-parent matches: {same_parent_matches} ⚠️")
        
        logger.info(f"Match distribution per team:")
        all_teams_satisfied = True
        for team in teams:
            actual_matches = team_match_counts[team.team.id]
            parent_name = team.team.parent_team.name if team.team.parent_team else "None"
            status = "✅" if actual_matches == matches_per_team else "❌"
            if actual_matches != matches_per_team:
                all_teams_satisfied = False
            logger.info(f"  {team.team.name} (parent: {parent_name}): {actual_matches}/{matches_per_team} matches {status}")
        
        if all_teams_satisfied:
            logger.info("✅ Perfect distribution: All teams have exactly the target number of matches!")
        else:
            logger.warning("❌ Uneven distribution detected!")
        
        return matches_created
        
    def _generate_swiss_matches(self, teams, round_obj):
        """Generate Swiss system matches for the first round."""
        from matches.models import Match
        
        logger.info(f"Generating Swiss matches for {len(teams)} teams")
        
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
                status="pending",
                time_limit_minutes=self.tournament.default_time_limit_minutes
            )
            matches_created += 1
            logger.debug(f"Created match: {teams_copy[i].team} vs {teams_copy[i + 1].team}")
            
        # Handle odd number of teams (bye)
        if len(teams_copy) % 2 == 1:
            bye_team = teams_copy[-1]
            bye_team.received_bye_in_round = round_obj.number_in_stage
            bye_team.save()
            logger.debug(f"{bye_team.team} receives a bye")
            
        logger.info(f"Created {matches_created} Swiss matches")
        return matches_created
        
    def _generate_smart_swiss_matches(self, teams, round_obj):
        """Generate Smart Swiss system matches for the first round."""
        from matches.models import Match
        from .swiss_algorithms import generate_smart_swiss_round
        
        logger.info(f"Generating Smart Swiss matches for {len(teams)} teams")
        
        # For first round of Smart Swiss, we can use random pairing like regular Swiss
        # The Smart Swiss algorithm is used for subsequent rounds
        teams_copy = teams.copy()
        random.shuffle(teams_copy)  # Random pairing for first round
        
        matches_created = 0
        for i in range(0, len(teams_copy) - 1, 2):
            match = Match.objects.create(
                tournament=self.tournament,
                round=round_obj,
                stage=self,  # Important: set the stage for multi-stage tournaments
                team1=teams_copy[i].team,
                team2=teams_copy[i + 1].team,
                status="pending",
                time_limit_minutes=self.tournament.default_time_limit_minutes
            )
            matches_created += 1
            logger.debug(f"Created Smart Swiss match: {teams_copy[i].team} vs {teams_copy[i + 1].team}")
            
        # Handle odd number of teams (bye)
        if len(teams_copy) % 2 == 1:
            bye_team = teams_copy[-1]
            bye_team.received_bye_in_round = round_obj.number_in_stage
            bye_team.save()
            logger.debug(f"{bye_team.team} receives a bye in Smart Swiss")
            
        logger.info(f"Created {matches_created} Smart Swiss matches")
        return matches_created
        
    def _generate_wtf_matches(self, teams, round_obj):
        """Generate WTF (πετΑ Index) system matches for the first round."""
        from matches.models import Match
        import random
        
        logger.info(f"Generating WTF matches for {len(teams)} teams")
        
        # For first round of WTF, we use random pairing like Swiss
        # The WTF πετΑ Index algorithm is used for subsequent rounds
        teams_copy = teams.copy()
        random.shuffle(teams_copy)  # Random pairing for first round
        
        matches_created = 0
        for i in range(0, len(teams_copy) - 1, 2):
            match = Match.objects.create(
                tournament=self.tournament,
                round=round_obj,
                stage=self,  # Important: set the stage for multi-stage tournaments
                team1=teams_copy[i].team,
                team2=teams_copy[i + 1].team,
                status="pending",
                time_limit_minutes=self.tournament.default_time_limit_minutes
            )
            matches_created += 1
            logger.debug(f"Created WTF match: {teams_copy[i].team} vs {teams_copy[i + 1].team}")
            
        # Handle odd number of teams (bye)
        if len(teams_copy) % 2 == 1:
            bye_team = teams_copy[-1]
            # Note: bye handling for multi-stage tournaments may need special logic
            logger.info(f"{bye_team.team} receives a bye in WTF round 1")
        
        logger.info(f"Created {matches_created} WTF matches")
        return matches_created
        
    def _generate_knockout_matches(self, teams, round_obj):
        """Generate knockout matches with proper bracket structure."""
        from matches.models import Match
        
        logger.info(f"Generating knockout matches for {len(teams)} teams")
        
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
                status="pending",
                time_limit_minutes=self.tournament.default_time_limit_minutes
            )
            matches_created += 1
            logger.debug(f"Created match: {teams_copy[i].team} vs {teams_copy[i + 1].team}")
            
        # Handle odd number of teams (bye to next round)
        if len(teams_copy) % 2 == 1:
            bye_team = teams_copy[-1]
            logger.debug(f"{bye_team.team} advances with a bye")
            
        logger.info(f"Created {matches_created} knockout matches")
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
        unique_together = ("tournament", "stage", "number_in_stage")
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


# Import partnership tracking models and mêlée player stats
from .partnership_models import MeleePartnership, MeleeShuffleHistory, MeleePlayerStats
