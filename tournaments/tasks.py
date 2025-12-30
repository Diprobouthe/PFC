# tasks.py for tournament automation

import logging
from django.db import transaction
from .models import Tournament, TournamentTeam, Round, Stage # Import Round and Stage
from matches.models import Match
from django.db.models import Q # Import Q for complex queries

logger = logging.getLogger("tournaments")

def generate_next_round_robin_round(tournament):
    logger.info(f"Checking completion status for Round Robin tournament {tournament.id}")
    
    try:
        with transaction.atomic():
            # For Round Robin, all matches are typically generated in round 1.
            # This function checks if all matches are completed.
            all_matches = Match.objects.filter(tournament=tournament)
            total_matches = all_matches.count()
            completed_matches = all_matches.filter(status="completed").count()

            logger.debug(f"Tournament {tournament.id}: Total matches={total_matches}, Completed={completed_matches}")

            if total_matches > 0 and completed_matches == total_matches:
                logger.info(f"All {total_matches} matches completed for Round Robin tournament {tournament.id}. Marking as completed.")
                tournament.automation_status = "completed"
                tournament.current_round_number = None # Or set to a final round number if applicable
                tournament.save()
            elif total_matches == 0:
                 logger.warning(f"No matches found for Round Robin tournament {tournament.id}. Cannot determine completion.")
                 # Consider setting status to error or completed depending on context
                 tournament.automation_status = "idle" # Reset status, maybe matches weren't generated?
                 tournament.save()
            else:
                logger.info(f"Round Robin tournament {tournament.id} is still ongoing ({completed_matches}/{total_matches} matches completed). No new round to generate.")
                # Ensure status is idle if it was processing
                tournament.automation_status = "idle"
                tournament.save()

    except Exception as e:
        logger.exception(f"Error checking Round Robin completion for tournament {tournament.id}: {e}")
        try:
            tournament.refresh_from_db()
            if tournament.automation_status != "error":
                tournament.automation_status = "error"
                tournament.save()
        except Tournament.DoesNotExist:
            pass
        raise # Re-raise to ensure transaction rollback if needed


def generate_next_swiss_round(tournament, stage=None):
    """
    Generate next Swiss round using the appropriate algorithm.
    Dispatches to Standard Swiss or Smart Swiss based on tournament/stage format.
    """
    from .swiss_algorithms import generate_standard_swiss_round, generate_smart_swiss_round
    
    # Determine which format to use
    if stage:
        format_to_check = stage.format
    else:
        format_to_check = tournament.format
    
    if format_to_check == "smart_swiss":
        logger.info(f"Using Smart Swiss algorithm for tournament {tournament.id}")
        return generate_smart_swiss_round(tournament, stage)
    else:
        # Use Standard Swiss for "swiss", "swiss_system", or any other Swiss variant
        logger.info(f"Using Standard Swiss algorithm for tournament {tournament.id}")
        return generate_standard_swiss_round(tournament, stage)


