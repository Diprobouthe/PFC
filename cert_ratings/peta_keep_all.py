"""Player-owned, pre-start Keep All selection for PETA events."""
from django.db import transaction

from .peta_models import PetaCompetitor, PetaEvent, PetaEventEntry, PetaKeepAllChoice


def keep_all_state(tournament, player):
    event = PetaEvent.objects.select_related("series").filter(tournament=tournament).first()
    if event is None or not player:
        return None
    from tournaments.models import MeleePlayer
    registered = MeleePlayer.objects.filter(tournament=tournament, player=player).exists()
    competitor = PetaCompetitor.objects.filter(series=event.series, player=player).first()
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
        "used": bool(competitor and competitor.exception_used),
        "locked": locked,
        "can_edit": registered and not locked and not bool(competitor and competitor.exception_used),
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
        competitor, _ = PetaCompetitor.objects.get_or_create(
            series=event.series, player_id=player_id
        )
        if competitor.exception_used:
            raise ValueError("Your one Keep All has already been used in this series.")
        if enabled and PetaKeepAllChoice.objects.filter(
            event__series=event.series, player_id=player_id,
            enabled=True,
        ).exclude(event=event).exists():
            raise ValueError("Keep All is already selected for another meeting in this series.")
        PetaKeepAllChoice.objects.update_or_create(
            event=event, player_id=player_id, defaults={"enabled": enabled}
        )
