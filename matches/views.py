from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.utils import timezone
from django.db.models import Q, Exists, OuterRef
from django.urls import reverse
import logging

from .models import Match, MatchActivation, MatchPlayer, MatchResult, NextOpponentRequest
from teams.models import Team, Player
from tournaments.models import Tournament, TournamentTeam, TournamentCourt, Round, Stage
from courts.models import Court
from friendly_games.models import FriendlyGame  # Import FriendlyGame model
from .forms import MatchActivationForm, MatchResultForm, MatchValidationForm
from .utils import auto_assign_court, get_court_assignment_status
from .utils import detect_match_type, validate_match_type  # Import match type utilities

logger = logging.getLogger(__name__)

def match_list(request, tournament_id=None):
    # Tournament matches (existing functionality)
    active_matches = Match.objects.filter(status="active").order_by("-start_time")
    pending_matches = Match.objects.filter(status="pending").order_by("scheduled_time")
    pending_verification_matches = Match.objects.filter(status="pending_verification").order_by("updated_at")
    waiting_validation = Match.objects.filter(status="waiting_validation").order_by("updated_at")
    completed_matches = Match.objects.filter(status="completed").order_by("-end_time")

    if tournament_id:
        tournament = get_object_or_404(Tournament, id=tournament_id)
        active_matches = active_matches.filter(tournament=tournament)
        pending_matches = pending_matches.filter(tournament=tournament)
        pending_verification_matches = pending_verification_matches.filter(tournament=tournament)
        waiting_validation = waiting_validation.filter(tournament=tournament)
        completed_matches = completed_matches.filter(tournament=tournament)
    else:
        tournament = None

    # Friendly games (new functionality)
    friendly_waiting = FriendlyGame.objects.filter(status="WAITING_FOR_PLAYERS").order_by("-created_at")
    friendly_active = FriendlyGame.objects.filter(status="ACTIVE").order_by("-started_at")
    friendly_completed = FriendlyGame.objects.filter(status="COMPLETED").order_by("-completed_at")

    context = {
        "active_matches": active_matches,
        "pending_matches": pending_matches,
        "pending_verification_matches": pending_verification_matches,
        "waiting_validation": waiting_validation,
        "completed_matches": completed_matches,
        "tournament": tournament,
        # Friendly games data
        "friendly_waiting": friendly_waiting,
        "friendly_active": friendly_active,
        "friendly_completed": friendly_completed,
    }
    return render(request, "matches/match_list.html", context)


def match_detail(request, match_id):
    match = get_object_or_404(Match, id=match_id)
    team_pin = request.session.get("team_pin")
    team_obj = None
    if team_pin:
        try:
            team_obj = Team.objects.get(pin=team_pin)
        except Team.DoesNotExist:
            pass # Team not found for PIN, team_obj remains None
            
    # Get MatchPlayer entries for display
    match_players_team1 = MatchPlayer.objects.filter(match=match, team=match.team1).select_related("player")
    match_players_team2 = MatchPlayer.objects.filter(match=match, team=match.team2).select_related("player")

    context = {
        "match": match,
        "team": team_obj, # Pass current team if logged in via PIN
        "match_players_team1": match_players_team1,
        "match_players_team2": match_players_team2,
    }
    return render(request, "matches/match_detail.html", context)


def request_next_opponent(request, tournament_id, team_id):
    """Find the next match for a team, prioritizing partially activated matches."""
    tournament = get_object_or_404(Tournament, id=tournament_id)
    requesting_team = get_object_or_404(Team, id=team_id)
    
    # First, check for partially activated matches (pending_verification) across all tournaments
    # These are prioritized as they already have one team that has activated them
    partially_activated_match = Match.objects.filter(
        Q(status="pending_verification") & 
        (
            (Q(team1=requesting_team) & ~Q(activations__team=requesting_team)) | 
            (Q(team2=requesting_team) & ~Q(activations__team=requesting_team))
        )
    ).select_related('tournament', 'team1', 'team2').order_by('created_at').first()
    
    # If a partially activated match is found, redirect to it
    if partially_activated_match:
        messages.success(request, "Priority match found! This match is waiting for your activation.")
        return redirect("match_detail", match_id=partially_activated_match.id)
    
    # Next, find regular pending matches
    pending_match = Match.objects.filter(
        Q(status="pending") & 
        (Q(team1=requesting_team) | Q(team2=requesting_team))
    ).select_related('tournament', 'team1', 'team2').order_by('created_at').first()
    
    # If a pending match is found, redirect to it
    if pending_match:
        messages.info(request, "Pending match found. You can activate this match.")
        return redirect("match_detail", match_id=pending_match.id)
    
    # If no matches are found, show a message and redirect to tournament detail
    messages.info(request, "No pending matches found for your team at this time.")
    return redirect("tournament_detail", tournament_id=tournament.id)


