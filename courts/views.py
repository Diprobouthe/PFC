from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
from django.db.models import Q
from django.shortcuts import render, get_object_or_404, redirect
from django.utils import timezone

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
from django.contrib.auth.decorators import login_required
import json

def court_complex_list(request):
    """List all court complexes"""
    complexes = CourtComplex.objects.all()
    return render(request, 'courts/court_complex_list.html', {
        'complexes': complexes
    })

def _current_billboard_presence_for_complex(court_complex):
    """Return the current, deduplicated Billboard presence for one venue.

    This is a read-only Court Complex presentation helper.  It applies the
    existing Billboard current-presence windows to the canonical
    ``BillboardEntry`` source without creating or changing any presence data.
    """
    from billboard.models import BillboardEntry
    from courts.timezone_utils import get_court_local_now

    now = timezone.now()
    manual_cutoff = get_court_local_now(court_complex) - timedelta(hours=2)
    game_cutoff = now - timedelta(hours=6)
    candidates = (
        BillboardEntry.objects.filter(
            court_complex=court_complex,
            action_type='AT_COURTS',
            is_active=True,
        )
        .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
        .filter(
            Q(
                presence_source__in=(
                    BillboardEntry.PRESENCE_SOURCE_FRIENDLY,
                    BillboardEntry.PRESENCE_SOURCE_MATCH,
                ),
                created_at__gte=game_cutoff,
            )
            | Q(presence_source=BillboardEntry.PRESENCE_SOURCE_POST_GAME)
            | Q(
                presence_source=BillboardEntry.PRESENCE_SOURCE_MANUAL,
                created_at__gte=manual_cutoff,
            )
            | Q(presence_source__isnull=True, created_at__gte=manual_cutoff)
        )
        .order_by('-created_at')
    )

    present = []
    seen_codenames = set()
    for entry in candidates:
        codename = (entry.codename or '').upper()
        if codename and codename in seen_codenames:
            continue
        if codename:
            seen_codenames.add(codename)
        present.append(entry)
    return present


def _live_venue_context(court_complex):
    """Build presentation-only live data for a physical Court Complex."""
    if not court_complex.has_coordinates():
        return {
            'is_physical': False,
            'now_here': [],
            'going': [],
            'available_friendly_codenames': set(),
            'community_report': None,
        }

    from billboard.community_presence import CommunityPresenceReport
    from billboard.models import BillboardEntry
    from courts.timezone_utils import get_court_local_now
    from friendly_games.views import _eligible_friendly_court_players

    now_here = _current_billboard_presence_for_complex(court_complex)
    today = get_court_local_now(court_complex).date()
    going = list(
        BillboardEntry.objects.filter(
            court_complex=court_complex,
            action_type='GOING_TO_COURTS',
            is_active=True,
            going_status=BillboardEntry.GOING_STATUS_ACTIVE,
        )
        .filter(Q(scheduled_date__isnull=True) | Q(scheduled_date__gte=today))
        .order_by('arrival_at', 'created_at')
    )
    available_friendly_codenames = {
        player.codename_profile.codename.upper()
        for player in _eligible_friendly_court_players(court_complex)
        if getattr(player, 'codename_profile', None)
    }
    for entry in now_here:
        entry.is_available_for_friendly = (
            (entry.codename or '').upper() in available_friendly_codenames
        )

    return {
        'is_physical': True,
        'now_here': now_here,
        'going': going,
        'available_friendly_codenames': available_friendly_codenames,
        'community_report': CommunityPresenceReport.get_active_for_court(court_complex),
    }


def court_complex_detail(request, complex_id):
    """Detailed view of a court complex with read-only, per-venue live context."""
    complex_obj = get_object_or_404(CourtComplex, id=complex_id)
    ratings = complex_obj.ratings.all()
    photos = complex_obj.photos.all()[:4]  # Limit to 4 photos
    courts = complex_obj.courts.all()
    live_venue = _live_venue_context(complex_obj)

    return render(request, 'courts/court_complex_detail.html', {
        'complex': complex_obj,
        'ratings': ratings,
        'photos': photos,
        'courts': courts,
        'average_rating': complex_obj.average_rating(),
        'rating_count': complex_obj.rating_count(),
        'live_venue': live_venue,
    })

@require_POST
def submit_rating(request, complex_id):
    """Submit a rating for a court complex — player identity resolved from logged-in user"""
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'You must be logged in to submit a rating.'}, status=401)

    complex_obj = get_object_or_404(CourtComplex, id=complex_id)

    # Resolve codename from the session — never accept it from the client
    codename = request.session.get('player_codename', '').strip().upper()
    if not codename:
        return JsonResponse({'error': 'Your player session could not be identified. Please log in again or set your player profile.'}, status=400)

    try:
        data = json.loads(request.body)
        stars = float(data.get('stars', 0))
        comment = data.get('comment', '').strip()

        if not (0.5 <= stars <= 5.0):
            return JsonResponse({'error': 'Rating must be between 0.5 and 5.0'}, status=400)

        # Update or create rating (one per player per complex)
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

    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid data'}, status=400)
    except Exception:
        return JsonResponse({'error': 'An error occurred'}, status=500)

