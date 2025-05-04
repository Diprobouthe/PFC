from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.utils import timezone
from django.db.models import Q
import logging # Import logging
from .models import Match, MatchActivation, MatchPlayer, MatchResult, NextOpponentRequest
from .forms import MatchActivationForm, MatchResultForm, MatchValidationForm
from teams.models import Team, Player
from courts.models import Court
from tournaments.models import Tournament
from matches.utils import auto_assign_court, get_court_assignment_status # Import utils

logger = logging.getLogger("matches") # Get the logger

def match_list(request, tournament_id=None):
    """View for listing all matches"""
    # If tournament_id is not in the URL path, check query parameters
    if tournament_id is None:
        tournament_id = request.GET.get("tournament_id")

    if tournament_id:
        matches = Match.objects.filter(tournament_id=tournament_id).order_by("-created_at")
        tournament = get_object_or_404(Tournament, id=tournament_id)
    else:
        matches = Match.objects.all().order_by("-created_at")
        tournament = None

    # Categorize matches by status
    active_matches = matches.filter(status="active")
    pending_matches = matches.filter(status="pending")
    pending_verification_matches = matches.filter(status="pending_verification")
    waiting_validation = matches.filter(status="waiting_validation")
    completed_matches = matches.filter(status="completed")

    context = {
        "tournament": tournament,
        "active_matches": active_matches,
        "pending_matches": pending_matches,
        "pending_verification_matches": pending_verification_matches,
        "waiting_validation": waiting_validation,
        "completed_matches": completed_matches,
    }

    return render(request, "matches/match_list.html", context)

def match_detail(request, match_id):
    """View for displaying match details"""
    match = get_object_or_404(Match, id=match_id)

    # Check if this is an AJAX request for court info
    if request.GET.get("court_info") == "true":
        from django.http import JsonResponse
        # Check if this is a tournament-specific court
        tournament_courts = match.tournament.tournamentcourt_set.all().select_related("court")
        tournament_court_ids = [tc.court.id for tc in tournament_courts]
        is_tournament_court = match.court and match.court.id in tournament_court_ids
        return JsonResponse({"is_tournament_court": is_tournament_court})

    # Get match result if exists
    result = None
    try:
        result = match.result
    except MatchResult.DoesNotExist:
        pass # No result submitted yet

    # Get tournament court IDs for template
    tournament_courts = match.tournament.tournamentcourt_set.all().select_related("court")
    tournament_court_ids = [tc.court.id for tc in tournament_courts]

    # Get initiating team if match is pending verification
    initiating_activation = None
    if match.status == "pending_verification":
        initiating_activation = match.activations.first() # The first activation is the initiator

    context = {
        "match": match,
        "result": result,
        "tournament_court_ids": tournament_court_ids,
        "initiating_activation": initiating_activation,
    }
    return render(request, "matches/match_detail.html", context)

# Removed login_required decorator
def next_opponent_request(request, tournament_id, team_id):
    """View for requesting a next opponent"""
    tournament = get_object_or_404(Tournament, id=tournament_id)
    requesting_team = get_object_or_404(Team, id=team_id)

    # Get available teams (teams that are not already matched with this team)
    matched_team_ids = Match.objects.filter(
        Q(team1=requesting_team) | Q(team2=requesting_team),
        tournament=tournament
    ).values_list("team1_id", "team2_id")

    # Flatten the list and remove the requesting team"s ID
    flat_matched_ids = []
    for t1, t2 in matched_team_ids:
        flat_matched_ids.extend([t1, t2])
    flat_matched_ids = list(set(flat_matched_ids))
    if requesting_team.id in flat_matched_ids:
        flat_matched_ids.remove(requesting_team.id)

    available_teams = Team.objects.filter(
        tournament_teams__tournament=tournament
    ).exclude(
        id__in=flat_matched_ids
    )

    # Get pending match requests
    pending_requests = NextOpponentRequest.objects.filter(
        tournament=tournament,
        requesting_team=requesting_team,
        status="pending"
    )

    if request.method == "POST":
        target_team_id = request.POST.get("target_team_id")
        if target_team_id:
            target_team = get_object_or_404(Team, id=target_team_id)

            # Create the request
            opponent_request = NextOpponentRequest.objects.create(
                tournament=tournament,
                requesting_team=requesting_team,
                target_team=target_team,
                status="pending"
            )

            messages.success(request, f"Request sent to {target_team.name}. Waiting for their response.")
            return redirect("team_tournament_dashboard", tournament_id=tournament.id, team_id=requesting_team.id)

    context = {
        "tournament": tournament,
        "requesting_team": requesting_team,
        "available_teams": available_teams,
        "pending_requests": pending_requests,
    }
    return render(request, "matches/next_opponent_request.html", context)

