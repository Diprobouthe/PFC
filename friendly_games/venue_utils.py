"""Friendly creator venue policy based on current Billboard court presence.

Any valid current AT_COURTS presence at a physical CourtComplex permits
creating a Friendly there, regardless of how presence was established.
The non-geolocated complex remains the virtual venue.
"""

from django.utils.translation import gettext_lazy as _

from billboard.presence_query import current_court_presence
from courts.models import CourtComplex
from pfc_core.session_utils import CodenameSessionManager


class FriendlyVenueError(ValueError):
    """Raised when a Friendly venue is missing, invalid, or not permitted."""


def _current_creator_presence_complex(request, creator_codename=None):
    """Return the newest physical complex where the creator is currently present.

    Use the same source-aware presence windows as the court-complex display.
    Never authorize a venue solely from an inactive or expired record.
    """
    codename = creator_codename or CodenameSessionManager.get_logged_in_codename(request)
    if not codename:
        return None

    physical_complexes = [
        complex_obj for complex_obj in CourtComplex.objects.order_by('name')
        if complex_obj.has_coordinates()
    ]
    latest = None
    for complex_obj in physical_complexes:
        entry = current_court_presence(complex_obj).filter(
            codename__iexact=codename,
        ).first()
        if entry and (latest is None or entry.created_at > latest.created_at):
            latest = entry
    return latest.court_complex if latest else None


def get_allowed_friendly_complexes(request, creator_codename=None):
    """Return the only Court Complexes the current Friendly creator may use.

    The configured data model defines a physical complex as one with both GPS
    coordinates.  Exactly one non-geolocated complex is required as the virtual
    Friendly venue.  A creator with current Billboard presence may use that exact physical
    complex plus the virtual complex; others may use only the virtual complex.
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
    physical_complex = _current_creator_presence_complex(request, creator_codename=creator_codename)
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
