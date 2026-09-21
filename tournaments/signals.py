"""Tournament automation triggered by genuine Match completion transitions."""

import logging

from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from matches.models import Match
from .automation_engine import TournamentEngine

logger = logging.getLogger('tournaments')


@receiver(pre_save, sender=Match)
def remember_previous_match_completion(sender, instance, **kwargs):
    """Do not rerun tournament progression on an unrelated save of a completed Match."""
    instance._pfc_new_completion = False
    if instance.status != 'completed' or not instance.pk:
        return
    previous_status = (
        Match.objects.filter(pk=instance.pk).values_list('status', flat=True).first()
    )
    instance._pfc_new_completion = (
        previous_status is not None and previous_status != 'completed'
    )


@receiver(post_save, sender=Match)
def handle_match_completion(sender, instance, created, update_fields=None, **kwargs):
    """Apply completed-Match progression once per observed status transition.

    Winner points are derived from persisted results, not incremented blindly;
    duplicate requests therefore cannot add another three points. The
    tournament engine and the Mêlée shuffle retain their existing safeguards.
    """
    if created or instance.status != 'completed':
        return
    if not getattr(instance, '_pfc_new_completion', False):
        return
    if not instance.tournament_id:
        return

    tournament = instance.tournament
    logger.info(
        'Match %s transitioned to completed for tournament %s',
        instance.pk, tournament.pk,
    )

    try:
        from .models import TournamentTeam
        if instance.winner_id:
            winner_tt = TournamentTeam.objects.filter(
                tournament=tournament, team_id=instance.winner_id,
            ).first()
            if winner_tt:
                # Recalculate from completed Match records and existing BYE
                # state instead of += 3 on every Match.save().
                winner_tt.update_swiss_stats()
                logger.info(
                    'Recalculated %s Swiss points: %s',
                    instance.winner_id, winner_tt.swiss_points,
                )
    except Exception:
        logger.exception(
            'Error calculating winner points for tournament %s', tournament.pk,
        )

    # A Super Mêlée roster must be persisted for the exact next Round before
    # the Swiss pairing generator is allowed to build next-Round Matches.
    if tournament.is_melee and tournament.shuffle_players_after_round and instance.round_id:
        from tournaments.shuffle_utils import prepare_automatic_super_melee_transition

        transition = prepare_automatic_super_melee_transition(
            tournament=tournament,
            completed_round=instance.round,
        )
        if not transition['success']:
            logger.error(
                'Super Mêlée transition after Round %s for tournament %s failed; '
                'skipping generic automation: %s',
                instance.round_id, tournament.pk, transition['message'],
            )
            return
        if transition.get('next_round_prepared'):
            logger.info(
                'Prepared Super Mêlée assignments after Round %s for tournament %s',
                instance.round_id, tournament.pk,
            )

    if tournament.automation_status != 'idle':
        logger.info(
            'Tournament %s automation is %s; skipping competing trigger',
            tournament.pk, tournament.automation_status,
        )
        return

    try:
        result = TournamentEngine(tournament).process_automation()
        if result:
            logger.info('Automation successful for tournament %s', tournament.pk)
        else:
            logger.warning('Automation returned False for tournament %s', tournament.pk)
    except Exception:
        logger.exception('Automation failed for tournament %s', tournament.pk)