# Removed login_required decorator
def match_activate(request, match_id, team_id):
    """View for initiating or validating a match using team PIN and selecting players"""
    match = get_object_or_404(Match, id=match_id)
    team = get_object_or_404(Team, id=team_id)

    # Verify this team is part of the match
    if team != match.team1 and team != match.team2:
        messages.error(request, "This team is not part of this match.")
        return redirect("match_detail", match_id=match.id)

    # Determine if this team is initiating or validating
    existing_activation = match.activations.first()
    is_initiating = not existing_activation
    is_validating = existing_activation and existing_activation.team != team

    # Check if this team has already submitted an activation for this match
    team_activation_exists = match.activations.filter(team=team).exists()
    if team_activation_exists:
        messages.info(request, "Your team has already initiated or validated this match.")
        return redirect("match_detail", match_id=match.id)

    # Check if the match is in the correct state for the intended action
    if is_initiating and match.status != "pending":
        messages.error(request, f"This match cannot be initiated (status: {match.get_status_display()}).")
        return redirect("match_detail", match_id=match.id)
    if is_validating and match.status != "pending_verification":
        messages.error(request, f"This match is not waiting for your validation (status: {match.get_status_display()}).")
        return redirect("match_detail", match_id=match.id)
    # Additional check for internal consistency
    if is_validating and existing_activation.team == team:
         messages.error(request, "Internal state error: Match is pending verification, but your team initiated it.")
         return redirect("match_detail", match_id=match.id)

    if request.method == "POST":
        form = MatchActivationForm(match, team, request.POST)
        if form.is_valid():
            # Create activation record
            activation = MatchActivation.objects.create(
                match=match,
                team=team,
                pin_used=form.cleaned_data["pin"],
                is_initiator=is_initiating # Set the initiator flag
            )

            # Create MatchPlayer records for selected players
            selected_players = form.cleaned_data["players"]
            for player in selected_players:
                MatchPlayer.objects.create(
                    match=match,
                    player=player,
                    team=team
                )

            if is_initiating:
                # First team initiating
                match.status = "pending_verification"
                match.save()
                messages.success(request, "Match initiated successfully. Waiting for the other team to validate.")
                return redirect("match_detail", match_id=match.id)
            elif is_validating:
                # Second team validating - attempt to make match active and assign court

                # Set status to active first
                match.status = "active"
                match.start_time = timezone.now()
                match.waiting_for_court = False # Assume court will be found
                match.save()

                # Call the utility function to assign a court
                logger.debug(f"Attempting to call auto_assign_court for match {match.id}") # Explicit debug log
                court = auto_assign_court(match)

                if court:
                    # Court assigned successfully
                    status_message = get_court_assignment_status(match)
                    messages.success(request, f"Match validated and activated! {status_message}.")
                else:
                    # No court could be assigned by the utility function
                    match.waiting_for_court = True
                    match.status = "pending_verification" # Revert status
                    match.start_time = None
                    match.save()
                    messages.warning(request, "Match validated, but no courts are currently available. You are queued and the match will start when a court is free.")
                    # Note: We don"t revert the activation record here, the match is validly activated by both teams, just waiting.

                # Redirect after handling validation logic
                return redirect("match_detail", match_id=match.id)
    else:
        form = MatchActivationForm(match, team)

    context = {
        "match": match,
        "team": team,
        "form": form,
        "is_initiating": is_initiating,
        "is_validating": is_validating,
    }
    return render(request, "matches/match_activate.html", context)

# Removed login_required decorator
def match_submit_result(request, match_id, team_id):
    """View for submitting match results"""
    match = get_object_or_404(Match, id=match_id)
    team = get_object_or_404(Team, id=team_id)

    # Verify this team is part of the match
    if team != match.team1 and team != match.team2:
        messages.error(request, "This team is not part of this match.")
        return redirect("match_detail", match_id=match.id)

    # Check if match is active
    if match.status != "active":
        messages.error(request, "Results can only be submitted for active matches.")
        return redirect("match_detail", match_id=match.id)

    # Check if result already exists (e.g., if page is refreshed after submission)
    try:
        existing_result = match.result
        # If result exists and match is waiting validation, redirect
        if match.status == "waiting_validation":
             messages.info(request, "Results already submitted. Waiting for validation.")
             return redirect("match_detail", match_id=match.id)
        # If result exists but match is somehow active again (e.g., after disagreement), allow resubmission
        # No explicit check needed here, form submission will handle it
    except MatchResult.DoesNotExist:
        pass # No result exists, proceed

    if request.method == "POST":
        form = MatchResultForm(match, team, request.POST, request.FILES)
        if form.is_valid():
            # If a result existed from a previous disagreement, delete it first
            try:
                old_result = match.result
                old_result.delete()
            except MatchResult.DoesNotExist:
                pass

            # Create new result
            result = MatchResult.objects.create(
                match=match,
                submitted_by=team,
                photo_evidence=form.cleaned_data.get("photo_evidence"),
                notes=form.cleaned_data.get("notes")
            )

            # Update match scores and status
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

