"""
billboard/community_presence.py
================================
CommunityPresenceReport — crowd-sourced estimate of the total number of
people physically present at a court complex.

This is SEPARATE from verified BillboardEntry presence.  It represents an
approximate total (including non-PFC users) reported by any logged-in player.

Rules:
  - One active report per court complex at a time.
  - Any player can update the count or confirm the current count.
  - A report becomes stale after 60 minutes with no confirmation or update.
  - Stale reports are hidden from the display (not deleted).
  - The reporter's identity is stored internally but never shown publicly.
"""
from django.db import models
from django.utils import timezone
from datetime import timedelta
from courts.models import CourtComplex

STALE_MINUTES = 60  # minutes before a report is considered stale


class CommunityPresenceReport(models.Model):
    """
    A crowd-sourced estimate of the total number of people at a court.
    """
    court_complex = models.OneToOneField(
        CourtComplex,
        on_delete=models.CASCADE,
        related_name='community_presence_report',
        help_text="One active report per court complex.",
    )
    # The estimated total number of people on site (including non-PFC users)
    reported_count = models.PositiveIntegerField(
        help_text="Estimated total number of people physically present."
    )
    # Number of players who have confirmed the current count
    confirmation_count = models.PositiveIntegerField(
        default=1,
        help_text="Number of players who confirmed this count."
    )
    # Codename of the player who last updated the count (internal only, never shown)
    last_reporter_codename = models.CharField(
        max_length=6,
        help_text="Codename of the player who last reported/updated (internal).",
    )
    # Codenames of all players who confirmed this report (comma-separated, internal)
    confirming_codenames = models.TextField(
        blank=True,
        default='',
        help_text="Comma-separated codenames of confirming players (internal).",
    )
    # When the count was last updated or confirmed
    last_updated = models.DateTimeField(default=timezone.now)
    # When the report was first created
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Community Presence Report"
        verbose_name_plural = "Community Presence Reports"

    def __str__(self):
        return f"~{self.reported_count} at {self.court_complex.name} ({self.minutes_ago()} min ago)"

    def is_stale(self):
        """Returns True if the report has not been updated/confirmed for STALE_MINUTES."""
        return timezone.now() - self.last_updated > timedelta(minutes=STALE_MINUTES)

    def minutes_ago(self):
        """Returns how many minutes ago the report was last updated."""
        delta = timezone.now() - self.last_updated
        return int(delta.total_seconds() // 60)

    def get_confirming_list(self):
        """Return list of confirming codenames."""
        if not self.confirming_codenames:
            return []
        return [c.strip() for c in self.confirming_codenames.split(',') if c.strip()]

    def add_confirmation(self, codename):
        """Add a codename to the confirming list (idempotent)."""
        codename = codename.upper()
        existing = self.get_confirming_list()
        if codename not in existing:
            existing.append(codename)
            self.confirming_codenames = ','.join(existing)
            self.confirmation_count = len(existing)
            self.last_updated = timezone.now()
            self.save(update_fields=['confirming_codenames', 'confirmation_count', 'last_updated'])

    def update_count(self, new_count, codename):
        """Update the reported count and reset confirmations."""
        codename = codename.upper()
        self.reported_count = new_count
        self.last_reporter_codename = codename
        self.confirming_codenames = codename  # reporter is the first confirmer
        self.confirmation_count = 1
        self.last_updated = timezone.now()
        self.save()

    @classmethod
    def get_active_for_court(cls, court):
        """Return the active (non-stale) report for a court, or None."""
        try:
            report = cls.objects.get(court_complex=court)
            if report.is_stale():
                return None
            return report
        except cls.DoesNotExist:
            return None

    @classmethod
    def create_or_update(cls, court, count, codename):
        """
        Create a new report or update an existing one.
        Returns the report instance.
        """
        codename = codename.upper()
        try:
            report = cls.objects.get(court_complex=court)
            report.update_count(count, codename)
        except cls.DoesNotExist:
            report = cls.objects.create(
                court_complex=court,
                reported_count=count,
                last_reporter_codename=codename,
                confirming_codenames=codename,
                confirmation_count=1,
            )
        return report
