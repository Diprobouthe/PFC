from .models import Match
from courts.models import Court # Ensure Court is imported
import logging

logger = logging.getLogger("matches") # Use the logger name defined in settings

def auto_assign_court(match):
    """Automatically assign a court to a match

    This function prioritizes tournament-specific courts that are not currently in use.
    If no tournament-specific courts are available, it falls back to any available court.
    """
    # Check if match already has a court
    if match.court:
        return None

    # Get tournament-specific courts first
    tournament_courts = match.tournament.tournamentcourt_set.all().select_related("court")
    tournament_court_ids = [tc.court.id for tc in tournament_courts]

    # Get courts that are not currently in use by active matches
    active_matches = Match.objects.filter(status="active").exclude(id=match.id)
    courts_in_use = [m.court.id for m in active_matches if m.court]

    # First try to assign a tournament-specific court that's not in use
    all_courts = Court.objects.all() # Explicitly query all courts
    available_tournament_courts = all_courts.filter(
        id__in=tournament_court_ids,
        is_active=False  # Check if the court itself is marked as available
    ).exclude(id__in=courts_in_use).order_by("number")  # Exclude courts in use by other active matches
    logger.debug(f"Available tournament-specific courts (is_active=False): {[c.id for c in available_tournament_courts]}")

    if available_tournament_courts.exists():
        court = available_tournament_courts.first()
        match.court = court
        match.save()
        court.is_active = True # Mark court as in use
        court.save()
        logger.info(f"Assigned tournament court {court.id} to match {match.id}")
        return court

    # If no tournament-specific courts are available, try any available court
    all_courts = Court.objects.all() # Explicitly query all courts
    available_courts = all_courts.filter(
        is_active=False  # Check if the court itself is marked as available
    ).exclude(id__in=courts_in_use).order_by("number") # Exclude courts in use by other active matches
    logger.debug(f"Available general courts (is_active=False): {[c.id for c in available_courts]}")

    if available_courts.exists():
        court = available_courts.first()
        match.court = court
        match.save()
        court.is_active = True # Mark court as in use
        court.save()
        logger.info(f"Assigned general court {court.id} to match {match.id}")
        return court

    return None

def get_court_assignment_status(match):
    """Get a status message about court assignment for a match

    This function returns a user-friendly message about the court assignment status,
    including whether the court is a tournament-specific court or not.
    """
    if not match.court:
        return "No court assigned"

    # Check if this is a tournament-specific court
    tournament_courts = match.tournament.tournamentcourt_set.all().select_related("court")
    tournament_court_ids = [tc.court.id for tc in tournament_courts]

    if match.court.id in tournament_court_ids:
        return f"Assigned to tournament-specific Court {match.court.number}"
    else:
        return f"Assigned to Court {match.court.number} (non-tournament court)"