def match_activate(request, match_id, team_id):
    match = get_object_or_404(Match, id=match_id)
    team = get_object_or_404(Team, id=team_id)
    tournament = match.tournament

    if team != match.team1 and team != match.team2:
        messages.error(request, "This team is not part of this match.")
        return redirect("match_detail", match_id=match.id)

    existing_activation = match.activations.order_by("activated_at").first()
    is_initiating = not existing_activation
    is_validating = existing_activation and existing_activation.team != team

    team_activation_exists = match.activations.filter(team=team).exists()
    if team_activation_exists:
        messages.info(request, "Your team has already initiated or validated this match.")
        return redirect("match_detail", match_id=match.id)

    if is_initiating and match.status != "pending":
        messages.error(request, f"This match cannot be initiated (status: {match.get_status_display()}).")
        return redirect("match_detail", match_id=match.id)
    if is_validating and match.status != "pending_verification":
        messages.error(request, f"This match is not waiting for your validation (status: {match.get_status_display()}).")
        return redirect("match_detail", match_id=match.id)
    if is_validating and existing_activation.team == team:
         messages.error(request, "Internal state error: Match is pending verification, but your team initiated it.")
         return redirect("match_detail", match_id=match.id)

    if request.method == "POST":
        form = MatchActivationForm(match, team, request.POST)
        if form.is_valid():
            selected_players_current_team = list(form.cleaned_data["players"])

            # Validate match type for both initiating and validating teams
            if is_initiating:
                # For initiating team, we need to check if their player count is valid for the tournament
                player_count = len(selected_players_current_team)
                
                # Check against tournament rules - for initiating team, we validate their count
                tournament_config = getattr(tournament, 'allowed_match_types', {})
                allowed_types = tournament_config.get('allowed_match_types', [])
                
                # Determine if the player count is valid for any allowed match type
                valid_counts = []
                if 'tete_a_tete' in allowed_types:
                    valid_counts.append(1)
                if 'doublet' in allowed_types:
                    valid_counts.append(2)
                if 'triplet' in allowed_types:
                    valid_counts.append(3)
                
                if valid_counts and player_count not in valid_counts:
                    # Generate appropriate error message
                    if len(valid_counts) == 1:
                        required_count = valid_counts[0]
                        match_type_name = {1: "Tête-à-tête", 2: "Doublet", 3: "Triplet"}[required_count]
                        error_message = f"This tournament only allows {match_type_name} matches ({required_count} player{'s' if required_count > 1 else ''} per team). You selected {player_count} player{'s' if player_count > 1 else ''}."
                    else:
                        valid_counts_str = ", ".join([str(c) for c in sorted(valid_counts)])
                        error_message = f"This tournament only allows matches with {valid_counts_str} players per team. You selected {player_count} player{'s' if player_count > 1 else ''}."
                    
                    messages.error(request, error_message)
                    return render(request, "matches/match_activate.html", {
                        "match": match,
                        "team": team,
                        "form": form,
                        "is_initiating": is_initiating,
                        "is_validating": is_validating,
                    })

            # If validating, check match type against tournament rules
            if is_validating:
                first_activating_team = existing_activation.team 
                first_team_match_players_qs = MatchPlayer.objects.filter(match=match, team=first_activating_team)
                first_team_selected_players = [mp.player for mp in first_team_match_players_qs]
                
                # Debug logging
                logger.info(f"Validation Debug - Match {match.id}: First team {first_activating_team.name} has {len(first_team_selected_players)} players in MatchPlayer records")
                logger.info(f"Validation Debug - Current team {team.name} selected {len(selected_players_current_team)} players")

                # Determine which team is team1 and team2 for consistent ordering
                if first_activating_team == match.team1:
                    team1_actual_players = first_team_selected_players
                    team2_actual_players = selected_players_current_team
                else: 
                    team2_actual_players = first_team_selected_players
                    team1_actual_players = selected_players_current_team
                
                # Detect match type based on player counts
                detected_type, count1, count2 = detect_match_type(team1_actual_players, team2_actual_players)
                logger.info(f"Detected match type for Match {match.id} upon validation by {team.name}: {detected_type} ({count1} vs {count2})")
                
                # Validate match type against tournament rules
                is_valid, error_message = validate_match_type(detected_type, count1, count2, tournament)
                
                # If match type is not valid, show error and return to form
                if not is_valid:
                    messages.error(request, error_message)
                    return render(request, "matches/match_activate.html", {
                        "match": match,
                        "team": team,
                        "form": form,
                        "is_initiating": is_initiating,
                        "is_validating": is_validating,
                    })
                
                # Store match type information for statistics
                match.match_type = detected_type
                match.team1_player_count = count1
                match.team2_player_count = count2
                match.save()
                
                # Update match_format for all players in this match
                MatchPlayer.objects.filter(match=match).update(match_format=detected_type)

            # Create activation record
            activation = MatchActivation.objects.create(
                match=match,
                team=team,
                pin_used=form.cleaned_data["pin"],
                is_initiator=is_initiating
            )

            # Create MatchPlayer records for selected players with their roles
            for player_obj in selected_players_current_team:
                role_field = f"role_{player_obj.id}"
                role = form.cleaned_data.get(role_field, "flex")
                MatchPlayer.objects.create(
                    match=match,
                    player=player_obj,
                    team=team,
                    role=role,
                    match_format=match.match_type if hasattr(match, 'match_type') and match.match_type else None
                )
            
            if is_initiating:
                match.status = "pending_verification"
                match.save()
                messages.success(request, "Match initiated successfully. Waiting for the other team to validate.")
                return redirect("match_detail", match_id=match.id)
            elif is_validating: 
                # Try to assign court FIRST before changing match status
                logger.debug(f"Attempting to call auto_assign_court for match {match.id}")
                court = auto_assign_court(match)

                if court:
                    # Court available - activate the match
                    match.status = "active"
                    match.start_time = timezone.now()
                    match.waiting_for_court = False
                    match.save()
                    
                    status_message = get_court_assignment_status(match)
                    messages.success(request, f"Match validated and activated! {status_message}")
                else:
                    # No court available - keep match in waiting state
                    match.waiting_for_court = True
                    match.save()
                    
                    messages.warning(request, "Match validated, but no courts are currently available. The match will start automatically when a court becomes free.")
                
                return redirect("match_detail", match_id=match.id)
    else: 
        form = MatchActivationForm(match, team)

    # For validating teams, get the first team's players to show in template
    first_team_match_players = []
    if is_validating and existing_activation:
        first_activating_team = existing_activation.team
        first_team_match_players_qs = MatchPlayer.objects.filter(match=match, team=first_activating_team)
        first_team_match_players = [mp.player for mp in first_team_match_players_qs]

    context = {
        "match": match,
        "team": team,
        "form": form,
        "is_initiating": is_initiating,
        "is_validating": is_validating,
        "first_team_match_players": first_team_match_players,
    }
    return render(request, "matches/match_activate.html", context)