def generate_next_knockout_round(tournament):
    logger.info(f"Attempting to generate next Knockout round for tournament {tournament.id}")
    
    try:
        with transaction.atomic():
            current_round = tournament.current_round_number
            next_round_num = current_round + 1
            logger.info(f"Current round: {current_round}, generating for round: {next_round_num}")

            # --- 1. Identify Advancing Teams --- 
            advancing_teams_tt = []

            # Get winners from completed matches of the current round - FIXED: Use round__number
            completed_matches = Match.objects.filter(tournament=tournament, round__number=current_round, status="completed")
            for match in completed_matches:
                if match.winner:
                    winner_tt = TournamentTeam.objects.filter(tournament=tournament, team=match.winner).first()
                    if winner_tt and winner_tt.is_active:
                        advancing_teams_tt.append(winner_tt)
                    else:
                         logger.warning(f"Winner team {match.winner.name} not found or inactive in TournamentTeam for match {match.id}. Skipping.")
                else:
                     logger.error(f"Match {match.id} in knockout tournament {tournament.id} has no winner. This should not happen in petanque.")
                     # Set tournament to error - requires admin intervention
                     tournament.automation_status = "error"
                     tournament.save()
                     return

            # Get teams that received a bye in the current round
            bye_teams_tt = TournamentTeam.objects.filter(tournament=tournament, is_active=True, received_bye_in_round=current_round)
            advancing_teams_tt.extend(list(bye_teams_tt))
            
            # Remove duplicates just in case (shouldn't happen with proper logic)
            advancing_teams_tt = list({tt.id: tt for tt in advancing_teams_tt}.values())
            num_advancing = len(advancing_teams_tt)
            logger.debug(f"Advancing teams ({num_advancing}): {[t.team.name for t in advancing_teams_tt]}")

            # --- 2. Check for Tournament Winner --- 
            if num_advancing == 1:
                winner = advancing_teams_tt[0]
                logger.info(f"Tournament {tournament.id} completed. Winner: {winner.team.name}")
                tournament.automation_status = "completed"
                tournament.current_round_number = None # Mark as finished
                tournament.save()
                
                # Assign tournament badges
                try:
                    from .completion import check_and_complete_tournament
                    check_and_complete_tournament(tournament)
                    logger.info(f"Tournament badges assigned for completed tournament {tournament.id}")
                except Exception as e:
                    logger.exception(f"Error assigning badges for completed tournament {tournament.id}: {e}")
                
                return
            elif num_advancing == 0:
                 logger.error(f"No teams advanced to round {next_round_num} for tournament {tournament.id}. This might indicate an issue with match results or bye handling. Setting status to error.")
                 tournament.automation_status = "error"
                 tournament.save()
                 return
            elif num_advancing < 2:
                 logger.error(f"Only {num_advancing} team(s) advanced to round {next_round_num}. Cannot generate matches. Setting status to error.")
                 tournament.automation_status = "error"
                 tournament.save()
                 return

            # --- 3. Handle Bye for Next Round --- 
            bye_team_tt_next_round = None
            teams_to_pair = advancing_teams_tt
            if num_advancing % 2 != 0:
                # Assign bye to a team that hasn't had one, ideally lowest seed/random among lowest
                # Simple approach: assign to the last team after shuffling
                random.shuffle(teams_to_pair)
                bye_assigned = False
                for i in range(num_advancing -1, -1, -1): # Check from end
                    candidate = teams_to_pair[i]
                    # Check if this team has EVER received a bye in this tournament
                    if candidate.received_bye_in_round is None: 
                        bye_team_tt_next_round = teams_to_pair.pop(i) # Remove from pairing list
                        bye_assigned = True
                        break
                
                if bye_assigned:
                    logger.info(f"Assigning Bye to {bye_team_tt_next_round.team.name} in Knockout Round {next_round_num}")
                    bye_team_tt_next_round.received_bye_in_round = next_round_num
                    bye_team_tt_next_round.swiss_points += 3 # Add points even in knockout for consistency?
                    bye_team_tt_next_round.save()
                else:
                    # All advancing teams have had a bye - this is unusual but possible in small tournaments
                    # Assign bye to the last team after shuffle anyway
                    logger.warning(f"Odd number of teams ({num_advancing}) and all have had byes. Assigning bye to {teams_to_pair[-1].team.name} anyway for round {next_round_num}.")
                    bye_team_tt_next_round = teams_to_pair.pop()
                    bye_team_tt_next_round.received_bye_in_round = next_round_num # Mark it again? Or just let them advance?
                    bye_team_tt_next_round.swiss_points += 3
                    bye_team_tt_next_round.save()

            # --- 4. Perform Pairing --- 
            # Shuffle remaining teams for random pairing in knockout
            random.shuffle(teams_to_pair)
            matches_created = []
            
            for i in range(0, len(teams_to_pair), 2):
                if i + 1 < len(teams_to_pair):
                    team1_tt = teams_to_pair[i]
                    team2_tt = teams_to_pair[i+1]
                    logger.info(f"Pairing {team1_tt.team.name} vs {team2_tt.team.name} for knockout round {next_round_num}")
                    match = Match.objects.create(
                        tournament=tournament,
                        round_number=next_round_num,
                        team1=team1_tt.team,
                        team2=team2_tt.team,
                        status="pending",
                        time_limit_minutes=tournament.default_time_limit_minutes
                    )
                    matches_created.append(match)
                    # Update opponents played if needed (less critical in knockout)
                    # team1_tt.opponents_played.add(team2_tt.team)
                    # team2_tt.opponents_played.add(team1_tt.team)
                else:
                    # This should not happen if bye logic is correct
                    logger.error(f"Error during knockout pairing: Odd number of teams ({len(teams_to_pair)}) remaining after bye assignment. Team {teams_to_pair[i].team.name} left over.")
                    raise Exception(f"Pairing failed for knockout tournament {tournament.id}, round {next_round_num}")

            # --- 5. Finalize Round --- 
            if len(matches_created) > 0 or bye_team_tt_next_round:
                tournament.current_round_number = next_round_num
                tournament.automation_status = "idle" # Ready for next check
                tournament.save()
                logger.info(f"Successfully generated {len(matches_created)} matches for Knockout round {next_round_num} in tournament {tournament.id}.")
            else:
                # Should only happen if num_advancing was 1 (winner found) or 0/error
                if tournament.automation_status not in ["completed", "error"]:
                     logger.error(f"No matches created for knockout round {next_round_num} and tournament not completed/errored. Setting status to error.")
                     tournament.automation_status = "error"
                     tournament.save()

    except Exception as e:
        logger.exception(f"Error generating Knockout round {tournament.current_round_number + 1} for tournament {tournament.id}: {e}")
        try:
            tournament.refresh_from_db()
            if tournament.automation_status != "error":
                tournament.automation_status = "error"
                tournament.save()
        except Tournament.DoesNotExist:
            pass
        raise


