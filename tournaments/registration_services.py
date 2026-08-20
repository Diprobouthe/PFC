"""Central Tournament registration eligibility and voucher redemption services.

This module controls only registration acceptance.  It does not create matches,
change tournament formats, or alter QR, scoring, Pool, or stage behavior.
"""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .models import (
    MeleePlayer,
    Tournament,
    TournamentRegistrationVoucher,
    TournamentRegistrationVoucherRedemption,
    TournamentTeam,
)


TOURNAMENT_CLOSED_MESSAGE = _("Tournament is not accepting registrations.")
TOURNAMENT_FULL_MESSAGE = _("Tournament is full.")
VOUCHER_REQUIRED_MESSAGE = _("A valid tournament voucher is required to register.")
VOUCHER_INVALID_MESSAGE = _("This tournament voucher is invalid, expired, inactive, or fully used.")
MELEE_CLOSED_MESSAGE = _("Registration is closed. Teams have already been generated.")


class TournamentRegistrationEligibilityError(ValidationError):
    """Raised when a registration cannot safely be accepted."""


def _lock_tournament(tournament):
    """Return the authoritative locked Tournament row for a registration write."""
    return Tournament.objects.select_for_update().get(pk=tournament.pk)


def _resolve_valid_voucher(*, tournament, voucher_code):
    """Lock and validate a voucher before a successful registration is persisted."""
    if tournament.registration_type != "voucher":
        return None

    code = (voucher_code or "").strip().upper()
    if not code:
        raise TournamentRegistrationEligibilityError(VOUCHER_REQUIRED_MESSAGE)

    voucher = (
        TournamentRegistrationVoucher.objects.select_for_update()
        .filter(tournament=tournament, code=code)
        .first()
    )
    if voucher is None or not voucher.is_currently_valid(timezone.now()):
        raise TournamentRegistrationEligibilityError(VOUCHER_INVALID_MESSAGE)
    return voucher


def _consume_voucher(*, voucher, team=None, player=None):
    """Create an audit redemption only after the registration write succeeds."""
    if voucher is None:
        return None
    return TournamentRegistrationVoucherRedemption.objects.create(
        voucher=voucher,
        team=team,
        player=player,
    )


@transaction.atomic
def register_team_for_tournament(*, team, tournament, voucher_code=None):
    """Create one Team registration after every centralized eligibility check.

    Existing registrations are idempotent and never need or consume another
    voucher.  New registrations lock the Tournament row so capacity and voucher
    usage limits remain correct under concurrent requests.
    """
    from .models import is_system_tournament_team, SYSTEM_TEAM_TOURNAMENT_MESSAGE

    tournament = _lock_tournament(tournament)
    if not tournament.is_active:
        raise TournamentRegistrationEligibilityError(TOURNAMENT_CLOSED_MESSAGE)
    if is_system_tournament_team(team):
        raise TournamentRegistrationEligibilityError(SYSTEM_TEAM_TOURNAMENT_MESSAGE)

    existing = TournamentTeam.objects.filter(tournament=tournament, team=team).first()
    if existing is not None:
        return existing, False, None

    if tournament.max_teams is not None:
        registered_count = TournamentTeam.objects.filter(tournament=tournament).count()
        if registered_count >= tournament.max_teams:
            raise TournamentRegistrationEligibilityError(TOURNAMENT_FULL_MESSAGE)

    voucher = _resolve_valid_voucher(tournament=tournament, voucher_code=voucher_code)
    registration = TournamentTeam.objects.create(tournament=tournament, team=team)
    redemption = _consume_voucher(voucher=voucher, team=team)
    return registration, True, redemption


@transaction.atomic
def register_melee_player_for_tournament(*, player, tournament, voucher_code=None):
    """Create one Mêlée player registration after centralized eligibility checks."""
    tournament = _lock_tournament(tournament)
    if not tournament.is_melee:
        raise TournamentRegistrationEligibilityError(
            _("This tournament is not configured for Mêlée mode.")
        )
    if not tournament.is_active:
        raise TournamentRegistrationEligibilityError(TOURNAMENT_CLOSED_MESSAGE)
    if tournament.melee_teams_generated:
        raise TournamentRegistrationEligibilityError(MELEE_CLOSED_MESSAGE)

    existing = MeleePlayer.objects.filter(tournament=tournament, player=player).first()
    if existing is not None:
        return existing, False, None

    if tournament.max_participants is not None:
        registered_count = MeleePlayer.objects.filter(tournament=tournament).count()
        if registered_count >= tournament.max_participants:
            raise TournamentRegistrationEligibilityError(TOURNAMENT_FULL_MESSAGE)

    voucher = _resolve_valid_voucher(tournament=tournament, voucher_code=voucher_code)
    registration = MeleePlayer.objects.create(
        tournament=tournament,
        player=player,
        original_team=player.team,
    )
    redemption = _consume_voucher(voucher=voucher, player=player)
    return registration, True, redemption
