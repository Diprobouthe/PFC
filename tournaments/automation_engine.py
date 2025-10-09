# automation_engine.py - Complete Tournament Automation System Rebuild

import logging
import random
from django.db import transaction
from django.db.models import Q, Count
from .models import Tournament, TournamentTeam, Round, Stage
from matches.models import Match

logger = logging.getLogger("tournaments")

class TournamentEngine:
    """Main tournament automation engine"""
    
    def __init__(self, tournament):
        self.tournament = tournament
        self.current_stage = self.get_current_stage()
        
    def process_automation(self):
        """Main automation entry point with comprehensive safeguards"""
        from django.db import transaction
        
        try:
            with transaction.atomic():
                # Refresh tournament data to get latest status
                self.tournament.refresh_from_db()
                current_status = getattr(self.tournament, 'automation_status', 'idle')
                
                # Safeguard 1: Check if automation is already running
                if current_status != 'idle':
                    logger.info(f"🔒 Tournament {self.tournament.id} automation already running (status: {current_status}). Skipping.")
                    return True
                
                logger.info(f"🚀 Processing automation for tournament {self.tournament.id}")
                
                # Set status to processing with atomic update
                updated = Tournament.objects.filter(
                    id=self.tournament.id,
                    automation_status='idle'
                ).update(automation_status='processing')
                
                if updated == 0:
                    logger.info(f"🔒 Tournament {self.tournament.id} status changed by another process. Skipping.")
                    return True
                
                # Refresh to get updated status
                self.tournament.refresh_from_db()
                
                # Safeguard 2: Double-check we have processing status
                if self.tournament.automation_status != 'processing':
                    logger.warning(f"⚠️ Tournament {self.tournament.id} status not 'processing' after update. Aborting.")
                    return False
                
                # Determine what action to take
                result = True
                action_taken = "none"
                
                # Check if tournament is complete
                if self.is_tournament_complete():
                    result = self.complete_tournament()
                    action_taken = "complete_tournament"
                # Check if current stage is complete
                elif self.is_current_stage_complete():
                    result = self.advance_to_next_stage()
                    action_taken = "advance_stage"
                # Check if we should generate next round
                elif self.should_generate_next_round():
                    result = self.generate_next_round()
                    action_taken = "generate_round"
                else:
                    logger.debug("No automation action needed")
                    action_taken = "none"
                
                # Always reset status to idle after processing
                self.tournament.automation_status = "idle"
                self.tournament.save()
                
                logger.info(f"✅ Automation completed for tournament {self.tournament.id} (action: {action_taken}), status reset to idle")
                return result
                
        except Exception as e:
            # Ensure status is reset even on error
            try:
                self.tournament.refresh_from_db()
                if self.tournament.automation_status == 'processing':
                    self.tournament.automation_status = "idle"
                    self.tournament.save()
            except:
                pass
            
            logger.error(f"❌ Automation failed for tournament {self.tournament.id}, status reset to idle for retry")
            return self.handle_automation_error(e)
    
    def get_current_stage(self):
        """Get the current active stage"""
        # Find stage with active teams
        stages = Stage.objects.filter(tournament=self.tournament).order_by('stage_number')
        
        for stage in stages:
            active_teams = TournamentTeam.objects.filter(
                tournament=self.tournament,
                current_stage_number=stage.stage_number,
                is_active=True
            ).count()
            
            if active_teams > 0:
                logger.debug(f"Current stage: {stage.stage_number} ({stage.name}) with {active_teams} teams")
                return stage
        
        # Fallback to first stage
        first_stage = stages.first()
        if first_stage:
            logger.debug(f"Fallback to first stage: {first_stage.stage_number}")
            return first_stage
        
        logger.error(f"No stages found for tournament {self.tournament.id}")
        return None
    
    def is_current_stage_complete(self):
        """Check if all rounds in current stage are complete"""
        if not self.current_stage:
            return False
            
        # Get all rounds for this stage
        stage_rounds = Round.objects.filter(
            tournament=self.tournament,
            stage=self.current_stage
        ).order_by('number')
        
        required_rounds = self.current_stage.num_rounds_in_stage
        logger.debug(f"Stage {self.current_stage.stage_number}: {stage_rounds.count()}/{required_rounds} rounds exist")
        
        # Check if we have all required rounds
        if stage_rounds.count() < required_rounds:
            logger.debug(f"Stage incomplete: only {stage_rounds.count()}/{required_rounds} rounds exist")
            return False
        
        # Check if all rounds are complete
        for round_obj in stage_rounds:
            if not self.is_round_complete(round_obj):
                logger.debug(f"Round {round_obj.number} in stage {self.current_stage.stage_number} is not complete")
                return False
        
        logger.info(f"✅ Stage {self.current_stage.stage_number} is complete ({required_rounds} rounds)")
        return True
    
    def is_round_complete(self, round_obj):
        """Check if all matches in a round are complete"""
        round_matches = Match.objects.filter(
            tournament=self.tournament,
            round=round_obj
        )
        
        total_matches = round_matches.count()
        completed_matches = round_matches.filter(status="completed").count()
        
        logger.debug(f"Round {round_obj.number}: {completed_matches}/{total_matches} matches complete")
        
        # Round is complete if:
        # 1. There are matches in the round
        # 2. All matches are completed
        is_complete = (total_matches > 0 and completed_matches == total_matches)
        
        if is_complete and not round_obj.is_complete:
            # Mark the round as complete in the database
            round_obj.is_complete = True
            round_obj.save()
            
            # Update tournament's current round number
            if not self.tournament.current_round_number or self.tournament.current_round_number < round_obj.number:
                self.tournament.current_round_number = round_obj.number
                self.tournament.save()
                logger.info(f"✅ Updated tournament current_round_number to {round_obj.number}")
            
            logger.info(f"✅ Marked Round {round_obj.number} as complete")
        
        return is_complete
    
    def should_generate_next_round(self):
        """Determine if we should generate the next round"""
        if not self.current_stage:
            return False
        
        # FIXED: Check if current stage is complete first
        if self.is_current_stage_complete():
            logger.debug(f"Stage {self.current_stage.stage_number} is complete, should advance to next stage instead")
            return False
            
        current_round = self.tournament.current_round_number or 0
        
        # Check if current round exists and is complete
        if current_round > 0:
            current_round_obj = Round.objects.filter(
                tournament=self.tournament,
                stage=self.current_stage,
                number=current_round
            ).first()
            
            if current_round_obj and not self.is_round_complete(current_round_obj):
                logger.debug(f"Current round {current_round} is not complete yet")
                return False
        
        # Check if we've reached the maximum rounds for this stage
        next_round_num = current_round + 1
        if next_round_num > self.current_stage.num_rounds_in_stage:
            logger.debug(f"Stage {self.current_stage.stage_number} has reached max rounds ({self.current_stage.num_rounds_in_stage})")
            return False
        
        # Check if next round already exists
        next_round_obj = Round.objects.filter(
            tournament=self.tournament,
            stage=self.current_stage,
            number=next_round_num
        ).first()
        
        if next_round_obj:
            existing_matches = Match.objects.filter(
                tournament=self.tournament,
                round=next_round_obj
            ).count()
            
            if existing_matches > 0:
                logger.debug(f"Round {next_round_num} already exists with {existing_matches} matches")
                return False
        
        logger.debug(f"✅ Should generate round {next_round_num}")
        return True
    
    def is_tournament_complete(self):
        """Check if tournament is completely finished"""
        # Tournament is complete if we're in the final stage and it's complete
        final_stage = Stage.objects.filter(tournament=self.tournament).order_by('-stage_number').first()
        
        if not final_stage:
            return False
            
        # Check if final stage is complete and has only 1 qualifier (winner)
        if (self.current_stage and 
            self.current_stage.stage_number == final_stage.stage_number and
            self.is_current_stage_complete() and
            final_stage.num_qualifiers == 1):
            
            logger.info(f"🏆 Tournament {self.tournament.id} is complete")
            return True
            
        return False
    
    def advance_to_next_stage(self):
        """Advance teams to next stage with comprehensive safeguards"""
        try:
            with transaction.atomic():
                logger.info(f"🔄 Advancing from stage {self.current_stage.stage_number}")
                
                # Safeguard 1: Verify current stage is actually complete
                if not self.is_current_stage_complete():
                    logger.warning(f"⚠️ Stage {self.current_stage.stage_number} is not complete - cannot advance")
                    return False
                
                # Get next stage
                next_stage = self.get_next_stage()
                if not next_stage:
                    logger.info(f"🏁 No next stage found - tournament should be complete")
                    return self.complete_tournament()
                
                # Safeguard 2: Check if next stage already has active teams
                existing_teams = TournamentTeam.objects.filter(
                    tournament=self.tournament,
                    current_stage_number=next_stage.stage_number,
                    is_active=True
                ).count()
                
                if existing_teams > 0:
                    logger.warning(f"🔒 Stage {next_stage.stage_number} already has {existing_teams} active teams - skipping advancement")
                    return True
                
                # Get qualifiers from current stage
                qualifiers = self.get_stage_qualifiers(self.current_stage)
                num_qualifiers = len(qualifiers)
                
                # Safeguard 3: Verify we have the expected number of qualifiers
                expected_qualifiers = self.current_stage.num_qualifiers
                if num_qualifiers != expected_qualifiers:
                    logger.warning(f"⚠️ Expected {expected_qualifiers} qualifiers but got {num_qualifiers}")
                    # Continue with what we have, but log the discrepancy
                
                logger.info(f"📊 Stage {self.current_stage.stage_number} qualifiers ({num_qualifiers}): {[q.team.name for q in qualifiers]}")
                
                # Safeguard 4: Ensure we have enough teams for next stage
                if num_qualifiers < 2:
                    logger.error(f"❌ Not enough qualifiers ({num_qualifiers}) for next stage")
                    return self.complete_tournament()
                
                # Deactivate non-qualifying teams
                non_qualifiers = TournamentTeam.objects.filter(
                    tournament=self.tournament,
                    current_stage_number=self.current_stage.stage_number,
                    is_active=True
                ).exclude(id__in=[q.id for q in qualifiers])
                
                for team_tt in non_qualifiers:
                    team_tt.is_active = False
                    team_tt.save()
                    logger.info(f"❌ Eliminated: {team_tt.team.name}")
                
                # Advance qualifiers to next stage
                for team_tt in qualifiers:
                    team_tt.current_stage_number = next_stage.stage_number
                    team_tt.save()
                    logger.info(f"✅ Advanced: {team_tt.team.name} to stage {next_stage.stage_number}")
                
                # Update tournament current stage tracking
                self.current_stage = next_stage
                
                # Generate first round of next stage
                next_round_number = self._get_next_overall_round_number()
                return self.generate_stage_round(next_stage, qualifiers, next_round_number)
                
        except Exception as e:
            logger.exception(f"Error advancing to next stage: {e}")
            raise
    
    def _get_next_overall_round_number(self):
        """Get the next overall round number for the tournament"""
        current_round = self.tournament.current_round_number or 0
        return current_round + 1
    
    def get_stage_qualifiers(self, stage):
        """Get top N teams from stage based on admin-configured num_qualifiers"""
        # Get all active teams in this stage
        teams = TournamentTeam.objects.filter(
            tournament=self.tournament,
            current_stage_number=stage.stage_number,
            is_active=True
        )
        
        # Rank teams by wins, then by tiebreakers
        ranked_teams = teams.order_by(
            '-swiss_points',      # Primary: most wins
            '-buchholz_score',    # Secondary: strength of schedule  
            'id'                  # Tertiary: consistent tiebreaker
        )
        
        # Return exactly the number of qualifiers configured by admin
        num_qualifiers = stage.num_qualifiers
        qualifiers = list(ranked_teams[:num_qualifiers])
        
        logger.info(f"🎯 Stage {stage.stage_number} configured for {num_qualifiers} qualifiers")
        for i, team_tt in enumerate(qualifiers, 1):
            logger.info(f"  #{i}: {team_tt.team.name} ({team_tt.swiss_points} pts)")
        
        return qualifiers
    
    def get_next_stage(self):
        """Get the next stage after current stage"""
        if not self.current_stage:
            return None
            
        next_stage = Stage.objects.filter(
            tournament=self.tournament,
            stage_number__gt=self.current_stage.stage_number
        ).order_by('stage_number').first()
        
        if next_stage:
            logger.debug(f"Next stage: {next_stage.stage_number} ({next_stage.name})")
        else:
            logger.debug("No next stage found")
            
        return next_stage
    
    def generate_next_round(self):
        """Generate next round within current stage with comprehensive safeguards"""
        if not self.current_stage:
            logger.error("No current stage found")
            return False
            
        # Determine next round number
        current_round = self.tournament.current_round_number or 0
        next_round_num = current_round + 1
        
        logger.info(f"🎲 Generating round {next_round_num} for stage {self.current_stage.stage_number}")
        
        # Safeguard 1: Check if this round already exists
        existing_round = Round.objects.filter(
            tournament=self.tournament,
            stage=self.current_stage,
            number=next_round_num
        ).first()
        
        if existing_round:
            existing_matches = Match.objects.filter(
                tournament=self.tournament,
                round=existing_round
            ).count()
            
            if existing_matches > 0:
                logger.warning(f"🔒 Round {next_round_num} already exists with {existing_matches} matches - skipping generation")
                return True
        
        # Safeguard 2: Check if we've exceeded the maximum rounds for this stage
        if hasattr(self.current_stage, 'num_rounds_in_stage') and self.current_stage.num_rounds_in_stage:
            current_stage_rounds = Round.objects.filter(
                tournament=self.tournament,
                stage=self.current_stage
            ).count()
            
            if current_stage_rounds >= self.current_stage.num_rounds_in_stage:
                logger.info(f"🏁 Stage {self.current_stage.stage_number} has reached maximum rounds ({self.current_stage.num_rounds_in_stage})")
                return True
        
        # Safeguard 3: Check if all matches in current round are actually completed
        if current_round > 0:
            current_round_matches = Match.objects.filter(
                tournament=self.tournament,
                round__number=current_round
            )
            
            incomplete_matches = current_round_matches.exclude(status='completed').count()
            if incomplete_matches > 0:
                logger.warning(f"⚠️ Current round {current_round} has {incomplete_matches} incomplete matches - cannot generate next round")
                return False
        
        # Get active teams in current stage
        active_teams = list(TournamentTeam.objects.filter(
            tournament=self.tournament,
            current_stage_number=self.current_stage.stage_number,
            is_active=True
        ).order_by('-swiss_points', '-buchholz_score', 'id'))
        
        if len(active_teams) < 2:
            logger.warning(f"Not enough teams ({len(active_teams)}) for round generation")
            return self.complete_tournament()
        
        # Calculate expected number of matches for this round
        expected_matches = len(active_teams) // 2
        
        # Generate round based on stage format
        result = self.generate_stage_round(self.current_stage, active_teams, next_round_num)
        
        if result:
            # Verify we created the expected number of matches
            created_matches = Match.objects.filter(
                tournament=self.tournament,
                round__stage=self.current_stage,
                round__number=next_round_num
            ).count()
            
            logger.info(f"✅ Created {created_matches}/{expected_matches} matches for round {next_round_num}")
            
            if created_matches != expected_matches:
                logger.warning(f"⚠️ Expected {expected_matches} matches but created {created_matches}")
        
        return result
    
    def generate_stage_round(self, stage, teams, round_number):
        """Generate round based on stage format"""
        try:
            with transaction.atomic():
                # Create round object
                round_obj, created = Round.objects.get_or_create(
                    tournament=self.tournament,
                    stage=stage,
                    number_in_stage=round_number,
                    defaults={
                        'number': self._get_next_overall_round_number(),
                        'is_complete': False
                    }
                )
                
                if created:
                    logger.info(f"📝 Created round {round_number} for stage {stage.stage_number}")
                
                # Generate matches based on format
                if stage.format == 'smart_swiss':
                    # Use the specialized Smart Swiss algorithm
                    from .swiss_algorithms import generate_smart_swiss_round
                    matches_created = generate_smart_swiss_round(self.tournament, stage)
                elif stage.format in ['swiss_system', 'swiss']:
                    generator = SwissGenerator(self.tournament, stage, round_obj)
                    matches_created = generator.generate_matches(teams)
                elif stage.format == 'knockout':
                    generator = KnockoutGenerator(self.tournament, stage, round_obj)
                    matches_created = generator.generate_matches(teams)
                elif stage.format == 'round_robin':
                    # Check if this is incomplete round robin
                    if hasattr(stage, 'num_matches_per_team') and stage.num_matches_per_team:
                        generator = IncompleteRoundRobinGenerator(self.tournament, stage, round_obj)
                    else:
                        generator = RoundRobinGenerator(self.tournament, stage, round_obj)
                    matches_created = generator.generate_matches(teams)
                else:
                    logger.error(f"Unknown stage format: {stage.format}")
                    return False
                
                if matches_created > 0:
                    # Update tournament state
                    self.tournament.current_round_number = round_number
                    self.tournament.automation_status = "idle"
                    self.tournament.save()
                    
                    logger.info(f"✅ Generated {matches_created} matches for round {round_number}")
                    return True
                else:
                    logger.warning(f"No matches created for round {round_number}")
                    return False
                    
        except Exception as e:
            logger.exception(f"Error generating stage round: {e}")
            raise
    
    def complete_tournament(self):
        """Mark tournament as completed and perform cleanup"""
        try:
            with transaction.atomic():
                self.tournament.automation_status = "completed"
                self.tournament.current_round_number = None
                self.tournament.save()
                
                logger.info(f"🏆 Tournament {self.tournament.id} marked as completed")
                
                # Assign tournament badges if available
                try:
                    from .completion import check_and_complete_tournament
                    check_and_complete_tournament(self.tournament)
                    logger.info(f"🏅 Tournament badges assigned")
                except Exception as e:
                    logger.exception(f"Error assigning badges: {e}")
                
                # Restore players to original teams if this is a Mêlée tournament
                if self.tournament.is_melee:
                    try:
                        self._restore_melee_players()
                        logger.info(f"👥 Players restored to original teams")
                    except Exception as e:
                        logger.exception(f"Error restoring players: {e}")
                    
                    # Note: Mêlée teams are kept to preserve tournament history and matches
                    # They will be hidden from UI instead of deleted
                    logger.info(f"🏆 Mêlée teams preserved for tournament history")
                
                return True
                
        except Exception as e:
            logger.exception(f"Error completing tournament: {e}")
            return False
    
    def _restore_melee_players(self):
        """Restore players from Mêlée teams back to their original teams"""
        from tournaments.models import MeleePlayer
        from teams.models import Player
        
        # Get all Mêlée players for this tournament
        melee_players = MeleePlayer.objects.filter(tournament=self.tournament)
        restored_count = 0
        
        for melee_player in melee_players:
            try:
                # Get the actual player object
                player = melee_player.player
                original_team = melee_player.original_team
                
                if player and original_team:
                    # Move player back to original team
                    player.team = original_team
                    player.save()
                    
                    logger.info(f"Restored player {player.name} from {player.team.name if player.team else 'None'} back to {original_team.name}")
                    restored_count += 1
                    
            except Exception as e:
                logger.error(f"Error restoring player {melee_player.player.name}: {e}")
        
        logger.info(f"Restored {restored_count} players to their original teams for tournament {self.tournament.name}")
    
    
    def handle_automation_error(self, error):
        """Handle automation errors without permanent error state"""
        try:
            # Log the error with full context
            logger.error(f"🚨 Automation error in tournament {self.tournament.id}: {error}")
            logger.exception("Full error details:")
            
            # Status is already set to idle in the calling method
            # Never set to permanent "error" or "needs_attention" state
            logger.info(f"⚠️ Tournament {self.tournament.id} status remains 'idle' - automation can be retried")
            
            return False
            
        except Exception as e:
            logger.exception(f"Error in error handler: {e}")
            return False
    
    def _get_next_overall_round_number(self):
        """Get the next overall round number for the tournament"""
        last_round = Round.objects.filter(tournament=self.tournament).order_by('-number').first()
        return (last_round.number + 1) if last_round else 1


