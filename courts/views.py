from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
from .models import Court, CourtComplex
from .utils import get_court_complex_for_court
from matches.models import Match

def is_staff(user):
    return user.is_staff

def court_list(request):
    courts = Court.objects.all()
    # Add complex information for each court
    courts_with_complex = []
    for court in courts:
        complex_info = get_court_complex_for_court(court)
        courts_with_complex.append({
            'court': court,
            'complex': complex_info
        })
    
    return render(request, 'courts/court_list.html', {
        'courts': courts,
        'courts_with_complex': courts_with_complex
    })

def court_detail(request, court_id):
    court = get_object_or_404(Court, id=court_id)
    court_complex = get_court_complex_for_court(court)
    
    return render(request, 'courts/court_detail.html', {
        'court': court,
        'court_complex': court_complex,
    })

def find_available_courts(tournament=None):
    """
    Finds available courts (not currently in use).
    Optionally prioritizes courts assigned to a specific tournament (if implemented).
    """
    # Find courts that are available (is_available=True means available/empty)
    available_courts = Court.objects.filter(is_available=True)

    # TODO: Implement court-tournament assignment and uncomment/adjust filtering logic
    # If tournament is specified, prioritize courts assigned to this tournament
    # if tournament:
    #     tournament_courts = available_courts.filter(tournaments=tournament)
    #     if tournament_courts.exists():
    #         return tournament_courts

    return available_courts

@user_passes_test(is_staff)
def assign_court(request, match_id):
    """ Allows staff to manually assign an available court to a match. """
    match = get_object_or_404(Match, id=match_id)

    # Find available courts to present as options
    available_courts = find_available_courts(match.tournament)

    if request.method == 'POST':
        court_id = request.POST.get('court_id')
        if court_id:
            try:
                court = get_object_or_404(Court, id=court_id)
                # Double-check if the selected court is still available
                if not court.is_available:
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

    # Find available courts (is_available=True means empty/available)
    tournament = match.tournament if hasattr(match, 'tournament') else None
    available_courts = find_available_courts(tournament)

    if available_courts.exists():
        # Assign the first available court found
        court_to_assign = available_courts.first()
        match.court = court_to_assign
        
        # IMPORTANT: Mark the court as occupied
        court_to_assign.is_available = False
        court_to_assign.save()
        
        match.save()
        print(f"Auto-assigned Court {court_to_assign.number} to Match {match.id} and marked as in use")
        return court_to_assign
    else:
        print(f"No available courts found for Match {match.id}")
        return None



# CourtComplex Views
from .models import CourtComplex, CourtComplexRating, CourtComplexPhoto
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
import json

def court_complex_list(request):
    """List all court complexes"""
    complexes = CourtComplex.objects.all()
    return render(request, 'courts/court_complex_list.html', {
        'complexes': complexes
    })

def court_complex_detail(request, complex_id):
    """Detailed view of a court complex"""
    complex_obj = get_object_or_404(CourtComplex, id=complex_id)
    ratings = complex_obj.ratings.all()
    photos = complex_obj.photos.all()[:4]  # Limit to 4 photos
    courts = complex_obj.courts.all()
    
    return render(request, 'courts/court_complex_detail.html', {
        'complex': complex_obj,
        'ratings': ratings,
        'photos': photos,
        'courts': courts,
        'average_rating': complex_obj.average_rating(),
        'rating_count': complex_obj.rating_count(),
    })

@require_POST
def submit_rating(request, complex_id):
    """Submit a rating for a court complex"""
    complex_obj = get_object_or_404(CourtComplex, id=complex_id)
    
    try:
        data = json.loads(request.body)
        codename = data.get('codename', '').strip()
        stars = float(data.get('stars', 0))
        comment = data.get('comment', '').strip()
        
        if not codename:
            return JsonResponse({'error': 'Codename is required'}, status=400)
        
        if not (0.5 <= stars <= 5.0):
            return JsonResponse({'error': 'Rating must be between 0.5 and 5.0'}, status=400)
        
        # Update or create rating
        rating, created = CourtComplexRating.objects.update_or_create(
            court_complex=complex_obj,
            codename=codename,
            defaults={
                'stars': stars,
                'comment': comment
            }
        )
        
        return JsonResponse({
            'success': True,
            'message': 'Rating submitted successfully',
            'average_rating': complex_obj.average_rating(),
            'rating_count': complex_obj.rating_count(),
        })
        
    except (json.JSONDecodeError, ValueError) as e:
        return JsonResponse({'error': 'Invalid data'}, status=400)
    except Exception as e:
        return JsonResponse({'error': 'An error occurred'}, status=500)

