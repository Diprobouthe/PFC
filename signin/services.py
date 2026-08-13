"""Shared persistence service for tournament team sign-in and registration."""

from django.db import transaction
from django.utils import timezone

from tournaments.models import (
    Tournament,
    TournamentTeam,
    VSEncounter,
    is_system_tournament_team,
    SYSTEM_TEAM_TOURNAMENT_MESSAGE,
)
from tournaments.vs_utils import (
    generate_vs_pending_matches,
    get_vs_num_matches,
    is_vs_tournament,
)

from .models import TeamTournamentSignin


VS_TWO_TEAM_MESSAGE = "A VS tournament accepts exactly two teams."


@transaction.atomic
def activate_team_tournament_signin(*, team, tournament):
    """Create or reactivate the records used by the existing Team Sign-in flow.

    Normal tournaments retain their existing behaviour.  For a tournament
    explicitly marked as VS, this shared persistence path additionally
    enforces the two-team limit and creates one encounter with the configured
    number of open-format pending matches when the second team signs in.
    """
    if is_system_tournament_team(team):
        from django.core.exceptions import ValidationError
        raise ValidationError(SYSTEM_TEAM_TOURNAMENT_MESSAGE)

    # The row lock serialises concurrent registrations for a VS tournament so
    # a third team cannot slip through while the encounter is being created.
    tournament = Tournament.objects.select_for_update().get(pk=tournament.pk)
    is_vs_mode = is_vs_tournament(tournament)

    existing_tournament_team = TournamentTeam.objects.filter(
        team=team,
        tournament=tournament,
    ).first()
    if is_vs_mode and existing_tournament_team is None:
        registered_count = TournamentTeam.objects.filter(
            tournament=tournament,
            is_active=True,
        ).count()
        if registered_count >= 2:
            from django.core.exceptions import ValidationError
            raise ValidationError(VS_TWO_TEAM_MESSAGE)

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

    vs_encounter = None
    vs_matches_created = 0
    if is_vs_mode:
        registered_teams = list(
            TournamentTeam.objects.filter(
                tournament=tournament,
                is_active=True,
            )
            .select_related("team")
            .order_by("created_at", "id")
        )
        if len(registered_teams) == 2:
            # There is deliberately one encounter per VS tournament.  The
            # tournament lock above makes this creation idempotent even when
            # the two registrations arrive concurrently.
            vs_encounter = VSEncounter.objects.filter(tournament=tournament).first()
            if vs_encounter is None:
                vs_encounter = VSEncounter.objects.create(
                    tournament=tournament,
                    team1=registered_teams[0].team,
                    team2=registered_teams[1].team,
                )
            pending_matches = generate_vs_pending_matches(
                vs_encounter,
                get_vs_num_matches(tournament),
            )
            vs_matches_created = len(pending_matches)

    return {
        "signin": signin,
        "created": created,
        "tournament_team": tournament_team,
        "tournament_team_created": tournament_team_created,
        "vs_encounter": vs_encounter,
        "vs_matches_created": vs_matches_created,
    }