class MatchGenerator:
    """Base class for match generators"""
    
    def __init__(self, tournament, stage, round_obj):
        self.tournament = tournament
        self.stage = stage
        self.round_obj = round_obj
    
    def generate_matches(self, teams):
        """Override in subclasses"""
        raise NotImplementedError
    
    def create_match(self, team1_tt, team2_tt):
        """Create a match between two teams"""
        match = Match.objects.create(
            tournament=self.tournament,
            round=self.round_obj,
            stage=self.stage,
            team1=team1_tt.team,
            team2=team2_tt.team,
            status="pending"
        )
        
        # Update opponents played
        team1_tt.opponents_played.add(team2_tt.team)
        team2_tt.opponents_played.add(team1_tt.team)
        
        logger.info(f"🥎 Created match: {team1_tt.team.name} vs {team2_tt.team.name}")
        return match


class SwissGenerator(MatchGenerator):
    """Swiss system match generator with fallback strategies"""
    
    def generate_matches(self, teams):
        """Generate Swiss pairings with multiple fallback strategies"""
        logger.info(f"🇨🇭 Generating Swiss pairings for {len(teams)} teams")
        
        # Handle bye if odd number of teams
        bye_team = None
        if len(teams) % 2 != 0:
            bye_team = self.assign_bye(teams)
            teams = [t for t in teams if t != bye_team]
        
        # Try different pairing strategies
        matches_created = 0
        
        # Strategy 1: Ideal Swiss pairing (no repeats)
        pairings = self.try_ideal_pairing(teams)
        if pairings:
            logger.info("✅ Using ideal Swiss pairing (no repeats)")
            matches_created = self.create_matches_from_pairings(pairings)
        else:
            # Strategy 2: Allow minimal repeats
            pairings = self.try_minimal_repeats(teams)
            if pairings:
                logger.warning("⚠️ Using minimal repeat pairing strategy")
                matches_created = self.create_matches_from_pairings(pairings)
            else:
                # Strategy 3: Random pairing (last resort)
                logger.warning("🎲 Using random pairing (last resort)")
                matches_created = self.random_pairing(teams)
        
        return matches_created
    
    def assign_bye(self, teams):
        """Assign bye to lowest-ranked team that hasn't had one"""
        for team_tt in reversed(teams):  # Start from lowest ranked
            if team_tt.received_bye_in_round is None:
                team_tt.received_bye_in_round = self.round_obj.number
                team_tt.swiss_points += 3  # Bye points
                team_tt.save()
                
                logger.info(f"🚫 Bye assigned to {team_tt.team.name}")
                return team_tt
        
        # All teams have had byes - assign to last team anyway
        bye_team = teams[-1]
        bye_team.received_bye_in_round = self.round_obj.number
        bye_team.swiss_points += 3
        bye_team.save()
        
        logger.warning(f"🚫 Bye assigned to {bye_team.team.name} (all teams had previous byes)")
        return bye_team
    
    def try_ideal_pairing(self, teams):
        """Try to pair teams without any repeats"""
        # Group teams by points
        point_groups = self.group_teams_by_points(teams)
        
        all_pairings = []
        unpaired_teams = []
        
        for point_group in point_groups:
            group_pairings, group_unpaired = self.pair_within_group_no_repeats(point_group)
            all_pairings.extend(group_pairings)
            unpaired_teams.extend(group_unpaired)
        
        # Try to pair remaining teams across point groups
        if unpaired_teams:
            cross_pairings, still_unpaired = self.pair_across_groups_no_repeats(unpaired_teams)
            all_pairings.extend(cross_pairings)
            
            if still_unpaired:
                logger.debug(f"Could not pair {len(still_unpaired)} teams without repeats")
                return None
        
        return all_pairings
    
    def try_minimal_repeats(self, teams):
        """Allow minimal repeats if necessary"""
        # Simple approach: pair sequentially, allowing repeats
        pairings = []
        available_teams = teams.copy()
        
        while len(available_teams) >= 2:
            team1 = available_teams.pop(0)
            
            # Try to find best opponent (fewest previous meetings)
            best_opponent = None
            min_meetings = float('inf')
            
            for team2 in available_teams:
                meetings = self.count_previous_meetings(team1, team2)
                if meetings < min_meetings:
                    min_meetings = meetings
                    best_opponent = team2
            
            if best_opponent:
                available_teams.remove(best_opponent)
                pairings.append((team1, best_opponent))
                
                if min_meetings > 0:
                    logger.warning(f"⚠️ Repeat pairing: {team1.team.name} vs {best_opponent.team.name} ({min_meetings} previous meetings)")
        
        return pairings
    
    def random_pairing(self, teams):
        """Last resort: random pairing"""
        available_teams = teams.copy()
        random.shuffle(available_teams)
        
        matches_created = 0
        while len(available_teams) >= 2:
            team1 = available_teams.pop()
            team2 = available_teams.pop()
            
            self.create_match(team1, team2)
            matches_created += 1
        
        return matches_created
    
    def group_teams_by_points(self, teams):
        """Group teams by Swiss points"""
        point_groups = {}
        for team in teams:
            points = team.swiss_points
            if points not in point_groups:
                point_groups[points] = []
            point_groups[points].append(team)
        
        # Return groups in descending point order
        return [point_groups[points] for points in sorted(point_groups.keys(), reverse=True)]
    
    def pair_within_group_no_repeats(self, group):
        """Pair teams within same point group, avoiding repeats"""
        pairings = []
        unpaired = group.copy()
        
        while len(unpaired) >= 2:
            team1 = unpaired.pop(0)
            opponent_found = False
            
            for i, team2 in enumerate(unpaired):
                if not self.have_played_before(team1, team2):
                    unpaired.pop(i)
                    pairings.append((team1, team2))
                    opponent_found = True
                    break
            
            if not opponent_found:
                # Can't pair team1 without repeats
                break
        
        return pairings, unpaired
    
    def pair_across_groups_no_repeats(self, teams):
        """Try to pair remaining teams across point groups"""
        pairings = []
        unpaired = teams.copy()
        
        while len(unpaired) >= 2:
            team1 = unpaired.pop(0)
            opponent_found = False
            
            for i, team2 in enumerate(unpaired):
                if not self.have_played_before(team1, team2):
                    unpaired.pop(i)
                    pairings.append((team1, team2))
                    opponent_found = True
                    break
            
            if not opponent_found:
                break
        
        return pairings, unpaired
    
    def have_played_before(self, team1_tt, team2_tt):
        """Check if two teams have played before"""
        return team2_tt.team in team1_tt.opponents_played.all()
    
    def count_previous_meetings(self, team1_tt, team2_tt):
        """Count how many times two teams have played"""
        # Simple check - could be enhanced to count actual meetings
        return 1 if self.have_played_before(team1_tt, team2_tt) else 0
    
    def create_matches_from_pairings(self, pairings):
        """Create matches from list of team pairings"""
        matches_created = 0
        for team1_tt, team2_tt in pairings:
            self.create_match(team1_tt, team2_tt)
            matches_created += 1
        
        return matches_created


