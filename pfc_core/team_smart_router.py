"""
Team Smart Router — Decision-State Routing for Team PIN Actions
================================================================

This module provides decision-state routing for the team_login view's
"Find Match" and "Submit Score" buttons. Instead of routing to the
intermediary team_matches or team_submit_score list pages, it resolves
the exact decision URL based on the team's current match state.

Used by: teams/views.py team_login() when action is 'find_next' or 'submit_score'
"""

from django.shortcuts import redirect
from django.urls import reverse
from django.db.models import Q
from django.contrib import messages

from matches.models import Match, MatchActivation, MatchResult


def resolve_find_next(request, team):
    """
    Smart routing for 'Find Match' button.
    
    Instead of going to team_matches (list of pending matches),
    find the highest-priority match and route directly to its
    decision page (activate = pick players).
    
    Priority:
    1. pending_verification where OTHER team activated (we need to respond)
    2. pending (nobody activated yet)
    
    If only one match → go directly to match_activate.
    If multiple → go to team_matches list (user must choose).
    If none → go to team_matches (shows "no matches" message).
    """
    team_id = team.id
    
    # Get all actionable matches for this team
    matches = Match.objects.filter(
        Q(team1=team) | Q(team2=team)
    ).filter(
        status__in=['pending', 'pending_verification']
    ).select_related('team1', 'team2', 'tournament').prefetch_related('activations')
    
    # Categorize
    needs_our_activation = []  # pending_verification, other team activated
    pending_fresh = []         # pending, nobody activated
    waiting_for_opponent = []  # pending_verification, WE activated
    
    for match in matches:
        if match.status == 'pending_verification':
            our_activation = match.activations.filter(team_id=team_id).exists()
            if our_activation:
                waiting_for_opponent.append(match)
            else:
                needs_our_activation.append(match)
        elif match.status == 'pending':
            pending_fresh.append(match)
    
    # Prioritized actionable matches (excludes waiting_for_opponent — nothing to do)
    actionable = needs_our_activation + pending_fresh
    
    if not actionable:
        if waiting_for_opponent:
            # Only matches where we're waiting — show info
            messages.info(request, "Your match is waiting for the opponent to activate.")
            return redirect('match_detail', match_id=waiting_for_opponent[0].id)
        # No matches at all
        return redirect('team_matches')
    
    if len(actionable) == 1:
        # Single match → go directly to activate (player selection)
        match = actionable[0]
        return redirect('match_activate', match_id=match.id, team_id=team_id)
    
    # Multiple actionable matches → user must choose
    # Fall back to the list view
    return redirect('team_matches')


def resolve_submit_score(request, team):
    """
    Smart routing for 'Submit Score' button.
    
    Instead of going to team_submit_score (list of active matches),
    find the highest-priority match and route directly to its
    decision page (submit_result or validate_result).
    
    Priority:
    1. waiting_validation where OTHER team submitted (we validate)
    2. active where no result submitted yet (we submit score)
    3. waiting_validation where WE submitted (just info)
    
    If only one match → go directly to the decision page.
    If multiple → go to team_submit_score list.
    If none → go to team_submit_score (shows "no matches" message).
    """
    team_id = team.id
    
    matches = Match.objects.filter(
        Q(team1=team) | Q(team2=team)
    ).filter(
        status__in=['active', 'waiting_validation']
    ).select_related('team1', 'team2', 'tournament')
    
    # Categorize
    needs_our_validation = []   # waiting_validation, opponent submitted
    needs_our_submission = []   # active, no result yet
    waiting_for_opponent = []   # waiting_validation, WE submitted
    
    for match in matches:
        if match.status == 'waiting_validation':
            try:
                result = match.result
                if result.submitted_by_id == team_id:
                    waiting_for_opponent.append(match)
                else:
                    needs_our_validation.append(match)
            except MatchResult.DoesNotExist:
                # Edge case — status says waiting but no result
                needs_our_validation.append(match)
        elif match.status == 'active':
            try:
                result = match.result
                # Result exists on active match — unusual but handle it
                if result.submitted_by_id == team_id:
                    waiting_for_opponent.append(match)
                else:
                    needs_our_submission.append(match)
            except MatchResult.DoesNotExist:
                needs_our_submission.append(match)
    
    # Prioritized actionable matches
    actionable = needs_our_validation + needs_our_submission
    
    if not actionable:
        if waiting_for_opponent:
            messages.info(request, "Your score has been submitted. Waiting for opponent validation.")
            return redirect('match_detail', match_id=waiting_for_opponent[0].id)
        return redirect('team_submit_score')
    
    if len(actionable) == 1:
        match = actionable[0]
        if match in needs_our_validation:
            return redirect('match_validate_result', match_id=match.id, team_id=team_id)
        else:
            return redirect('match_submit_result', match_id=match.id, team_id=team_id)
    
    # Multiple actionable matches → user must choose
    return redirect('team_submit_score')
