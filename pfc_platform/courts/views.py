from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
from .models import Court
from matches.models import Match

def is_staff(user):
    return user.is_staff

def court_list(request):
    courts = Court.objects.all()
    # Update context to pass court details correctly if needed by template
    return render(request, 'courts/court_list.html', {'courts': courts})

def court_detail(request, court_id):
    court = get_object_or_404(Court, id=court_id)
    return render(request, 'courts/court_detail.html', {
        'court': court,
    })

def find_available_courts(tournament=None):
    """
    Finds available courts (not currently in use).
    Optionally prioritizes courts assigned to a specific tournament (if implemented).
    """
    # Find courts that are NOT active (i.e., available)
    available_courts = Court.objects.filter(is_active=False)

    # TODO: Implement court-tournament assignment and uncomment/adjust filtering logic
    # If tournament is specified, prioritize courts assigned to this tournament
    # if tournament:
    #     # Assuming a ManyToManyField 'tournaments' on Court model or similar relationship
    #     tournament_courts = available_courts.filter(tournaments=tournament)
    #     if tournament_courts.exists():
    #         return tournament_courts

    return available_courts

@user_passes_test(is_staff)
def assign_court(request, match_id):
    """ Allows staff to manually assign an available court to a match. """
    match = get_object_or_404(Match, id=match_id)

    # Find available courts to present as options
    available_courts = Court.objects.filter(is_active=False)

    if request.method == 'POST':
        court_id = request.POST.get('court_id')
        if court_id:
            try:
                court = get_object_or_404(Court, id=court_id)
                # Double-check if the selected court is still available
                if court.is_active:
                    messages.error(request, f"Court {court.number} ({court}) is currently in use. Please select another court.")
                else:
                    # Assign court to the match
                    match.court = court
                    match.save()
                    # Note: Marking the court as active (is_active=True) should likely happen
                    # when the match status becomes 'active', not just upon assignment.
                    # This logic might need adjustment in the match status update process.
                    messages.success(request, f"Match {match.id} assigned to Court {court.number} ({court}).")
                    # Redirect to match detail or tournament dashboard, adjust as needed
                    return redirect('admin:matches_match_changelist') # Redirecting to admin match list for now
            except Court.DoesNotExist:
                messages.error(request, "Selected court not found.")
        else:
            messages.warning(request, "No court was selected.")

    # Render the assignment form
    return render(request, 'courts/assign_court.html', { # Assuming 'courts/assign_court.html' exists/is correct
        'match': match,
        'available_courts': available_courts
    })

def auto_assign_court(match):
    """
    Automatically assign an available court to a match, prioritizing tournament courts if applicable.
    Returns the assigned Court object or None if no court could be assigned.
    """
    # Check if match already has a court
    if match.court:
        print(f"Match {match.id} already has court {match.court.number}")
        return match.court # Return existing court if already assigned

    # Find potentially available courts (is_active=False)
    tournament = match.tournament if hasattr(match, 'tournament') else None
    potential_courts = find_available_courts(tournament) # Uses corrected logic

    # Exclude courts currently in use by other *active* matches
    # Consider if 'pending_verification' or other statuses should also block a court
    active_matches = Match.objects.filter(status='active').exclude(id=match.id)
    courts_in_use_ids = [m.court.id for m in active_matches if m.court]

    # Filter out courts that are actually in use by active matches
    truly_available_courts = potential_courts.exclude(id__in=courts_in_use_ids)

    if truly_available_courts.exists():
        # Assign the first available court found
        court_to_assign = truly_available_courts.first()
        match.court = court_to_assign
        match.save()
        print(f"Auto-assigned Court {court_to_assign.number} to Match {match.id}")
        return court_to_assign
    else:
        print(f"No available courts found for Match {match.id}")
        return None

