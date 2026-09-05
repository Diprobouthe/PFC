"""Friendly-only Court assignment constrained by the creator venue policy.

The caller supplies the Court Complexes that the creator is authorized to use.
There is intentionally no global, session, default-setting, or first-database
fallback: a submitted Court can never change the selected authorized Complex.
"""

import logging

from django.utils.translation import gettext_lazy as _
from courts.models import CourtComplex
from .venue_utils import FriendlyVenueError, get_friendly_venue_context

logger = logging.getLogger(__name__)

SESSION_PREF_COMPLEX_KEY = 'preferred_court_complex_id'
SESSION_PREF_COURT_KEY = 'preferred_court_id'


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def resolve_court_assignment(request, allowed_complexes, complex_id=None, court_id=None):
    """Resolve a Friendly venue without allowing a Court to change its Complex.

    ``allowed_complexes`` is computed from the creator's current GPS-protected
    manual presence plus the single non-geolocated virtual complex.  A selected
    Court is looked up only through the selected allowed Complex, so a global
    Court ID cannot override, redirect, or broaden the Friendly venue.
    """
    allowed_by_id = {court_complex.pk: court_complex for court_complex in allowed_complexes}
    if not allowed_by_id:
        raise FriendlyVenueError(_('No permitted Court Complex is available for this Friendly Game.'))

    # The form always selects a permitted default.  Retain that safe default for
    # a malformed empty POST, but never use session/settings/database fallbacks.
    selected_complex_id = complex_id or next(iter(allowed_by_id))
    selected_complex = allowed_by_id.get(selected_complex_id)
    if selected_complex is None:
        raise FriendlyVenueError(_('The selected Court Complex is not permitted for this Friendly Game.'))

    if court_id:
        court = selected_complex.courts.filter(pk=court_id).first()
        if court is None:
            raise FriendlyVenueError(_('The selected Court does not belong to the selected Court Complex.'))
        _save_preference(request, selected_complex.pk, court.pk)
        return selected_complex, court

    resolved_complex, court = _pick_court_from_complex(selected_complex.pk)
    _save_preference(request, selected_complex.pk, court.pk if court else None)
    return selected_complex, court


def get_court_context_for_form(request):
    """
    Return context data needed to render the court selection UI.

    Returns a dict with:
      - all_complexes        : QuerySet[CourtComplex]
      - preferred_complex_id : int | None
      - preferred_court_id   : int | None
    """
    return get_friendly_venue_context(request)


def courts_for_complex_json(complex_id):
    """
    Return a list of dicts [{id, number, is_available}] for the given complex.
    Used by the AJAX endpoint that refreshes the court dropdown when the
    complex selector changes.
    """
    try:
        cc = CourtComplex.objects.get(pk=complex_id)
        return [
            {'id': c.pk, 'number': c.number, 'is_available': c.is_available}
            for c in cc.courts.order_by('number')
        ]
    except CourtComplex.DoesNotExist:
        return []


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _pick_court_from_complex(complex_id):
    """
    Given a complex PK, return (CourtComplex, Court | None).
    Prefers an available court; falls back to any court in the complex.
    Returns (None, None) if the complex doesn't exist.
    """
    try:
        cc = CourtComplex.objects.get(pk=complex_id)
    except CourtComplex.DoesNotExist:
        logger.warning(f"CourtComplex id={complex_id} not found")
        return None, None

    # Prefer an available court
    court = cc.courts.filter(is_available=True).order_by('number').first()
    if not court:
        # Fall back to any court in the complex
        court = cc.courts.order_by('number').first()

    return cc, court


def _save_preference(request, complex_id, court_id=None):
    """Persist the user's court preference in the session."""
    request.session[SESSION_PREF_COMPLEX_KEY] = complex_id
    if court_id:
        request.session[SESSION_PREF_COURT_KEY] = court_id
    elif SESSION_PREF_COURT_KEY in request.session:
        del request.session[SESSION_PREF_COURT_KEY]