class KnockoutGenerator(MatchGenerator):
    """Knockout tournament match generator"""
    
    def generate_matches(self, teams):
        """Generate knockout matches"""
        logger.info(f"🏆 Generating knockout matches for {len(teams)} teams")
        
        # Handle bye if odd number of teams
        if len(teams) % 2 != 0:
            bye_team = teams[-1]  # Give bye to lowest seed
            bye_team.received_bye_in_round = self.round_obj.number
            bye_team.save()
            teams = teams[:-1]
            logger.info(f"🚫 Knockout bye assigned to {bye_team.team.name}")
        
        # Pair teams sequentially (seeded)
        matches_created = 0
        for i in range(0, len(teams), 2):
            if i + 1 < len(teams):
                team1 = teams[i]
                team2 = teams[i + 1]
                self.create_match(team1, team2)
                matches_created += 1
        
        return matches_created


class RoundRobinGenerator(MatchGenerator):
    """Round robin tournament match generator"""
    
    def generate_matches(self, teams):
        """Generate round robin matches"""
        logger.info(f"🔄 Generating round robin matches for {len(teams)} teams")
        
        # In round robin, typically all matches are generated at once
        # This is a simplified version - could be enhanced for multi-round round robin
        matches_created = 0
        
        for i in range(len(teams)):
            for j in range(i + 1, len(teams)):
                team1 = teams[i]
                team2 = teams[j]
                
                if not self.have_played_before(team1, team2):
                    self.create_match(team1, team2)
                    matches_created += 1
        
        return matches_created
    
    def have_played_before(self, team1_tt, team2_tt):
        """Check if teams have played in this tournament"""
        return team2_tt.team in team1_tt.opponents_played.all()