def match_submit_result(request, match_id, team_id):
    match = get_object_or_404(Match, id=match_id)
    team = get_object_or_404(Team, id=team_id)

    if team != match.team1 and team != match.team2:
        messages.error(request, "This team is not part of this match.")
        return redirect("match_detail", match_id=match.id)

    if match.status != "active":
        messages.error(request, "Results can only be submitted for active matches.")
        return redirect("match_detail", match_id=match.id)

    try:
        existing_result = match.result
        if match.status == "waiting_validation":
             messages.info(request, "Results already submitted. Waiting for validation.")
             return redirect("match_detail", match_id=match.id)
    except MatchResult.DoesNotExist:
        pass

    if request.method == "POST":
        form = MatchResultForm(match, team, request.POST, request.FILES)
        if form.is_valid():
            try:
                old_result = match.result
                old_result.delete()
            except MatchResult.DoesNotExist:
                pass

            result = MatchResult.objects.create(
                match=match,
                submitted_by=team,
                photo_evidence=form.cleaned_data.get("photo_evidence"),
                notes=form.cleaned_data.get("notes")
            )

            match.team1_score = form.cleaned_data["team1_score"]
            match.team2_score = form.cleaned_data["team2_score"]
            match.status = "waiting_validation"
            match.save()

            messages.success(request, "Results submitted successfully. Waiting for validation from the other team.")
            return redirect("match_detail", match_id=match.id)
    else:
        form = MatchResultForm(match, team)

    context = {
        "match": match,
        "team": team,
        "form": form,
    }
    return render(request, "matches/match_submit_result.html", context)

