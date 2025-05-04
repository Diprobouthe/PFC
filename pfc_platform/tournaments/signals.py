# signals.py for tournament automation triggers

import logging
from django.db.models.signals import post_save
from django.dispatch import receiver
from matches.models import Match
from .tasks import check_round_completion

logger = logging.getLogger("tournaments")

@receiver(post_save, sender=Match)
def handle_match_completion(sender, instance, created, update_fields=None, **kwargs):
    """Listens for Match saves and triggers round completion check if status becomes completed."""
    
    # Check if the status field was updated or if it's a new instance (less likely for completion)
    status_updated = update_fields is None or "status" in update_fields
    
    if status_updated and instance.status == "completed":
        logger.info(f"Match {instance.id} completed for tournament {instance.tournament_id}. Triggering round completion check.")
        try:
            # Ideally, run this asynchronously in a real-world scenario (e.g., using Celery)
            # For simplicity here, we call it directly.
            check_round_completion(instance.tournament_id)
        except Exception as e:
            # Log error but don't crash the save operation
            logger.exception(f"Error triggering check_round_completion for tournament {instance.tournament_id} after match {instance.id} completion: {e}")

