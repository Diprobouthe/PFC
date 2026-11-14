"""Player-owned, pre-start Keep All selection for PETA events."""
from django.db import transaction

from .peta_models import PetaCompetitor, PetaEvent, PetaEventEntry, PetaKeepAllChoice


def prior_participation_count(event, player_id):
    """Count distinct completed earlier PETA events with a frozen player entry."""
    return PetaEventEntry.objects.filter(
        event__series=event.series,
        event__ordinal__lt=event.ordinal,
        event__settled_at__isnull=False,
        player_id=player_id,
    ).count()


def keep_all_state(tournament, player):
    event = PetaEvent.objects.select_related("series").filter(tournament=tournament).first()
    if event is None or not player:
        return None
    from tournaments.models import MeleePlayer
    registered = MeleePlayer.objects.filter(tournament=tournament, player=player).exists()
    prior_count = prior_participation_count(event, player.pk)
    choice = PetaKeepAllChoice.objects.filter(event=event, player=player).first()
    # Once the roster is frozen / teams generated, the choice is immutable.
    locked = bool(
        event.settled_at or tournament.melee_teams_generated
        or PetaEventEntry.objects.filter(event=event).exists()
        or tournament.rounds.filter(matches__isnull=False).exists()
    )
    return {
        "event": event, "registered": registered,
        "enabled": bool(choice and choice.enabled),
        "prior_participations": prior_count,
        "eligible": event.ordinal >= 5 and prior_count >= 3,
        "locked": locked,
        "can_edit": registered and not locked and event.ordinal >= 5 and prior_count >= 3,
    }


def set_keep_all_choice(tournament_id, player_id, enabled):
    """Serialize with tournament roster generation; never change after freeze."""
    from tournaments.models import MeleePlayer, Tournament
    with transaction.atomic():
        tournament = Tournament.objects.select_for_update().get(pk=tournament_id)
        event = PetaEvent.objects.select_for_update().get(tournament=tournament)
        if not MeleePlayer.objects.filter(tournament=tournament, player_id=player_id).exists():
            raise ValueError("Register for this Super Mêlée first.")
        if (event.settled_at or tournament.melee_teams_generated
                or PetaEventEntry.objects.filter(event=event).exists()
                or tournament.rounds.filter(matches__isnull=False).exists()):
            raise ValueError("Keep All is locked: this Super Mêlée has started preparation.")
        if enabled and event.ordinal < 5:
            raise ValueError("Keep All is available only in events 5 through 8.")
        if enabled and prior_participation_count(event, player_id) < 3:
            raise ValueError("Keep All requires three completed previous PETA events.")
        PetaKeepAllChoice.objects.update_or_create(
            event=event, player_id=player_id, defaults={"enabled": enabled}
        )
