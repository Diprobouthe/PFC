"""Persistent, match-scoped state for the Match Tracking interface."""

from django.db import models
from django.utils import timezone


class MatchTrackingSession(models.Model):
    """One tracking period for a specific tournament match or friendly game."""

    MATCH_TYPE_CHOICES = [
        ("match", "Tournament match"),
        ("game", "Friendly game"),
    ]
    STATUS_ACTIVE = "active"
    STATUS_ENDED = "ended"
    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Active"),
        (STATUS_ENDED, "Ended"),
    ]

    match_type = models.CharField(max_length=8, choices=MATCH_TYPE_CHOICES)
    match_pk = models.PositiveIntegerField(db_index=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_ACTIVE, db_index=True)
    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    ended_reason = models.CharField(max_length=32, blank=True)

    class Meta:
        ordering = ["-started_at"]
        indexes = [
            models.Index(fields=["match_type", "match_pk", "status"]),
        ]

    def __str__(self):
        return f"Tracking {self.match_type}:{self.match_pk} ({self.status})"

    def end(self, reason):
        """Finalize this tracking period and all practice sessions it opened."""
        if self.status != self.STATUS_ACTIVE:
            return
        for link in self.practice_sessions.select_related("practice_session").filter(
            practice_session__is_active=True
        ):
            link.practice_session.end_session()
        self.authorizations.filter(is_active=True).update(is_active=False)
        self.status = self.STATUS_ENDED
        self.ended_at = timezone.now()
        self.ended_reason = reason
        self.save(update_fields=["status", "ended_at", "ended_reason"])


class TrackingAuthorization(models.Model):
    """A QR-authorized participant within one MatchTrackingSession."""

    tracking_session = models.ForeignKey(
        MatchTrackingSession,
        on_delete=models.CASCADE,
        related_name="authorizations",
    )
    player = models.ForeignKey(
        "teams.Player",
        on_delete=models.CASCADE,
        related_name="match_tracking_authorizations",
    )
    codename = models.CharField(max_length=50)
    authorized_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True, db_index=True)
    # Separate, explicit consent for the public spectator feed. Tracking itself
    # remains usable when this is false, and the permission ends with the
    # existing match-scoped authorization/session lifecycle.
    broadcast_permitted = models.BooleanField(default=False, db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tracking_session", "player"],
                name="unique_tracking_player_authorization",
            ),
        ]

    def __str__(self):
        return f"{self.player} authorized for {self.tracking_session}"


class TrackingPracticeSession(models.Model):
    """Links an existing PracticeSession to the Match Tracking period that owns it."""

    tracking_session = models.ForeignKey(
        MatchTrackingSession,
        on_delete=models.CASCADE,
        related_name="practice_sessions",
    )
    player = models.ForeignKey(
        "teams.Player",
        on_delete=models.CASCADE,
        related_name="match_tracking_practice_sessions",
    )
    practice_session = models.OneToOneField(
        "practice.PracticeSession",
        on_delete=models.CASCADE,
        related_name="match_tracking_link",
    )
    practice_type = models.CharField(max_length=20, choices=[("shooting", "Shooting"), ("pointing", "Pointing")])
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tracking_session", "player", "practice_type"],
                name="unique_tracking_practice_type",
            ),
        ]

    def __str__(self):
        return f"{self.tracking_session} / {self.player} / {self.practice_type}"
