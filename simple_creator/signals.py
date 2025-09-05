from django.db.models.signals import post_save
from django.dispatch import receiver
from matches.models import Match
from .models import SimpleTournament


@receiver(post_save, sender=Match)
def check_tournament_completion(sender, instance, **kwargs):
    """
    Check if a match completion triggers tournament completion
    and automatically cleanup if needed
    """
    # Only process if match is completed
    if instance.status != 'completed':
        return
    
    # Check if this match belongs to a simple tournament
    tournament = instance.tournament
    if not tournament:
        return
    
    try:
        simple_tournament = SimpleTournament.objects.get(tournament=tournament)
        
        # Check if tournament is now complete and trigger cleanup
        if not simple_tournament.is_completed:
            simple_tournament.check_completion()
            
    except SimpleTournament.DoesNotExist:
        # This is not a simple tournament, ignore
        pass
    except Exception as e:
        # Log error but don't break the system
        import logging
        logger = logging.getLogger('simple_creator')
        logger.error(f"Error checking tournament completion for match {instance.id}: {e}")


def auto_cleanup_completed_tournaments():
    """
    Function to be called periodically to cleanup completed tournaments
    This can be called from a cron job or scheduled task
    """
    from .models import SimpleTournament
    
    # Find tournaments that are completed but not cleaned up
    tournaments_to_cleanup = SimpleTournament.objects.filter(
        is_completed=True,
        players_restored=False
    )
    
    cleanup_count = 0
    for simple_tournament in tournaments_to_cleanup:
        try:
            simple_tournament.auto_cleanup()
            cleanup_count += 1
        except Exception as e:
            import logging
            logger = logging.getLogger('simple_creator')
            logger.error(f"Error during auto cleanup for tournament {simple_tournament.tournament.id}: {e}")
    
    return cleanup_count

