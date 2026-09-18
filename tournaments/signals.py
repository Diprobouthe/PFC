# signals.py for tournament automation triggers

import logging
from django.db.models.signals import post_save
from django.dispatch import receiver
from matches.models import Match
from .models import Tournament
from .automation_engine import TournamentEngine

logger = logging.getLogger("tournaments")

@receiver(post_save, sender=Match)
def handle_match_completion(sender, instance, created, update_fields=None, **kwargs):
    """Listens for Match saves and triggers round completion check if status becomes completed."""
    
    # Always check if status is completed, regardless of update_fields
    if instance.status == "completed" and instance.tournament:
        tournament = instance.tournament
        
        logger.info(f"Match {instance.id} completed for tournament {tournament.id}. Updating team stats and triggering automation.")
        
        # Update swiss_points for tournament teams
        try:
            from .models import TournamentTeam
            
            # Update winner's swiss_points
            if instance.winner:
                winner_tt = TournamentTeam.objects.filter(
                    tournament=tournament,
                    team=instance.winner
                ).first()
                
                if winner_tt:
                    winner_tt.swiss_points += 3  # Standard Swiss scoring: 3 points for win
                    winner_tt.save()
                    logger.info(f"Updated {instance.winner.name} swiss_points to {winner_tt.swiss_points}")
            
            # Update loser's swiss_points (0 points for loss, but we could add draw logic later)
            loser_team = None
            if instance.team1 == instance.winner:
                loser_team = instance.team2
            elif instance.team2 == instance.winner:
                loser_team = instance.team1
                
            if loser_team:
                loser_tt = TournamentTeam.objects.filter(
                    tournament=tournament,
                    team=loser_team
                ).first()
                
                if loser_tt:
                    # Loser gets 0 points (no change needed, but we log it)
                    logger.info(f"Match completed: {loser_team.name} remains at {loser_tt.swiss_points} swiss_points")
                    
        except Exception as e:
            logger.exception(f"Error updating swiss_points for tournament {tournament.id}: {e}")

        # A Super Mêlée must prepare its next concrete Round assignment before
        # generic automation creates that Round's Matches. This receiver runs
        # synchronously inside the final ``match.save()`` call, so the old
        # view-level shuffle was necessarily too late: automation had already
        # copied the prior MeleePlayer.assigned_team values.
        if tournament.is_melee and tournament.shuffle_players_after_round and instance.round_id:
            from tournaments.shuffle_utils import prepare_automatic_super_melee_transition

            transition = prepare_automatic_super_melee_transition(
                tournament=tournament,
                completed_round=instance.round,
            )
            if not transition["success"]:
                logger.error(
                    "Super Mêlée transition after Round %s for tournament %s "
                    "was not prepared; generic next-round automation is skipped: %s",
                    instance.round_id,
                    tournament.id,
                    transition["message"],
                )
                return
            if transition.get("next_round_prepared"):
                logger.info(
                    "Prepared Super Mêlée assignments after Round %s before "
                    "generic Match generation for tournament %s.",
                    instance.round_id,
                    tournament.id,
                )
        
        # Only trigger automation if tournament is idle
        current_status = getattr(tournament, 'automation_status', 'idle')
        
        if current_status != 'idle':
            logger.info(f"Tournament {tournament.id} automation is not idle (status: {current_status}). Skipping automation.")
            return
        
        try:
            # Use the fixed automation engine
            engine = TournamentEngine(tournament)
            result = engine.process_automation()
            
            if result:
                logger.info(f"✅ Automation successful for tournament {tournament.id}")
            else:
                logger.warning(f"⚠️ Automation returned False for tournament {tournament.id}")
                
        except Exception as e:
            logger.exception(f"❌ Error in automation for tournament {tournament.id}: {e}")
            # Don't set error status - let the engine handle it
