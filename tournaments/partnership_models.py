"""Historical partnership and shuffle records for Mêlée tournaments."""

from collections import defaultdict

from django.db import models
from django.db.models import Q

from teams.models import Player
from tournaments.models import Tournament


class MeleePartnership(models.Model):
    """One pair of Players assigned to one exact Mêlée Round.

    ``round`` is nullable solely for records created by the legacy pre-P4
    number-based implementation. P4 records always carry the concrete Round
    and are derived from its immutable ``MeleeRoundAssignment`` roster.
    """

    tournament = models.ForeignKey(
        Tournament,
        on_delete=models.CASCADE,
        related_name="melee_partnerships",
        help_text="The tournament where this partnership occurred",
    )
    round = models.ForeignKey(
        "Round",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="melee_partnerships",
        help_text="Exact Round for P4 assignment-based partnership history.",
    )
    player1 = models.ForeignKey(
        Player,
        on_delete=models.CASCADE,
        related_name="partnerships_as_player1",
        help_text="First player in the partnership",
    )
    player2 = models.ForeignKey(
        Player,
        on_delete=models.CASCADE,
        related_name="partnerships_as_player2",
        help_text="Second player in the partnership",
    )
    # Retained for legacy display and compatibility. P4 writes this from the
    # concrete Round's stage-local number but never uses it to resolve a roster.
    round_number = models.PositiveIntegerField(
        help_text="Round number when this partnership was formed"
    )
    team_name = models.CharField(
        max_length=100,
        help_text="Name of the mêlée team they were on together",
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="When this partnership was recorded",
    )

    class Meta:
        ordering = ["tournament", "round_id", "round_number", "team_name"]
        indexes = [
            models.Index(fields=["tournament", "round_number"]),
            models.Index(fields=["tournament", "round"]),
            models.Index(fields=["player1", "player2"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["tournament", "round", "player1", "player2"],
                condition=Q(round__isnull=False),
                name="unique_melee_partnership_exact_round",
            ),
        ]

    def __str__(self):
        round_label = self.round_id or self.round_number
        return f"{self.player1.name} & {self.player2.name} - {self.team_name} (Round {round_label})"

    @classmethod
    def record_partnerships_for_round(cls, tournament, round_obj=None, round_number=None):
        """Persist partnership history from one concrete P4 Round roster.

        New callers must pass ``round_obj``. The numeric fallback exists only
        for completion of legacy events created before P4 and must not be used
        by assignment-based generation or shuffle.
        """
        from tournaments.models import (
            MeleePlayer,
            MeleeRoundAssignment,
            MeleeRoundTeamBye,
        )

        teams_players = defaultdict(list)
        if round_obj is not None:
            if round_obj.tournament_id != tournament.id:
                raise ValueError("The partnership Round belongs to another tournament.")
            display_round_number = round_obj.number_in_stage or round_obj.number
            bye_team_ids = set(
                MeleeRoundTeamBye.objects.filter(
                    tournament=tournament,
                    round=round_obj,
                ).values_list("team_id", flat=True)
            )
            assignments = MeleeRoundAssignment.objects.filter(
                tournament=tournament,
                round=round_obj,
                state=MeleeRoundAssignment.ASSIGNED,
            ).exclude(team_id__in=bye_team_ids).select_related("player", "team")
            for assignment in assignments:
                teams_players[assignment.team].append(assignment.player)
        else:
            # Legacy-only compatibility. Its old records do not identify a
            # concrete Round, so preserve historic behavior without allowing
            # assignment-mode callers to use it.
            if getattr(tournament, "melee_roster_mode", None) == "assignment_based":
                raise ValueError("Assignment-based Mêlée partnerships require a concrete Round.")
            if round_number is None:
                raise ValueError("A concrete Round or legacy round number is required.")
            display_round_number = round_number
            for melee_player in MeleePlayer.objects.filter(
                tournament=tournament,
                assigned_team__isnull=False,
            ).select_related("player", "assigned_team"):
                teams_players[melee_player.assigned_team].append(melee_player.player)

        partnerships_created = 0
        for team, players in teams_players.items():
            for first_index in range(len(players)):
                for second_index in range(first_index + 1, len(players)):
                    player1, player2 = players[first_index], players[second_index]
                    if player1.id > player2.id:
                        player1, player2 = player2, player1
                    lookup = {
                        "tournament": tournament,
                        "player1": player1,
                        "player2": player2,
                    }
                    if round_obj is not None:
                        lookup["round"] = round_obj
                    else:
                        lookup["round__isnull"] = True
                        lookup["round_number"] = display_round_number
                    _, created = cls.objects.get_or_create(
                        defaults={
                            "round_number": display_round_number,
                            "team_name": team.name,
                            **({} if round_obj is not None else {}),
                        },
                        **lookup,
                    )
                    if created:
                        partnerships_created += 1
        return partnerships_created

    @classmethod
    def get_partnership_count(cls, tournament, player1, player2):
        """Return the number of recorded times a Player pair were teammates."""
        if player1.id > player2.id:
            player1, player2 = player2, player1
        return cls.objects.filter(
            tournament=tournament,
            player1=player1,
            player2=player2,
        ).count()

    @classmethod
    def get_player_partnership_history(cls, tournament, player):
        """Return partnership history for one Player in one Tournament."""
        return cls.objects.filter(tournament=tournament).filter(
            Q(player1=player) | Q(player2=player)
        ).select_related("player1", "player2", "round")


class MeleeShuffleHistory(models.Model):
    """Audit log for Super Mêlée shuffles."""

    tournament = models.ForeignKey(
        Tournament,
        on_delete=models.CASCADE,
        related_name="shuffle_history",
        help_text="The tournament where shuffling occurred",
    )
    round_number = models.PositiveIntegerField(
        help_text="Round number after which shuffling occurred"
    )
    round = models.ForeignKey(
        "Round",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="melee_shuffle_history",
        help_text="Exact completed Round for P4 shuffles.",
    )
    shuffle_type = models.CharField(
        max_length=20,
        choices=[
            ("automatic", "Automatic (after round completion)"),
            ("manual", "Manual (admin triggered)"),
        ],
        default="manual",
        help_text="How the shuffle was triggered",
    )
    shuffled_at = models.DateTimeField(
        auto_now_add=True,
        help_text="When the shuffle occurred",
    )
    shuffled_by = models.ForeignKey(
        "auth.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="Admin user who triggered the shuffle (for manual shuffles)",
    )
    players_shuffled = models.PositiveIntegerField(
        default=0,
        help_text="Number of players that were shuffled",
    )
    notes = models.TextField(blank=True, help_text="Optional notes about the shuffle")

    class Meta:
        ordering = ["-shuffled_at"]
        verbose_name_plural = "Mêlée shuffle histories"
        constraints = [
            models.UniqueConstraint(
                fields=["tournament", "round"],
                condition=Q(round__isnull=False),
                name="unique_melee_shuffle_exact_round",
            ),
        ]

    def __str__(self):
        round_label = self.round_id or self.round_number
        return f"{self.tournament.name} - Round {round_label} ({self.shuffle_type})"


class MeleePlayerStats(models.Model):
    """Track individual player statistics in mêlée tournaments."""

    tournament = models.ForeignKey(
        Tournament,
        on_delete=models.CASCADE,
        related_name="melee_player_stats",
        help_text="The mêlée tournament",
    )
    player = models.ForeignKey(
        Player,
        on_delete=models.CASCADE,
        related_name="melee_stats",
        help_text="The player",
    )
    starting_rating = models.FloatField(
        default=1000.0,
        help_text="Player's PFC rating when tournament started",
    )
    wins = models.PositiveIntegerField(default=0, help_text="Number of matches won (team victories)")
    losses = models.PositiveIntegerField(default=0, help_text="Number of matches lost (team defeats)")
    matches_played = models.PositiveIntegerField(default=0, help_text="Total matches played in this tournament")
    points_scored = models.PositiveIntegerField(default=0, help_text="Total points scored across all matches")
    points_against = models.PositiveIntegerField(default=0, help_text="Total points conceded across all matches")
    current_streak = models.IntegerField(default=0, help_text="Current win/loss streak (positive=wins, negative=losses)")
    best_performance = models.PositiveIntegerField(default=0, help_text="Best consecutive wins achieved in this tournament")
    created_at = models.DateTimeField(auto_now_add=True, help_text="When stats tracking started")
    updated_at = models.DateTimeField(auto_now=True, help_text="Last time stats were updated")

    class Meta:
        ordering = ["-wins"]
        unique_together = ["tournament", "player"]
        verbose_name = "Mêlée Player Statistics"
        verbose_name_plural = "Mêlée Player Statistics"
        indexes = [models.Index(fields=["tournament", "-wins"])]

    def __str__(self):
        return f"{self.player.name} - {self.tournament.name} ({self.wins}W-{self.losses}L)"

    @property
    def current_rating(self):
        try:
            from teams.models import PlayerProfile
            return round(PlayerProfile.objects.get(player=self.player).value, 2)
        except PlayerProfile.DoesNotExist:
            return self.starting_rating

    @property
    def rating_change(self):
        return round(self.current_rating - self.starting_rating, 1)

    @property
    def win_rate(self):
        if self.matches_played == 0:
            return 0.0
        return round((self.wins / self.matches_played) * 100, 1)

    @property
    def point_differential(self):
        return self.points_scored - self.points_against
