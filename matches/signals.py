"""
Django signals for automatic LiveScoreboard creation.
This ensures that every match gets a live scoreboard without modifying existing logic.
"""

from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Match, LiveScoreboard
import logging

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Match)
def create_live_scoreboard_for_tournament_match(sender, instance, created, **kwargs):
    """
    Automatically create a LiveScoreboard when a tournament Match is created.
    This signal runs AFTER the match is saved, so it doesn't interfere with match creation.
    """
    if created:  # Only for newly created matches
        try:
            # Check if a scoreboard already exists (shouldn't happen, but safety first)
            if not hasattr(instance, 'live_scoreboard'):
                LiveScoreboard.objects.create(
                    tournament_match=instance,
                    is_active=True
                )
                logger.info(f"Created live scoreboard for tournament match {instance.id}")
        except Exception as e:
            # Log the error but don't let it break match creation
            logger.error(f"Failed to create live scoreboard for tournament match {instance.id}: {e}")


# Signal for friendly games - we need to import the model dynamically to avoid circular imports
@receiver(post_save, sender='friendly_games.FriendlyGame')
def create_live_scoreboard_for_friendly_game(sender, instance, created, **kwargs):
    """
    Automatically create a LiveScoreboard when a FriendlyGame is created.
    This signal runs AFTER the game is saved, so it doesn't interfere with game creation.
    """
    if created:  # Only for newly created games
        try:
            # Check if a scoreboard already exists (shouldn't happen, but safety first)
            if not hasattr(instance, 'live_scoreboard'):
                LiveScoreboard.objects.create(
                    friendly_game=instance,
                    is_active=True
                )
                logger.info(f"Created live scoreboard for friendly game {instance.id}")
        except Exception as e:
            # Log the error but don't let it break game creation
            logger.error(f"Failed to create live scoreboard for friendly game {instance.id}: {e}")




# Signal for automatic court assignment when courts become available
@receiver(post_save, sender='courts.Court')
def auto_assign_waiting_matches_when_court_available(sender, instance, created, **kwargs):
    """
    Automatically assign waiting matches to courts when a court becomes available.
    This signal runs when a Court's is_available field changes to True.
    """
    # Only trigger if court becomes available (not when created)
    if not created and instance.is_available:
        try:
            from .models import Match
            from .utils import auto_assign_court
            from django.utils import timezone
            
            # Find matches waiting for courts
            waiting_matches = Match.objects.filter(
                status="pending_verification",
                waiting_for_court=True
            ).order_by("created_at")
            
            if waiting_matches.exists():
                logger.info(f"Court {instance.name} became available, checking {waiting_matches.count()} waiting matches")
                
                for match in waiting_matches:
                    # Try to assign this court or any other available court
                    assigned_court = auto_assign_court(match)
                    
                    if assigned_court:
                        # Court assigned - activate the match
                        match.status = "active"
                        # Use court-local time so start_time reflects the venue's local clock
                        try:
                            from courts.timezone_utils import get_court_local_now
                            _complex = assigned_court.courtcomplex_set.first()
                            match.start_time = get_court_local_now(_complex) if _complex else timezone.now()
                        except Exception:
                            match.start_time = timezone.now()
                        match.waiting_for_court = False
                        match.save()
                        
                        # Auto-register players to Billboard when match starts
                        try:
                            from .views import auto_register_players_to_billboard
                            auto_register_players_to_billboard(match)
                        except Exception as e:
                            logger.error(f"Failed to auto-register players for match {match.id} upon court assignment: {e}")
                        
                        logger.info(f"Auto-assigned court {assigned_court.name} to waiting match {match.id} and activated it")
                        
                        # Only assign one match per court availability event
                        break
                    
        except Exception as e:
            # Log the error but don't let it break court operations
            logger.error(f"Failed to auto-assign waiting matches when court {instance.name} became available: {e}")



# ---------------------------------------------------------------------------
# VS Mode: update encounter points when a sub-game completes
# ---------------------------------------------------------------------------

@receiver(post_save, sender=Match)
def update_vs_encounter_on_match_complete(sender, instance, created, **kwargs):
    """
    When a VS sub-game Match transitions to 'completed', recalculate the
    parent VSEncounter's point totals and update TournamentTeam.vs_points.

    This signal is intentionally isolated from all non-VS matches:
      - It exits immediately if the match has no vs_encounter FK.
      - It does NOT touch any Mêlée, Super Mêlée, or Friendly Game logic.
    """
    if created:
        return  # Only care about status changes, not new match creation

    if instance.status != "completed":
        return  # Only act when the match just became completed

    if not instance.vs_encounter_id:
        return  # Not a VS sub-game — do nothing

    try:
        from tournaments.vs_utils import update_vs_encounter_points
        update_vs_encounter_points(instance.vs_encounter)
    except Exception as exc:
        logger.error(
            "VS Mode: failed to update encounter points for match %s (encounter %s): %s",
            instance.pk,
            instance.vs_encounter_id,
            exc,
        )