# Removed login_required decorator
def match_validate_result(request, match_id, team_id):
    """View for validating or disagreeing with match results"""
    match = get_object_or_404(Match, id=match_id)
    team = get_object_or_404(Team, id=team_id)

    # Verify this team is part of the match
    if team != match.team1 and team != match.team2:
        messages.error(request, "This team is not part of this match.")
        return redirect("match_detail", match_id=match.id)

    # Check if match is waiting validation
    if match.status != "waiting_validation":
        messages.error(request, "This match is not waiting for validation.")
        return redirect("match_detail", match_id=match.id)

    # Check if result exists
    try:
        result = match.result
    except MatchResult.DoesNotExist:
        messages.error(request, "No results have been submitted for this match.")
        return redirect("match_detail", match_id=match.id)

    # Check if this team submitted the result (can"t validate own submission)
    if result.submitted_by == team:
        messages.error(request, "You cannot validate your own result submission.")
        return redirect("match_detail", match_id=match.id)

    if request.method == "POST":
        form = MatchValidationForm(match, team, request.POST)
        if form.is_valid():
            validation_action = form.cleaned_data["validation_action"]

            if validation_action == "agree":
                # --- Agree Logic --- 
                result.validated_by = team
                result.validated_at = timezone.now()
                result.save()

                match.status = "completed"
                match.end_time = timezone.now()

                # Calculate duration
                if match.start_time:
                    match.duration = match.end_time - match.start_time
                
                # Determine winner/loser based on validated scores
                if match.team1_score > match.team2_score:
                    match.winner = match.team1
                    match.loser = match.team2
                elif match.team2_score > match.team1_score:
                    match.winner = match.team2
                    match.loser = match.team1
                # No else needed due to form validation preventing draws

                # Release the court (mark as inactive/available)
                if match.court:
                    court_to_release = match.court
                    court_to_release.is_active = False # Mark court as available
                    court_to_release.save()
                    messages.info(request, f"Court {court_to_release.number} released and marked as available.")

                    # Check if any matches are waiting for a court
                    waiting_matches = Match.objects.filter(status="pending_verification", waiting_for_court=True).order_by("created_at")
                    assigned_court = None
                    next_match = None
                    for waiting_match in waiting_matches:
                        # Check if both teams have activated this waiting match
                        if waiting_match.activations.count() == 2:
                            # Check if released court is suitable (tournament or general)
                            tournament_courts = waiting_match.tournament.tournamentcourt_set.all().select_related("court")
                            tournament_court_ids = [tc.court.id for tc in tournament_courts]
                            is_tournament_court = court_to_release.id in tournament_court_ids

                            if tournament_courts: # If waiting match has specific courts
                                if is_tournament_court: # And released court is one of them
                                    assigned_court = court_to_release
                                    next_match = waiting_match
                                    break
                            else: # If waiting match can use any court
                                assigned_court = court_to_release
                                next_match = waiting_match
                                break

                    if assigned_court and next_match:
                        # Assign the court to the first valid waiting match
                        next_match.court = assigned_court
                        next_match.status = "active"
                        next_match.start_time = timezone.now()
                        next_match.waiting_for_court = False
                        next_match.save()
                        messages.info(request, f"Court {assigned_court.number} automatically assigned to waiting match {next_match.id}.")

                match.save()
                messages.success(request, "Results validated successfully. Match completed.")
                return redirect("match_detail", match_id=match.id)

            elif validation_action == "disagree":
                # --- Disagree Logic (New) ---
                # Delete the submitted result
                result.delete()
                
                # Reset match status and scores
                match.status = "active" # Revert to active state for resubmission
                match.team1_score = None
                match.team2_score = None
                match.save()
                
                messages.warning(request, "You disagreed with the submitted score. The result has been cleared. Please coordinate with the other team and resubmit the correct score.")
                return redirect("match_detail", match_id=match.id)

    else:
        form = MatchValidationForm(match, team)

    context = {
        "match": match,
        "team": team,
        "form": form,
        "result": result, # Pass result to template
    }
    return render(request, "matches/match_validate_result.html", context)

