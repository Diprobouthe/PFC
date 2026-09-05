"""Friendly-only creator venue policy.

A physical Friendly venue is permitted only when the creator has a current
manual AT_COURTS presence at that geolocated CourtComplex.  The manual check-in
flow is already GPS/proximity protected.  The one non-geolocated CourtComplex
is the existing virtual Friendly venue.
"""

from datetime import timedelta

from django.utils.translation import gettext_lazy as _

from billboard.models import BillboardEntry
from courts.models import CourtComplex
from courts.timezone_utils import get_court_local_now
from pfc_core.session_utils import CodenameSessionManager


class FriendlyVenueError(ValueError):
    """Raised when a Friendly venue is missing, invalid, or not permitted."""


def _current_creator_gps_complex(request, creator_codename=None):
    """Return the creator's newest current manual presence at a physical complex.

    Manual ``AT_COURTS`` presence is the existing GPS-protected "I'm Here"
    result.  Friendly-, tournament-, and post-game-generated presence never
    authorizes a physical Friendly venue.
    """
    codename = creator_codename or CodenameSessionManager.get_logged_in_codename(request)
    if not codename:
        return None

    entries = (
        BillboardEntry.objects.filter(
            codename=codename.upper(),
            action_type='AT_COURTS',
            presence_source=BillboardEntry.PRESENCE_SOURCE_MANUAL,
            is_active=True,
        )
        .select_related('court_complex')
        .order_by('-created_at')
    )
    for entry in entries:
        court_complex = entry.court_complex
        if not court_complex.has_coordinates():
            continue
        if entry.created_at >= get_court_local_now(court_complex) - timedelta(hours=2):
            return court_complex
    return None


def get_allowed_friendly_complexes(request, creator_codename=None):
    """Return the only Court Complexes the current Friendly creator may use.

    The configured data model defines a physical complex as one with both GPS
    coordinates.  Exactly one non-geolocated complex is required as the virtual
    Friendly venue.  A creator with current GPS-protected presence may use that
    exact physical complex plus the virtual complex; every other creator may
    use only the virtual complex.
    """
    virtual_complexes = [
        court_complex
        for court_complex in CourtComplex.objects.order_by('name')
        if not court_complex.has_coordinates()
    ]
    if len(virtual_complexes) != 1:
        raise FriendlyVenueError(
            _('Friendly venue configuration requires exactly one non-geolocated Court Complex.')
        )

    virtual_complex = virtual_complexes[0]
    physical_complex = _current_creator_gps_complex(request, creator_codename=creator_codename)
    if physical_complex:
        return [physical_complex, virtual_complex]
    return [virtual_complex]


def get_friendly_venue_context(request):
    """Return form-safe allowed venue data without permitting any fallback venue."""
    try:
        allowed_complexes = get_allowed_friendly_complexes(request)
    except FriendlyVenueError as exc:
        return {
            'all_complexes': CourtComplex.objects.none(),
            'preferred_complex_id': None,
            'preferred_court_id': None,
            'friendly_venue_error': str(exc),
        }

    default_complex = allowed_complexes[0]
    preferred_court_id = request.session.get('preferred_court_id')
    if preferred_court_id and not default_complex.courts.filter(pk=preferred_court_id).exists():
        preferred_court_id = None

    return {
        'all_complexes': allowed_complexes,
        'preferred_complex_id': default_complex.pk,
        'preferred_court_id': preferred_court_id,
        'friendly_venue_error': '',
    }
