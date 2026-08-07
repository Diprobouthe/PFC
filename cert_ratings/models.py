"""
cert_ratings.models
===================
Independent Certifying Entity rating system.

This is completely separate from the existing PFC Rating (teams.PlayerProfile).
It must never read or write to PlayerProfile.value or PlayerProfile.rating_history.
A failure in this system must not affect any existing PFC functionality.
"""

from django.db import models
from django.utils import timezone


# ---------------------------------------------------------------------------
# Rating system type choices
# ---------------------------------------------------------------------------

RATING_SYSTEM_CHOICES = [
    ("classic_elo", "Classic Elo"),
]

# Classic Elo defaults (spec-mandated values)
CLASSIC_ELO_STARTING_RATING = 1000
CLASSIC_ELO_K_FACTOR = 20
CLASSIC_ELO_SCALE = 400


# ---------------------------------------------------------------------------
# CertifyingEntity
# ---------------------------------------------------------------------------

class CertifyingEntity(models.Model):
    """
    A body that certifies tournaments and maintains its own independent
    player rating universe.

    Examples: PETA, Atlas, EOED.
    """

    name = models.CharField(max_length=100, unique=True)
    is_active = models.BooleanField(default=True)
    rating_system = models.CharField(
        max_length=30,
        choices=RATING_SYSTEM_CHOICES,
        default="classic_elo",
    )

    # Rating-system parameters stored as individual fields for clarity.
    # Only classic_elo parameters are used now; extend as needed.
    elo_starting_rating = models.IntegerField(
        default=CLASSIC_ELO_STARTING_RATING,
        help_text="Starting Elo rating for new players (default 1000).",
    )
    elo_k_factor = models.IntegerField(
        default=CLASSIC_ELO_K_FACTOR,
        help_text="K-factor for Elo calculation (default 20).",
    )
    elo_scale = models.IntegerField(
        default=CLASSIC_ELO_SCALE,
        help_text="Rating scale divisor for Elo calculation (default 400).",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Certifying Entity"
        verbose_name_plural = "Certifying Entities"
        ordering = ["name"]

    def __str__(self):
        status = "" if self.is_active else " (inactive)"
        return f"{self.name}{status}"


# ---------------------------------------------------------------------------
# PlayerCertRating  (one row per player × certifying entity)
# ---------------------------------------------------------------------------

class PlayerCertRating(models.Model):
    """
    Current Elo rating for one player inside one certifying entity's universe.

    The combination (player, entity) is unique — there is exactly one row
    per player per entity.  The row is created the first time the player
    participates in an eligible certified tournament match.
    """

    player = models.ForeignKey(
        "teams.Player",
        on_delete=models.CASCADE,
        related_name="cert_ratings",
    )
    entity = models.ForeignKey(
        CertifyingEntity,
        on_delete=models.CASCADE,
        related_name="player_ratings",
    )
    current_rating = models.FloatField(default=CLASSIC_ELO_STARTING_RATING)
    matches_played = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("player", "entity")]
        verbose_name = "Player Certifying Entity Rating"
        verbose_name_plural = "Player Certifying Entity Ratings"
        ordering = ["-current_rating"]

    def __str__(self):
        return (
            f"{self.player.name} — {self.entity.name}: "
            f"{self.current_rating:.0f} ({self.matches_played} matches)"
        )


# ---------------------------------------------------------------------------
# CertRatingHistory  (one row per player × match processed)
# ---------------------------------------------------------------------------

class CertRatingHistory(models.Model):
    """
    Immutable record of every Elo change for a player inside a certifying
    entity's universe.

    Idempotency: the (player, entity, match) combination is unique so the
    same match can never update the same entity rating twice.
    """

    player = models.ForeignKey(
        "teams.Player",
        on_delete=models.CASCADE,
        related_name="cert_rating_history",
    )
    entity = models.ForeignKey(
        CertifyingEntity,
        on_delete=models.CASCADE,
        related_name="rating_history",
    )
    match = models.ForeignKey(
        "matches.Match",
        on_delete=models.CASCADE,
        related_name="cert_rating_history",
    )
    rating_before = models.FloatField()
    rating_after = models.FloatField()
    rating_change = models.FloatField()
    timestamp = models.DateTimeField(default=timezone.now)

    class Meta:
        unique_together = [("player", "entity", "match")]
        verbose_name = "Cert Rating History Entry"
        verbose_name_plural = "Cert Rating History Entries"
        ordering = ["-timestamp"]

    def __str__(self):
        sign = "+" if self.rating_change >= 0 else ""
        return (
            f"{self.player.name} [{self.entity.name}] "
            f"match {self.match_id}: "
            f"{self.rating_before:.0f} → {self.rating_after:.0f} "
            f"({sign}{self.rating_change:.1f})"
        )