def generate_next_combo_round(tournament):
    logger.info(f"Checking multi-stage progression for tournament {tournament.id}")
    
    try:
        with transaction.atomic():
            current_round_num = tournament.current_round_number
            if current_round_num is None:
                logger.error(f"Cannot process combo round generation for tournament {tournament.id}: current_round_number is None.")
                tournament.automation_status = "error"
                tournament.save()
                return

            # Find the round object and its associated stage
            try:
                current_round_obj = Round.objects.select_related("stage").get(tournament=tournament, number=current_round_num)
                current_stage = current_round_obj.stage
                if not current_stage:
                     logger.error(f"Round {current_round_num} in multi-stage tournament {tournament.id} is not associated with a stage. Setting status to error.")
                     tournament.automation_status = "error"
                     tournament.save()
                     return
            except Round.DoesNotExist:
                logger.error(f"Round object for round number {current_round_num} not found for tournament {tournament.id}. Setting status to error.")
                tournament.automation_status = "error"
                tournament.save()
                return

            logger.info(f"Current round {current_round_num} is round {current_round_obj.number_in_stage} of stage {current_stage.stage_number} ({current_stage.name}). Stage requires {current_stage.num_rounds_in_stage} rounds.")

            # Check if the completed round was the last one for the current stage
            if current_round_obj.number_in_stage >= current_stage.num_rounds_in_stage:
                logger.info(f"Stage {current_stage.stage_number} ({current_stage.name}) completed for tournament {tournament.id}. Attempting to advance to next stage.")
                # Mark stage as complete (advance_to_next_stage should probably do this)
                # current_stage.is_complete = True
                # current_stage.save()
                
                # Call the method to handle qualification and next stage generation
                tournament.advance_to_next_stage() 
                # advance_to_next_stage should update tournament.automation_status and current_round_number on success/failure/completion
                logger.info(f"advance_to_next_stage called for tournament {tournament.id}. Current status: {tournament.automation_status}")

            else:
                # More rounds remaining within the current stage
                next_round_num_in_stage = current_round_obj.number_in_stage + 1
                next_overall_round_num = current_round_num + 1
                stage_format = current_stage.format
                logger.info(f"Stage {current_stage.stage_number} ongoing. Attempting to generate round {next_round_num_in_stage} (overall {next_overall_round_num}) using format: {stage_format}.")
                
                # --- Generate next round WITHIN the current stage --- 
                # This requires the specific format generators to potentially handle a stage context
                # or filter teams based on current_stage_number.
                # For now, we call the existing functions, assuming they can be adapted or are sufficient.
                
                if stage_format == "swiss" or stage_format == "smart_swiss":
                    # Pass stage context for stage-aware team filtering
                    generate_next_swiss_round(tournament, stage=current_stage)
                elif stage_format == "knockout":
                    generate_next_knockout_round(tournament)
                elif stage_format == "round_robin":
                    # Round robin within a stage might need specific logic if not all matches are pre-generated
                    generate_next_round_robin_round(tournament)
                # Add other stage formats like "poule" if needed
                else:
                    logger.error(f"Unsupported stage format 	{stage_format}	 for stage {current_stage.id}. Cannot generate next round within stage.")
                    tournament.automation_status = "error"
                    tournament.save()
                    return
                
                # Check if the called function updated the round number and status correctly
                tournament.refresh_from_db() 
                if tournament.current_round_number == next_overall_round_num and tournament.automation_status == "idle":
                    logger.info(f"Successfully generated next round within stage {current_stage.stage_number}.")
                else:
                    logger.error(f"Failed to generate round {next_overall_round_num} within stage {current_stage.stage_number}. Status: {tournament.automation_status}, Round: {tournament.current_round_number}")
                    # Ensure status is error if generation failed
                    if tournament.automation_status != "error":
                         tournament.automation_status = "error"
                         tournament.save()

    except Exception as e:
        logger.exception(f"Error processing multi-stage progression for tournament {tournament.id}: {e}")
        try:
            tournament.refresh_from_db()
            if tournament.automation_status != "error":
                tournament.automation_status = "error"
                tournament.save()
        except Tournament.DoesNotExist:
            pass
        raise