class IncompleteRoundRobinGenerator(MatchGenerator):
    """Incomplete Round Robin tournament match generator with subteam pairing preferences"""
    
    def generate_matches(self, teams):
        """Generate incomplete round robin matches with parent team preferences"""
        logger.info(f"🔄 Generating incomplete round robin matches for {len(teams)} teams")
        
        # Get the number of matches per team from the stage
        matches_per_team = self.stage.num_matches_per_team
        if not matches_per_team:
            logger.error("num_matches_per_team not specified for incomplete round robin")
            return 0
        
        logger.info(f"Target: {matches_per_team} matches per team")
        
        # Generate all possible pairings with penalties
        all_pairings = self._generate_all_pairings_with_penalties(teams)
        
        # Select optimal pairings using the penalty system
        selected_pairings = self._select_optimal_pairings(all_pairings, teams, matches_per_team)
        
        # Create matches from selected pairings
        matches_created = 0
        for team1_tt, team2_tt, penalty in selected_pairings:
            if not self.have_played_before(team1_tt, team2_tt):
                self.create_match(team1_tt, team2_tt)
                matches_created += 1
                logger.debug(f"Created match: {team1_tt.team.name} vs {team2_tt.team.name} (penalty: {penalty})")
        
        logger.info(f"✅ Created {matches_created} matches for incomplete round robin")
        return matches_created
    
    def _generate_all_pairings_with_penalties(self, teams):
        """Generate all possible pairings with parent team penalties"""
        pairings = []
        
        for i in range(len(teams)):
            for j in range(i + 1, len(teams)):
                team1_tt = teams[i]
                team2_tt = teams[j]
                
                # Calculate penalty based on parent teams
                penalty = self._calculate_pairing_penalty(team1_tt.team, team2_tt.team)
                
                pairings.append((team1_tt, team2_tt, penalty))
        
        # Sort by penalty (prefer lower penalties = different parents)
        pairings.sort(key=lambda x: x[2])
        
        logger.debug(f"Generated {len(pairings)} possible pairings")
        return pairings
    
    def _calculate_pairing_penalty(self, team1, team2):
        """Calculate penalty for pairing two teams"""
        # Get parent teams (or the team itself if no parent)
        parent1 = team1.parent_team if team1.parent_team else team1
        parent2 = team2.parent_team if team2.parent_team else team2
        
        # Penalty: 0 if different parents, +1 if same parent
        penalty = 1 if parent1 == parent2 else 0
        
        return penalty
    
    def _select_optimal_pairings(self, all_pairings, teams, matches_per_team):
        """Select optimal pairings to achieve target matches per team"""
        selected_pairings = []
        team_match_counts = {team.team.id: 0 for team in teams}
        
        # Calculate target total matches more carefully
        # For incomplete round robin, we want each team to have exactly matches_per_team matches
        # Total matches = (sum of all team matches) / 2
        total_target_matches = (len(teams) * matches_per_team) // 2
        
        # However, if the number is odd, we need to handle the remainder
        total_team_matches_needed = len(teams) * matches_per_team
        if total_team_matches_needed % 2 == 1:
            # This shouldn't happen in a well-formed tournament, but handle it gracefully
            logger.warning(f"Odd total team matches needed: {total_team_matches_needed}")
            # We'll allow some teams to have one extra match
            total_target_matches = (total_team_matches_needed + 1) // 2
        
        logger.debug(f"Target total matches: {total_target_matches} (from {total_team_matches_needed} team-matches)")
        
        # Greedy selection with penalty preference
        for team1_tt, team2_tt, penalty in all_pairings:
            team1_id = team1_tt.team.id
            team2_id = team2_tt.team.id
            
            # Check if both teams can still play more matches
            if (team_match_counts[team1_id] < matches_per_team and 
                team_match_counts[team2_id] < matches_per_team):
                
                # Select this pairing
                selected_pairings.append((team1_tt, team2_tt, penalty))
                team_match_counts[team1_id] += 1
                team_match_counts[team2_id] += 1
                
                # Stop if we've reached the target number of matches
                if len(selected_pairings) >= total_target_matches:
                    break
        
        # Check if we need to add more matches to satisfy all teams
        # This handles cases where the greedy algorithm doesn't perfectly distribute matches
        teams_needing_matches = [
            team for team in teams 
            if team_match_counts[team.team.id] < matches_per_team
        ]
        
        if teams_needing_matches:
            logger.debug(f"Adding additional matches for {len(teams_needing_matches)} teams")
            
            # Try to pair up teams that need more matches
            while len(teams_needing_matches) >= 2:
                team1_tt = teams_needing_matches[0]
                team2_tt = teams_needing_matches[1]
                
                # Check if this pairing already exists
                pairing_exists = any(
                    (p[0] == team1_tt and p[1] == team2_tt) or 
                    (p[0] == team2_tt and p[1] == team1_tt)
                    for p in selected_pairings
                )
                
                if not pairing_exists:
                    penalty = self._calculate_pairing_penalty(team1_tt.team, team2_tt.team)
                    selected_pairings.append((team1_tt, team2_tt, penalty))
                    team_match_counts[team1_tt.team.id] += 1
                    team_match_counts[team2_tt.team.id] += 1
                    logger.debug(f"Added extra match: {team1_tt.team.name} vs {team2_tt.team.name}")
                
                # Remove teams that now have enough matches
                teams_needing_matches = [
                    team for team in teams_needing_matches
                    if team_match_counts[team.team.id] < matches_per_team
                ]
        
        # Log the selection results
        logger.info(f"Selected {len(selected_pairings)} pairings:")
        cross_parent_matches = sum(1 for _, _, penalty in selected_pairings if penalty == 0)
        same_parent_matches = sum(1 for _, _, penalty in selected_pairings if penalty == 1)
        logger.info(f"  Cross-parent matches: {cross_parent_matches}")
        logger.info(f"  Same-parent matches: {same_parent_matches}")
        
        # Log matches per team
        for team in teams:
            count = team_match_counts[team.team.id]
            logger.debug(f"  {team.team.name}: {count} matches")
        
        return selected_pairings
    
    def have_played_before(self, team1_tt, team2_tt):
        """Check if teams have played in this tournament"""
        return team2_tt.team in team1_tt.opponents_played.all()

