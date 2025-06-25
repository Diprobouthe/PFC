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


def generate_next_swiss_round(tournament):
    logger.info(f"Attempting to generate next Swiss round for tournament {tournament.id}")
    
    try:
        with transaction.atomic():
            current_round = tournament.current_round_number
            next_round_num = current_round + 1
            logger.info(f"Current round: {current_round}, generating for round: {next_round_num}")

            # --- 1. Update Swiss Points and Buchholz (if necessary) ---
            # Note: Buchholz calculation is complex and often done after all points are updated.
            # We might need a separate step or recalculate it here based on *current* opponent points.
            active_teams_tt = list(TournamentTeam.objects.filter(tournament=tournament, is_active=True).select_related("team"))
            for tt in active_teams_tt:
                tt.update_swiss_stats() # Recalculate points based on completed matches
            
            # Optional: Recalculate Buchholz globally here if needed
            # calculate_buchholz_scores(tournament)

            # --- 2. Get Sorted Active Teams --- 
            # Re-fetch with updated points, ordered for pairing
            teams_to_pair = list(TournamentTeam.objects.filter(tournament=tournament, is_active=True).order_by("-swiss_points", "-buchholz_score", "id"))
            num_teams = len(teams_to_pair)
            logger.debug(f"Teams to pair ({num_teams}): {[t.team.name for t in teams_to_pair]}")

            if num_teams < 2:
                logger.warning(f"Not enough active teams ({num_teams}) to generate next round for {tournament.name}. Marking tournament as completed.")
                tournament.automation_status = "completed"
                tournament.save()
                return

            # --- 3. Handle Bye --- 
            bye_team_tt = None
            if num_teams % 2 != 0:
                # Find the lowest-ranked team that hasn't received a bye yet
                for i in range(num_teams - 1, -1, -1):
                    candidate = teams_to_pair[i]
                    if candidate.received_bye_in_round is None:
                        bye_team_tt = teams_to_pair.pop(i) # Remove from pairing list
                        break
                
                if bye_team_tt:
                    logger.info(f"Assigning Bye to {bye_team_tt.team.name} in Swiss Round {next_round_num}")
                    bye_team_tt.received_bye_in_round = next_round_num
                    bye_team_tt.swiss_points += 3 # Assuming 3 points for a bye win
                    bye_team_tt.save()
                else:
                    # This should ideally not happen if byes are managed correctly across rounds
                    logger.error(f"Odd number of teams ({num_teams}) but could not assign a bye (all remaining teams may have had one). Manual intervention needed.")
                    tournament.automation_status = "error"
                    tournament.save()
                    return

            # --- 4. Perform Pairing --- 
            paired_indices = set()
            matches_created = []
            
            for i in range(num_teams):
                if i in paired_indices:
                    continue
                
                team1_tt = teams_to_pair[i]
                found_opponent = False
                for j in range(i + 1, num_teams):
                    if j in paired_indices:
                        continue
                        
                    team2_tt = teams_to_pair[j]
                    
                    # Check if they have played before
                    if team2_tt.team not in team1_tt.opponents_played.all():
                        # Pair found!
                        logger.info(f"Pairing {team1_tt.team.name} ({team1_tt.swiss_points} pts) vs {team2_tt.team.name} ({team2_tt.swiss_points} pts) for round {next_round_num}")
                        match = Match.objects.create(
                            tournament=tournament,
                            round_number=next_round_num,
                            team1=team1_tt.team,
                            team2=team2_tt.team,
                            status="pending"
                        )
                        matches_created.append(match)
                        
                        # Mark as paired for this round
                        paired_indices.add(i)
                        paired_indices.add(j)
                        
                        # Update opponents played
                        team1_tt.opponents_played.add(team2_tt.team)
                        team2_tt.opponents_played.add(team1_tt.team)
                        
                        found_opponent = True
                        break # Move to the next unpaired team
                
                if not found_opponent and i not in paired_indices:
                    # If we reach here, team i could not be paired with anyone they haven't played
                    # This requires more complex handling (e.g., allow rematches, pair across score groups)
                    # For now, log an error and stop generation
                    logger.error(f"Could not find suitable opponent for {team1_tt.team.name} in round {next_round_num}. All potential opponents may have been played. Manual intervention needed.")
                    tournament.automation_status = "error"
                    tournament.save()
                    # Rollback transaction implicitly via exception or explicit raise
                    raise Exception(f"Pairing failed for tournament {tournament.id}, round {next_round_num}")

            # --- 5. Finalize Round --- 
            if len(matches_created) > 0 or bye_team_tt:
                tournament.current_round_number = next_round_num
                tournament.automation_status = "idle" # Ready for next check after this round completes
                tournament.save()
                logger.info(f"Successfully generated {len(matches_created)} matches for Swiss round {next_round_num} in tournament {tournament.id}.")
            else:
                # Should not happen if pairing logic is correct and num_teams >= 2
                logger.error(f"No matches were created for round {next_round_num} despite having teams. Setting status to error.")
                tournament.automation_status = "error"
                tournament.save()

    except Exception as e:
        logger.exception(f"Error generating Swiss round {tournament.current_round_number + 1} for tournament {tournament.id}: {e}")
        # Ensure status is set to error if not already
        try:
            tournament.refresh_from_db()
            if tournament.automation_status != "error":
                tournament.automation_status = "error"
                tournament.save()
        except Tournament.DoesNotExist:
            pass # Tournament might have been deleted
        # Re-raise the exception to ensure transaction rollback if not handled explicitly
        raise


