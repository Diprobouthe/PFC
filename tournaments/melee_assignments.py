"""Validated writer for Mêlée round assignments.

P4 uses this writer as the live source for tournament-specific rosters. It
never writes Player.team; legacy Player.team fallback remains only in readers
for genuinely historical Mêlée records without assignment data.
"""

from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max

from tournaments.models import (
    MeleePlayer,
    MeleeRoundAssignment,
    Round,
    Tournament,
    TournamentTeam,
)


@dataclass(frozen=True)
class MeleeRoundAssignmentInput:
    """One complete Player state supplied to the round-assignment writer."""

    player: object
    team: object | None
    state: str


class MeleeRoundAssignmentWriteConflict(ValidationError):
    """Raised instead of overwriting an existing immutable round roster."""


class MeleeRoundAssignmentWriter:
    """Persist complete Mêlée round rosters with explicit validation.

    The writer deliberately calls ``full_clean()`` *before* every ``save()``.
    Django's base Model.save() does not perform model validation automatically;
    P1's model override is defence in depth, not the only writer guarantee.
    """

    @classmethod
    def initial_round_for_generation(cls, *, tournament):
        """Return/create the concrete first Round used by Mêlée generation.

        The method mirrors the existing match-generation identity convention:
        a multi-stage Mêlée uses the first Stage and ``number_in_stage=1``;
        a single-stage tournament uses its stage-less first Round. A malformed
        multi-stage tournament with no Stage has no reliable round context, so
        P2 leaves legacy generation untouched and returns ``None``.
        """
        if tournament.is_multi_stage:
            stage = tournament.stages.order_by('stage_number', 'id').first()
            if stage is None:
                return None
            round_obj, _ = Round.objects.get_or_create(
                tournament=tournament,
                stage=stage,
                number_in_stage=1,
                defaults={
                    'number': cls._next_overall_round_number(tournament),
                    'name': 'Round 1',
                },
            )
            return round_obj

        round_obj, _ = Round.objects.get_or_create(
            tournament=tournament,
            stage=None,
            number_in_stage=1,
            defaults={'number': 1, 'name': 'Round 1'},
        )
        return round_obj

    @classmethod
    def next_round_for_shuffle(cls, *, tournament, completed_round=None, completed_round_number=None):
        """Resolve a concrete next Round for a Super Mêlée redistribution.

        Normal live calls pass the completed Match's exact Round object. Older
        callers that have only a number are accepted only when that number maps
        to one unambiguous tournament Round. P2 never chooses among ambiguous
        Stage/global round rows silently.
        """
        if completed_round is None:
            if completed_round_number is None:
                return None
            matching_rounds = list(
                Round.objects.filter(
                    tournament=tournament,
                    number=completed_round_number,
                ).order_by('id')[:2]
            )
            if len(matching_rounds) != 1:
                return None
            completed_round = matching_rounds[0]

        if completed_round.tournament_id != tournament.id:
            raise ValidationError(
                'The completed round does not belong to the supplied tournament.'
            )

        if completed_round.stage_id:
            stage = completed_round.stage
            next_number_in_stage = completed_round.number_in_stage + 1
            if next_number_in_stage > stage.num_rounds_in_stage:
                return None
            next_round, _ = Round.objects.get_or_create(
                tournament=tournament,
                stage=stage,
                number_in_stage=next_number_in_stage,
                defaults={
                    'number': cls._next_overall_round_number(tournament),
                    'name': f'Round {next_number_in_stage}',
                },
            )
            return next_round

        next_number = completed_round.number + 1
        next_round, _ = Round.objects.get_or_create(
            tournament=tournament,
            stage=None,
            number_in_stage=next_number,
            defaults={'number': next_number, 'name': f'Round {next_number}'},
        )
        return next_round

    @staticmethod
    def _next_overall_round_number(tournament):
        highest_number = tournament.rounds.aggregate(highest=Max('number'))['highest']
        return (highest_number or 0) + 1

    @classmethod
    def write_current_generation_assignments(
        cls,
        *,
        tournament,
        round,
        individual_bye_player_ids=None,
    ):
        """Write every current Mêlée enrollment for initial generation.

        A registration without ``assigned_team`` is normally explicitly
        waitlisted. Snake Draft doubles may designate the one individual
        remainder player as an explicit round BYE; no Player.team compatibility
        projection is created by either state.
        """
        individual_bye_player_ids = set(individual_bye_player_ids or ())
        inputs = []
        for melee_player in tournament.melee_players.select_related('player', 'assigned_team'):
            if melee_player.assigned_team_id:
                inputs.append(
                    MeleeRoundAssignmentInput(
                        player=melee_player.player,
                        team=melee_player.assigned_team,
                        state=MeleeRoundAssignment.ASSIGNED,
                    )
                )
            else:
                inputs.append(
                    MeleeRoundAssignmentInput(
                        player=melee_player.player,
                        team=None,
                        state=(
                            MeleeRoundAssignment.BYE
                            if melee_player.player_id in individual_bye_player_ids
                            else MeleeRoundAssignment.WAITLISTED
                        ),
                    )
                )
        return cls.write_complete_round(
            tournament=tournament,
            round=round,
            assignments=inputs,
        )

    @classmethod
    def write_complete_round(cls, *, tournament, round, assignments):
        """Create one complete immutable roster/state set for a concrete Round.

        The input must classify every registered Mêlée Player exactly once.
        Existing identical data is returned idempotently. Different existing
        data is rejected rather than overwriting a historical round roster.
        """
        requested = cls._normalise_inputs(assignments)

        with transaction.atomic():
            locked_tournament = Tournament.objects.select_for_update().get(pk=tournament.pk)
            locked_round = Round.objects.select_for_update().get(pk=round.pk)
            cls._validate_round_context(
                tournament=locked_tournament,
                round=locked_round,
            )
            cls._validate_complete_registered_roster(
                tournament=locked_tournament,
                requested=requested,
            )

            existing = list(
                MeleeRoundAssignment.objects.select_for_update()
                .filter(tournament=locked_tournament, round=locked_round)
                .order_by('player_id')
            )
            if existing:
                if cls._matches_existing(existing=existing, requested=requested):
                    return existing
                raise MeleeRoundAssignmentWriteConflict(
                    'This Mêlée round already has a different assignment roster.'
                )

            persisted = []
            for player_id in sorted(requested):
                data = requested[player_id]
                assignment = MeleeRoundAssignment(
                    tournament=locked_tournament,
                    round=locked_round,
                    player_id=player_id,
                    team_id=data['team_id'],
                    state=data['state'],
                )
                # This explicit validation is mandatory. Model.save() is not
                # relied upon to enforce P1's cross-table relationship checks.
                assignment.full_clean()
                assignment.save()
                persisted.append(assignment)
            return persisted

    @staticmethod
    def _normalise_inputs(assignments):
        requested = {}
        for item in assignments:
            player_id = getattr(item.player, 'pk', None)
            team_id = getattr(item.team, 'pk', None) if item.team is not None else None
            if not player_id:
                raise ValidationError('Every Mêlée assignment must specify a saved Player.')
            if player_id in requested:
                raise ValidationError('A Player may receive only one state in a Mêlée round.')
            requested[player_id] = {'team_id': team_id, 'state': item.state}
        return requested

    @staticmethod
    def _validate_round_context(*, tournament, round):
        if not tournament.is_melee:
            raise ValidationError('Round assignments are only valid for Mêlée tournaments.')
        if round.tournament_id != tournament.id:
            raise ValidationError(
                'The supplied round does not belong to the supplied tournament.'
            )

    @staticmethod
    def _validate_complete_registered_roster(*, tournament, requested):
        registered_ids = set(
            MeleePlayer.objects.filter(tournament=tournament).values_list('player_id', flat=True)
        )
        requested_ids = set(requested)
        if requested_ids != registered_ids:
            missing_ids = registered_ids - requested_ids
            extra_ids = requested_ids - registered_ids
            details = []
            if missing_ids:
                details.append('missing registered Players')
            if extra_ids:
                details.append('unregistered Players')
            raise ValidationError(
                'A complete Mêlée round roster is required: ' + ', '.join(details) + '.'
            )

        team_ids = {
            data['team_id']
            for data in requested.values()
            if data['team_id'] is not None
        }
        enrolled_temp_team_ids = set(
            TournamentTeam.objects.filter(
                tournament=tournament,
                team_id__in=team_ids,
                team__is_tournament_temp=True,
            ).values_list('team_id', flat=True)
        )
        if team_ids != enrolled_temp_team_ids:
            raise ValidationError(
                'Assigned Mêlée teams must be temporary Teams enrolled in this tournament.'
            )

    @staticmethod
    def _matches_existing(*, existing, requested):
        existing_by_player = {
            assignment.player_id: {
                'team_id': assignment.team_id,
                'state': assignment.state,
            }
            for assignment in existing
        }
        return existing_by_player == requested
