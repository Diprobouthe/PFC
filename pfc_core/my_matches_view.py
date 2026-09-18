"""Legacy ``/my-matches/old/`` compatibility route.

The original view duplicated Player.team-based tournament routing.  P3 keeps
its public URL but delegates directly to the Match-scoped Smart Router so the
same MatchPlayer → exact-round assignment → legacy fallback precedence applies.
"""

from pfc_core.smart_router import resolve_decision_url


def my_active_matches(request):
    """Serve the historical endpoint through the authoritative Smart Router."""
    return resolve_decision_url(request)
