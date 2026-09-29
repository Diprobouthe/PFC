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
    """Compatibility receiver retained without lifecycle side effects.

    Tournament progression is now claimed by ``MatchLifecycleTransition`` after
    the official result commit.  A generic ``post_save`` receiver cannot
    distinguish a first completion from a later presentation/edit save, so it
    must not update points, shuffle, or generate Rounds.
    """
    if not created and instance.status == "completed":
        logger.debug(
            "Match %s completed-save observed; lifecycle follow-up is handled by its transition record.",
            instance.id,
        )
