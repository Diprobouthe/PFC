"""PETA series persistence; registered by cert_ratings.models.

These models never alter the global PFC PlayerProfile rating.
"""
from decimal import Decimal
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models


class PetaSeries(models.Model):
    name = models.CharField(max_length=120)
    entity = models.OneToOneField(
        "cert_ratings.CertifyingEntity", on_delete=models.PROTECT,
        related_name="peta_series")
    rules_commitment = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class PetaEvent(models.Model):
    series = models.ForeignKey(PetaSeries, on_delete=models.PROTECT, related_name="events")
    tournament = models.OneToOneField(
        "tournaments.Tournament", on_delete=models.PROTECT, related_name="peta_event")
    ordinal = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(8)])
    include_podium = models.BooleanField(default=True)
    require_task = models.BooleanField(default=False)
    settled_at = models.DateTimeField(null=True, blank=True)
    settlement_audit = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["series", "ordinal"], name="peta_unique_series_ordinal")
        ]
        ordering = ["series_id", "ordinal"]

    def __str__(self):
        return f"{self.series.name} — {self.ordinal}/8"


class PetaCompetitor(models.Model):
    series = models.ForeignKey(PetaSeries, on_delete=models.PROTECT, related_name="competitors")
    player = models.ForeignKey("teams.Player", on_delete=models.PROTECT)
    travel_points = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal("0.0000"))
    last_end_rating = models.FloatField(null=True, blank=True)
    exception_used = models.BooleanField(default=False)
    dividend_suspended = models.BooleanField(
        default=False, help_text="Confirmed violation only; a rating drop alone does not prove intent.")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["series", "player"], name="peta_unique_competitor")
        ]


class PetaEventEntry(models.Model):
    event = models.ForeignKey(PetaEvent, on_delete=models.PROTECT, related_name="entries")
    player = models.ForeignKey("teams.Player", on_delete=models.PROTECT)
    entry_rating = models.FloatField()
    end_rating = models.FloatField(null=True, blank=True)
    use_exception = models.BooleanField(default=False)
    task_passed = models.BooleanField(null=True, blank=True)
    eligible_for_dividend = models.BooleanField(null=True, blank=True)
    personal_earnings = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal("0.0000"))
    dividend = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal("0.0000"))

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["event", "player"], name="peta_unique_event_entry")
        ]
