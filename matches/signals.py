"""
Django signals for automatic LiveScoreboard creation.
This ensures that every match gets a live scoreboard without modifying existing logic.
"""

from django.db import transaction
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


@receiver(post_save, sender=Match)
def notify_new_actionable_match(sender, instance, created, **kwargs):
    """Broadcast a new pending Match only after its creation commits successfully."""
    if not created or instance.status != "pending" or not instance.team1_id or not instance.team2_id:
        return

    match_id = instance.pk

    def deliver():
        try:
            from pfc_events.signals import notify_match_state_changed
            from pfc_events.push_notifications import notify_match_action_required
            from .melee_roster_resolution import players_for_match_team
            match = Match.objects.select_related("team1", "team2").get(pk=match_id)
            notify_match_state_changed(match_id, match.status, match=match)
            players = (
                list(players_for_match_team(match, match.team1))
                + list(players_for_match_team(match, match.team2))
            )
            notify_match_action_required(players, "new_match", "match", match_id)
        except Exception as exc:
            logger.warning("Failed to announce new actionable match %s: %s", match_id, exc)

    transaction.on_commit(deliver)


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
    # The lifecycle service owns Court locks and queue promotion. Delay the
    # attempt until the availability change has committed so this signal never
    # competes with the transaction that released the Court.
    if getattr(instance, "_lifecycle_skip_auto_promotion", False):
        return

    if not created and instance.is_available:
        court_id = instance.pk

        def promote_after_commit():
            try:
                from .lifecycle import promote_one_waiting_match

                promote_one_waiting_match(preferred_court_id=court_id)
            except Exception:
                logger.exception(
                    "Failed to promote a waiting Match after Court %s became available",
                    court_id,
                )

        transaction.on_commit(promote_after_commit)



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
    # The Match lifecycle transition calls ``update_vs_encounter_points`` once
    # after it claims the completed Match. A generic post-save hook cannot tell
    # a first completion from a later save and therefore must not repeat the
    # projection.
    return
