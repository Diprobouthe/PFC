"""
billboard/presence_prefs.py
============================
UserPresencePrefs — per-player smart defaults for the one-tap Billboard.

Tracks:
  - last court complex used
  - preferred time (inferred from past entries)
  - preferred days (bitmask, Mon=0 … Sun=6)

Updated automatically every time a BillboardEntry is saved.
"""
from django.db import models
from django.utils import timezone
from courts.models import CourtComplex


class UserPresencePrefs(models.Model):
    """
    Stores per-player smart defaults derived from their Billboard history.
    Keyed by codename (same auth as BillboardEntry).
    """
    codename = models.CharField(
        max_length=6,
        unique=True,
        db_index=True,
        help_text="Player codename (uppercase)",
    )

    # Last court complex the player posted from
    last_court_complex = models.ForeignKey(
        CourtComplex,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="presence_prefs",
    )

    # Most-used time slot (HH:MM string from BillboardEntry.TIME_SLOTS)
    preferred_time = models.CharField(
        max_length=5,
        blank=True,
        default="",
        help_text="Most-used time slot, e.g. '10:00'",
    )

    # Comma-separated day numbers (0=Mon … 6=Sun) sorted by frequency
    preferred_days = models.CharField(
        max_length=20,
        blank=True,
        default="",
        help_text="Comma-separated day numbers ordered by frequency",
    )

    # Timestamps
    last_seen = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "User Presence Prefs"
        verbose_name_plural = "User Presence Prefs"

    def __str__(self):
        return f"Prefs({self.codename}) → {self.last_court_complex}"

    # ── helpers ──────────────────────────────────────────────────────────────

    def get_preferred_days_list(self):
        """Return list of int day numbers, most-preferred first."""
        if not self.preferred_days:
            return []
        try:
            return [int(d) for d in self.preferred_days.split(",") if d.strip()]
        except ValueError:
            return []

    @classmethod
    def update_from_entry(cls, entry):
        """
        Called after a BillboardEntry is saved.
        Rebuilds the prefs for that codename from their last 60 entries.
        """
        from billboard.models import BillboardEntry
        from collections import Counter

        codename = entry.codename.upper()
        prefs, _ = cls.objects.get_or_create(codename=codename)

        # Always update last court and last seen
        prefs.last_court_complex = entry.court_complex
        prefs.last_seen = timezone.now()

        # Analyse last 60 entries for this player
        recent = (
            BillboardEntry.objects
            .filter(codename=codename)
            .order_by("-created_at")[:60]
        )

        # Preferred time: most common scheduled_time (skip blanks)
        times = [e.scheduled_time for e in recent if e.scheduled_time]
        if times:
            prefs.preferred_time = Counter(times).most_common(1)[0][0]

        # Preferred days: day-of-week of created_at, sorted by frequency
        days = [e.created_at.weekday() for e in recent]
        if days:
            ordered = [str(d) for d, _ in Counter(days).most_common()]
            prefs.preferred_days = ",".join(ordered)

        prefs.save()
        return prefs

    @classmethod
    def get_for_codename(cls, codename):
        """Return prefs object or None."""
        try:
            return cls.objects.select_related("last_court_complex").get(
                codename=codename.upper()
            )
        except cls.DoesNotExist:
            return None