def check_round_completion(tournament_id):
    """Checks if all matches in the current round are completed and triggers next round generation."""
    logger.info(f"🔍 DEBUG: check_round_completion called for tournament {tournament_id}")
    try:
        with transaction.atomic():
            tournament = Tournament.objects.select_for_update().get(id=tournament_id)
            logger.info(f"🔍 DEBUG: Tournament {tournament.id} found - Format: {tournament.format}, Status: {tournament.automation_status}")

            # Avoid race conditions or redundant checks
            if tournament.automation_status != "idle":
                logger.warning(f"Automation for tournament {tournament.id} is already running or completed. Skipping check.")
                return

            current_round = tournament.current_round_number
            logger.info(f"🔍 DEBUG: Current round number: {current_round}")
            if current_round is None:
                logger.info(f"Tournament {tournament.id} has not started or round number is not set. Skipping completion check.")
                return

            # Find matches for the current round - FIXED: Use round__number since Match has Round ForeignKey
            round_matches = Match.objects.filter(tournament=tournament, round__number=current_round)
            logger.info(f"🔍 DEBUG: Found {round_matches.count()} matches for round {current_round}")
            
            # Debug: List all matches and their status
            for match in round_matches:
                logger.info(f"🔍 DEBUG: Match {match.id} - Status: {match.status}, Round: {match.round.number if match.round else 'None'}")

            if not round_matches.exists():
                logger.warning(f"No matches found for round {current_round} in tournament {tournament.id}. Cannot check completion.")
                # Potentially mark tournament as errored or needing admin intervention?
                return

            # Check if all matches in the round are completed
            all_completed = all(match.status == "completed" for match in round_matches)
            logger.info(f"🔍 DEBUG: All matches completed: {all_completed}")

            if all_completed:
                logger.info(f"All matches for round {current_round} in tournament {tournament.id} are completed.")
                tournament.automation_status = "processing"
                tournament.save()
                logger.info(f"🔍 DEBUG: Tournament status set to 'processing', calling generation function for format: {tournament.format}")

                # Trigger next round generation based on format
                if tournament.format == "round_robin":
                    generate_next_round_robin_round(tournament)
                elif tournament.format == "swiss" or tournament.format == "smart_swiss":
                    generate_next_swiss_round(tournament)
                elif tournament.format == "knockout":
                    generate_next_knockout_round(tournament)
                elif tournament.format == "multi_stage":
                    generate_next_combo_round(tournament)
                else:
                    logger.error(f"Unknown tournament format 	{tournament.format}	 for tournament {tournament.id}. Cannot generate next round.")
                    tournament.automation_status = "error"
                    tournament.save()
                    # TODO: Add admin notification here
                    return

                # If generation was successful (or placeholder ran), update status
                # The generation functions themselves should update round number and status on success/failure
                # For now, assume placeholder means success and reset status
                # In real implementation, generation functions would handle this.
                if tournament.automation_status == "processing": # Check if generation function changed it
                     tournament.automation_status = "idle" # Reset for next check
                     tournament.save()

            else:
                logger.info(f"Round {current_round} in tournament {tournament.id} is not yet complete. Waiting for remaining matches.")
            
            # Check if tournament is completed and assign badges if needed
            # This runs after all match generation logic to avoid interference
            try:
                from .completion import check_and_complete_tournament
                check_and_complete_tournament(tournament)
            except Exception as e:
                logger.exception(f"Error checking tournament completion for {tournament.id}: {e}")
                # Don't fail the entire automation if badge assignment fails

    except Tournament.DoesNotExist:
        logger.error(f"Tournament with ID {tournament_id} not found during completion check.")
    except Exception as e:
        logger.exception(f"Error checking round completion for tournament {tournament_id}: {e}")
        # Attempt to mark tournament as errored if possible
        try:
            tournament = Tournament.objects.get(id=tournament_id)
            tournament.automation_status = "error"
            tournament.save()
        except Tournament.DoesNotExist:
            pass # Tournament doesn't exist, nothing to mark
        # TODO: Add admin notification here