def match_validate_result(request, match_id, team_id):
    match = get_object_or_404(Match, id=match_id)
    team = get_object_or_404(Team, id=team_id)

    if team != match.team1 and team != match.team2:
        messages.error(request, "This team is not part of this match.")
        return redirect("match_detail", match_id=match.id)

    if match.status != "waiting_validation":
        messages.error(request, "This match is not waiting for validation.")
        return redirect("match_detail", match_id=match.id)

    try:
        result = match.result
    except MatchResult.DoesNotExist:
        messages.error(request, "No results have been submitted for this match.")
        return redirect("match_detail", match_id=match.id)

    if result.submitted_by == team:
        messages.error(request, "You cannot validate your own result submission.")
        return redirect("match_detail", match_id=match.id)

    if request.method == "POST":
        form = MatchValidationForm(match, team, request.POST)
        if form.is_valid():
            validation_action = form.cleaned_data["validation_action"]

            if validation_action == "agree":
                result.validated_by = team
                result.validated_at = timezone.now()
                result.save()

                match.status = "completed"
                match.end_time = timezone.now()
                if match.start_time:
                    match.duration = match.end_time - match.start_time
                
                if match.team1_score > match.team2_score:
                    match.winner = match.team1
                    match.loser = match.team2
                elif match.team2_score > match.team1_score:
                    match.winner = match.team2
                    match.loser = match.team1
                else: # Draw
                    match.winner = None
                    match.loser = None
                match.save()
                
                # ===== TOURNAMENT PROGRESSION CHECK =====
                # Check if tournament should advance to next stage/round after match completion
                try:
                    tournament = match.tournament
                    if tournament.format == "multi_stage":
                        advanced, matches_created, tournament_complete = tournament.advance_to_next_stage()
                        if advanced:
                            logger.info(f"Tournament {tournament.name} advanced to next stage, created {matches_created} matches")
                        elif tournament_complete:
                            logger.info(f"Tournament {tournament.name} completed")
                    elif tournament.format == "knockout":
                        advanced, matches_created, tournament_complete = tournament.check_and_advance_knockout_round()
                        if advanced:
                            logger.info(f"Tournament {tournament.name} advanced to next round, created {matches_created} matches")
                        elif tournament_complete:
                            logger.info(f"Tournament {tournament.name} completed")
                except Exception as e:
                    logger.error(f"Tournament progression error for {match.tournament.name}: {e}")
                    # Continue with normal match completion - progression failures don't break matches
                # ===== END TOURNAMENT PROGRESSION CHECK =====
                
                # ===== RATING SYSTEM INTEGRATION =====
                # Update player ratings after successful match completion
                # This is completely separate from match completion and won't affect it if it fails
                try:
                    from .rating_integration import update_tournament_match_ratings
                    rating_result = update_tournament_match_ratings(match)
                    if rating_result["success"]:
                        logger.info(f"Match {match.id} rating updates: {rating_result.get('reason', 'completed successfully')}")
                    else:
                        logger.warning(f"Match {match.id} rating updates failed: {rating_result.get('reason', 'unknown error')}")
                except Exception as e:
                    logger.error(f"Rating system error for match {match.id}: {e}")
                    # Continue with normal match completion - rating failures don't break matches
                # ===== END RATING SYSTEM INTEGRATION =====
                
                if match.court:
                    logger.info(f"Match {match.id} completed, freeing court {match.court.name}")
                    waiting_matches = Match.objects.filter(
                        tournament=match.tournament,
                        status="pending_verification",
                        waiting_for_court=True
                    ).order_by("created_at")
                    
                    if waiting_matches.exists():
                        next_match_to_assign = waiting_matches.first()
                        logger.info(f"Court {match.court.name} freed. Assigning to next waiting match {next_match_to_assign.id}")
                        next_match_to_assign.court = match.court
                        next_match_to_assign.waiting_for_court = False
                        next_match_to_assign.status = "active" # Make it active
                        next_match_to_assign.start_time = timezone.now()
                        next_match_to_assign.save()
                    else:
                        # No matches waiting, mark court as available
                        match.court.is_available = True
                        match.court.save(update_fields=["is_available"])
                        logger.info(f"Court {match.court.name} marked as available - no matches waiting") 
                messages.success(request, "Results validated and match completed.")
                return redirect("match_detail", match_id=match.id)
            
            elif validation_action == "disagree":
                result.delete() # Delete the submitted result
                match.status = "active" # Revert match to active for resubmission
                match.team1_score = None
                match.team2_score = None
                match.save()
                messages.warning(request, "Results disagreed. The match is now active again for resubmission of scores.")
                return redirect("match_detail", match_id=match.id)
    else:
        form = MatchValidationForm(match, team)

    context = {
        "match": match,
        "team": team,
        "result": result,
        "form": form,
    }
    return render(request, "matches/match_validate_result.html", context)
