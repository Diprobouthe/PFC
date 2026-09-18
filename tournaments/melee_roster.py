"""Read-only roster access for the P1 Mêlée round-assignment foundation.

This module intentionally does not alter Player.team. P4 uses it with P2's
validated assignment writer for generation, shuffle, and Mêlée Match/Smart/QR
readers. Player.team remains only normal affiliation plus a legacy fallback
for old Mêlée records that have no assignment dataset.
"""

from django.core.exceptions import ValidationError

from teams.models import Player
from tournaments.models import MeleeRoundAssignment, TournamentTeam


class MeleeRoundRosterService:
    """Resolve a Mêlée roster from explicit assignments, never Team.players."""

    @staticmethod
    def _validate_context(*, tournament, round, team=None):
        """Reject context combinations that cannot identify one tournament roster."""
        if round.tournament_id != tournament.id:
            raise ValidationError(
                "The supplied round does not belong to the supplied tournament."
            )
        if team is not None and not TournamentTeam.objects.filter(
            tournament_id=tournament.id,
            team_id=team.id,
        ).exists():
            raise ValidationError(
                "The supplied team is not enrolled in the supplied tournament."
            )

    @classmethod
    def assignments_for_team(cls, *, tournament, round, team):
        """Return assigned roster rows for one Team in one concrete Round.

        The queryset is ordered deterministically and selects Player data for
        display callers. It never follows Player.team or Team.players.
        """
        cls._validate_context(tournament=tournament, round=round, team=team)
        return (
            MeleeRoundAssignment.objects.filter(
                tournament_id=tournament.id,
                round_id=round.id,
                team_id=team.id,
                state=MeleeRoundAssignment.ASSIGNED,
            )
            .select_related('player', 'team', 'round')
            .order_by('player__name', 'player_id')
        )

    @classmethod
    def players_for_team(cls, *, tournament, round, team):
        """Return Players assigned to a Team/round through roster rows only."""
        assignments = cls.assignments_for_team(
            tournament=tournament,
            round=round,
            team=team,
        )
        return Player.objects.filter(
            pk__in=assignments.values('player_id')
        ).order_by('name', 'id')

    @classmethod
    def assignment_for_player(cls, *, tournament, round, player):
        """Return the Player's single assignment state for a round, if present."""
        cls._validate_context(tournament=tournament, round=round)
        return (
            MeleeRoundAssignment.objects.filter(
                tournament_id=tournament.id,
                round_id=round.id,
                player_id=player.id,
            )
            .select_related('team', 'round')
            .first()
        )

    @classmethod
    def assigned_team_for_player(cls, *, tournament, round, player):
        """Return the assigned temporary Team, or None for a non-team state."""
        assignment = cls.assignment_for_player(
            tournament=tournament,
            round=round,
            player=player,
        )
        if assignment is None or assignment.state != MeleeRoundAssignment.ASSIGNED:
            return None
        return assignment.team
