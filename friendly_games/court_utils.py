"""
friendly_games/court_utils.py
─────────────────────────────
Court assignment logic for friendly games.

Priority chain (highest → lowest):
  1. User explicitly selected a specific court
  2. User explicitly selected a complex (auto-pick a court from it)
  3. User's preferred complex stored in session (auto-pick a court)
  4. Admin default complex from settings (FRIENDLY_GAME_DEFAULT_COURT_COMPLEX_ID)
  5. First available CourtComplex in the database
  6. No court assigned (game proceeds without court context)

User preference is stored in the session under the key 'preferred_court_complex_id'.
"""

import logging
from django.conf import settings
from courts.models import Court, CourtComplex

logger = logging.getLogger(__name__)

SESSION_PREF_COMPLEX_KEY = 'preferred_court_complex_id'
SESSION_PREF_COURT_KEY = 'preferred_court_id'


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def resolve_court_assignment(request, complex_id=None, court_id=None):
    """
    Resolve the (court_complex, court) pair for a new friendly game.

    Parameters
    ----------
    request      : HttpRequest  – used to read/write session preferences
    complex_id   : int | None   – user-selected complex PK (from POST)
    court_id     : int | None   – user-selected court PK (from POST)

    Returns
    -------
    (CourtComplex | None, Court | None)
    """
    # 1. User selected a specific court ──────────────────────────────────────
    if court_id:
        try:
            court = Court.objects.get(pk=court_id)
            court_complex = court.courtcomplex_set.first()
            if court_complex:
                _save_preference(request, court_complex.pk, court.pk)
                return court_complex, court
        except Court.DoesNotExist:
            logger.warning(f"Court id={court_id} not found, falling through")

    # 2. User selected a complex (pick first available court) ─────────────────
    if complex_id:
        result = _pick_court_from_complex(complex_id)
        if result[0]:
            _save_preference(request, result[0].pk, result[1].pk if result[1] else None)
            return result

    # 3. User's session preference ────────────────────────────────────────────
    pref_complex_id = request.session.get(SESSION_PREF_COMPLEX_KEY)
    if pref_complex_id:
        result = _pick_court_from_complex(pref_complex_id)
        if result[0]:
            return result

    # 4. Admin default complex ────────────────────────────────────────────────
    admin_default_id = getattr(settings, 'FRIENDLY_GAME_DEFAULT_COURT_COMPLEX_ID', None)
    if admin_default_id:
        result = _pick_court_from_complex(admin_default_id)
        if result[0]:
            return result

    # 5. First available complex in DB ────────────────────────────────────────
    first_complex = CourtComplex.objects.first()
    if first_complex:
        result = _pick_court_from_complex(first_complex.pk)
        if result[0]:
            return result

    # 6. No court context available ───────────────────────────────────────────
    logger.info("No court complex available for friendly game — proceeding without court assignment")
    return None, None


def get_court_context_for_form(request):
    """
    Return context data needed to render the court selection UI.

    Returns a dict with:
      - all_complexes        : QuerySet[CourtComplex]
      - preferred_complex_id : int | None
      - preferred_court_id   : int | None
    """
    return {
        'all_complexes': CourtComplex.objects.prefetch_related('courts').all(),
        'preferred_complex_id': request.session.get(SESSION_PREF_COMPLEX_KEY),
        'preferred_court_id': request.session.get(SESSION_PREF_COURT_KEY),
    }


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