def generate_next_knockout_round(tournament):
    logger.info(f"Attempting to generate next Knockout round for tournament {tournament.id}")
    
    try:
        with transaction.atomic():
            current_round = tournament.current_round_number
            next_round_num = current_round + 1
            logger.info(f"Current round: {current_round}, generating for round: {next_round_num}")

            # --- 1. Identify Advancing Teams --- 
            advancing_teams_tt = []

            # Get winners from completed matches of the current round
            completed_matches = Match.objects.filter(tournament=tournament, round__number=current_round, status="completed")
            for match in completed_matches:
                if match.winner:
                    winner_tt = TournamentTeam.objects.filter(tournament=tournament, team=match.winner).first()
                    if winner_tt and winner_tt.is_active:
                        advancing_teams_tt.append(winner_tt)
                    else:
                         logger.warning(f"Winner team {match.winner.name} not found or inactive in TournamentTeam for match {match.id}. Skipping.")
                elif match.is_draw:
                     logger.warning(f"Match {match.id} in knockout tournament {tournament.id} ended in a draw. Cannot determine winner. Manual intervention needed.")
                     # Set tournament to error? Requires admin to resolve draw.
                     tournament.automation_status = "error"
                     tournament.save()
                     return
                else:
                    logger.warning(f"Completed match {match.id} has no winner and is not a draw. Skipping.")

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
                # TODO: Add notification/final standings update?
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
                        status="pending"
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
                
                if stage_format == "swiss":
                    # Pass stage context or ensure generate_next_swiss_round filters by stage?
                    # generate_next_swiss_round(tournament, stage=current_stage) # Ideal but requires refactor
                    generate_next_swiss_round(tournament) # Current implementation - needs check inside
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
    try:
        with transaction.atomic():
            tournament = Tournament.objects.select_for_update().get(id=tournament_id)

            # Avoid race conditions or redundant checks
            if tournament.automation_status != "idle":
                logger.warning(f"Automation for tournament {tournament.id} is already running or completed. Skipping check.")
                return

            current_round = tournament.current_round_number
            if current_round is None:
                logger.info(f"Tournament {tournament.id} has not started or round number is not set. Skipping completion check.")
                return

            # Find matches for the current round
            round_matches = Match.objects.filter(tournament=tournament, round__number=current_round)

            if not round_matches.exists():
                logger.warning(f"No matches found for round {current_round} in tournament {tournament.id}. Cannot check completion.")
                # Potentially mark tournament as errored or needing admin intervention?
                return

            # Check if all matches in the round are completed
            all_completed = all(match.status == "completed" for match in round_matches)

            if all_completed:
                logger.info(f"All matches for round {current_round} in tournament {tournament.id} are completed.")
                tournament.automation_status = "processing"
                tournament.save()

                # Trigger next round generation based on format
                if tournament.format == "round_robin":
                    generate_next_round_robin_round(tournament)
                elif tournament.format == "swiss":
                    generate_next_swiss_round(tournament)
                elif tournament.format == "knockout":
                    generate_next_knockout_round(tournament)
                elif tournament.format == "combo":
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

