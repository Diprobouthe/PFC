"""Shared persistence helpers for tournament team sign-in."""

from django.utils import timezone

from tournaments.models import (
    TournamentTeam,
    is_system_tournament_team,
    SYSTEM_TEAM_TOURNAMENT_MESSAGE,
)

from .models import TeamTournamentSignin


def activate_team_tournament_signin(*, team, tournament):
    """Create or reactivate the exact records used by the existing Team Sign-in flow.

    A valid team is signed in by maintaining both records: the active
    ``TeamTournamentSignin`` used by the team dashboard and the
    ``TournamentTeam`` used by tournament views and scheduling.
    """
    if is_system_tournament_team(team):
        from django.core.exceptions import ValidationError
        raise ValidationError(SYSTEM_TEAM_TOURNAMENT_MESSAGE)

    signin, created = TeamTournamentSignin.objects.get_or_create(
        team=team,
        tournament=tournament,
        defaults={"is_active": True},
    )

    # The legacy form leaves an already-active sign-in unchanged, while an
    # inactive historical sign-in is reactivated with a fresh timestamp.
    if not created and not signin.is_active:
        signin.is_active = True
        signin.signed_in_at = timezone.now()
        signin.save(update_fields=["is_active", "signed_in_at"])

    tournament_team, tournament_team_created = TournamentTeam.objects.get_or_create(
        team=team,
        tournament=tournament,
        defaults={},
    )

    return {
        "signin": signin,
        "created": created,
        "tournament_team": tournament_team,
        "tournament_team_created": tournament_team_created,
    }
