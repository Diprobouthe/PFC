"""One-time Court Complex presence for a generated Mêlée tournament.

The ordinary Match lifecycle must not create or retire player presence.
"""
import logging
from datetime import timedelta

from django.utils import timezone

from billboard.models import BillboardEntry
from courts.models import CourtComplex
from friendly_games.models import PlayerCodename
from tournaments.models import Tournament, TournamentCourt

logger = logging.getLogger(__name__)


def register_melee_tournament_presence(tournament_id):
    """Register the generated roster once, after the generation transaction commits.

    No Court or CourtComplex rows are locked. A missing/ambiguous venue is
    logged and skipped, never guessed from an unrelated global Court.
    """
    tournament = Tournament.objects.get(pk=tournament_id)
    if not tournament.is_melee or not tournament.melee_teams_generated:
        return 0

    court_ids = list(
        TournamentCourt.objects.filter(tournament_id=tournament_id)
        .values_list("court_id", flat=True)
    )
    if not court_ids:
        logger.warning("Melee %s: no configured courts; skipping presence", tournament_id)
        return 0
    complex_ids = list(
        CourtComplex.objects.filter(courts__id__in=court_ids)
        .values_list("id", flat=True).distinct()
    )
    if len(complex_ids) != 1:
        logger.warning(
            "Melee %s: expected exactly one Court Complex, got %s; skipping presence",
            tournament_id, complex_ids,
        )
        return 0

    player_ids = list(tournament.melee_players.values_list("player_id", flat=True))
    codenames = set(
        PlayerCodename.objects.filter(player_id__in=player_ids)
        .values_list("codename", flat=True)
    )
    if not codenames:
        return 0

    complex_id = complex_ids[0]
    game_ref = f"tournament:{tournament_id}"
    existing = set(
        BillboardEntry.objects.filter(
            court_complex_id=complex_id,
            action_type="AT_COURTS",
            is_active=True,
            game_ref=game_ref,
        ).values_list("codename", flat=True)
    )
    now = timezone.now()
    # The configured tournament schedule is authoritative. Keep a one-hour
    # post-event buffer without introducing another duration setting.
    expiry = tournament.end_date + timedelta(hours=1)
    if expiry <= now:
        logger.warning("Melee %s: scheduled presence already expired", tournament_id)
        return 0
    rows = [
        BillboardEntry(
            codename=codename,
            court_complex_id=complex_id,
            action_type="AT_COURTS",
            is_active=True,
            presence_source=BillboardEntry.PRESENCE_SOURCE_MATCH,
            game_ref=game_ref,
            expires_at=expiry,
            message="Melee tournament participation",
        )
        for codename in sorted(codenames - existing)
    ]
    if rows:
        BillboardEntry.objects.bulk_create(rows, batch_size=500)
    return len(rows)
