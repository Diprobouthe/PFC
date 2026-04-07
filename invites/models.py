"""
invites/models.py
=================
Targeted invitation system for PFC.

Two invitation types:
  - PLAY_INVITE   : invite player(s) to play at a time/place (no team created)
  - TEAM_BUILD    : invite players to form a team (normal or tournament)

Design rules:
  - No team is created until enough players accept a TEAM_BUILD invite.
  - PLAY_INVITE carries optional time + court info; no team side-effects.
  - Each invite carries an optional short message (max 200 chars).
  - Realtime delivery is handled by the InviteConsumer (see consumers.py).
  - This module never touches existing match/tournament/team logic.
"""
import uuid
from django.db import models
from django.utils import timezone
from teams.models import Player, Team, generate_pin
from courts.models import CourtComplex
from tournaments.models import Tournament


# ── Invitation ────────────────────────────────────────────────────────────────

class Invitation(models.Model):
    """
    A targeted, single-direction invite from one player to another.

    One Invitation row per (sender, recipient) pair.
    For a TEAM_BUILD invite, all invitations share the same TeamBuildSession.
    For a PLAY_INVITE, session is NULL.
    """

    INVITE_TYPE_PLAY = "play"
    INVITE_TYPE_TEAM = "team_build"
    INVITE_TYPE_CHOICES = [
        (INVITE_TYPE_PLAY, "Play Invite"),
        (INVITE_TYPE_TEAM, "Team Build Invite"),
    ]

    STATUS_PENDING  = "pending"
    STATUS_ACCEPTED = "accepted"
    STATUS_REJECTED = "rejected"
    STATUS_EXPIRED  = "expired"
    STATUS_CHOICES = [
        (STATUS_PENDING,  "Pending"),
        (STATUS_ACCEPTED, "Accepted"),
        (STATUS_REJECTED, "Rejected"),
        (STATUS_EXPIRED,  "Expired"),
    ]

    # Unique token used in WebSocket group names and API calls
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    invite_type = models.CharField(
        max_length=20,
        choices=INVITE_TYPE_CHOICES,
        default=INVITE_TYPE_PLAY,
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
    )

    sender    = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="sent_invitations")
    recipient = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="received_invitations")

    # Optional short message attached to the invite (NOT a chat system)
    message = models.CharField(
        max_length=200,
        blank=True,
        default="",
        help_text="Optional short note (max 200 chars). Not a conversation thread.",
    )

    # ── PLAY INVITE fields ────────────────────────────────────────────────────
    play_time    = models.DateTimeField(null=True, blank=True, help_text="Proposed play time")
    play_court   = models.ForeignKey(
        CourtComplex,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="play_invitations",
        help_text="Proposed court/location",
    )
    play_notes   = models.CharField(max_length=200, blank=True, default="")

    # ── TEAM BUILD fields ─────────────────────────────────────────────────────
    session = models.ForeignKey(
        "TeamBuildSession",
        null=True, blank=True,
        on_delete=models.CASCADE,
        related_name="invitations",
    )

    created_at  = models.DateTimeField(auto_now_add=True)
    responded_at = models.DateTimeField(null=True, blank=True)
    expires_at  = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Invitation"
        verbose_name_plural = "Invitations"

    def __str__(self):
        return (
            f"[{self.get_invite_type_display()}] "
            f"{self.sender.name} → {self.recipient.name} "
            f"({self.get_status_display()})"
        )

    def accept(self):
        """Mark accepted and record timestamp."""
        self.status = self.STATUS_ACCEPTED
        self.responded_at = timezone.now()
        self.save(update_fields=["status", "responded_at"])

    def reject(self):
        """Mark rejected and record timestamp."""
        self.status = self.STATUS_REJECTED
        self.responded_at = timezone.now()
        self.save(update_fields=["status", "responded_at"])

    @property
    def is_pending(self):
        return self.status == self.STATUS_PENDING

    @property
    def channel_group_sender(self):
        """Channel group for the sender's personal notification stream."""
        return f"player_{self.sender_id}"

    @property
    def channel_group_recipient(self):
        """Channel group for the recipient's personal notification stream."""
        return f"player_{self.recipient_id}"


# ── TeamBuildSession ──────────────────────────────────────────────────────────

class TeamBuildSession(models.Model):
    """
    Tracks the process of assembling a team through invitations.

    A real Team object is NOT created until accepted_players.count()
    reaches target_size.  At that point, create_team() is called
    automatically by the accept-invite view.
    """

    BUILD_TYPE_NORMAL     = "normal"
    BUILD_TYPE_TOURNAMENT = "tournament"
    BUILD_TYPE_CHOICES = [
        (BUILD_TYPE_NORMAL,     "Normal Team"),
        (BUILD_TYPE_TOURNAMENT, "Tournament Team (temporary)"),
    ]

    SESSION_OPEN      = "open"
    SESSION_COMPLETE  = "complete"
    SESSION_CANCELLED = "cancelled"
    SESSION_CHOICES = [
        (SESSION_OPEN,      "Open"),
        (SESSION_COMPLETE,  "Complete — team created"),
        (SESSION_CANCELLED, "Cancelled"),
    ]

    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    creator = models.ForeignKey(
        Player,
        on_delete=models.CASCADE,
        related_name="created_build_sessions",
    )
    build_type = models.CharField(
        max_length=20,
        choices=BUILD_TYPE_CHOICES,
        default=BUILD_TYPE_NORMAL,
    )
    status = models.CharField(
        max_length=20,
        choices=SESSION_CHOICES,
        default=SESSION_OPEN,
    )

    target_size = models.PositiveSmallIntegerField(
        default=3,
        help_text="Number of players needed (including creator) to form the team.",
    )

    # Players who accepted (creator is added automatically on creation)
    accepted_players = models.ManyToManyField(
        Player,
        blank=True,
        related_name="accepted_build_sessions",
    )

    # Tournament reference (only for BUILD_TYPE_TOURNAMENT)
    tournament = models.ForeignKey(
        Tournament,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="team_build_sessions",
    )

    # The resulting team (set once create_team() succeeds)
    created_team = models.OneToOneField(
        Team,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="build_session",
    )

    # Optional proposed team name (creator can suggest; can be changed later)
    proposed_team_name = models.CharField(max_length=100, blank=True, default="")

    created_at   = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Team Build Session"
        verbose_name_plural = "Team Build Sessions"

    def __str__(self):
        return (
            f"TeamBuildSession #{self.pk} by {self.creator.name} "
            f"({self.get_build_type_display()}, {self.get_status_display()})"
        )

    @property
    def accepted_count(self):
        # +1 for the creator who is always counted
        return self.accepted_players.count() + 1

    @property
    def is_ready(self):
        """True when enough players have accepted to form the team."""
        return self.accepted_count >= self.target_size

    @property
    def is_tournament_type(self):
        return self.build_type == self.BUILD_TYPE_TOURNAMENT

    def create_team(self):
        """
        Create the actual Team once quorum is reached.
        Called by the accept-invite view after an acceptance tips the count.
        Returns the newly created Team or None if already created.
        """
        if self.created_team_id:
            return self.created_team  # Already done

        if not self.is_ready:
            return None

        # Determine team name
        name = self.proposed_team_name.strip() or f"Team {self.creator.name}"

        # Create the team using the existing generate_pin utility
        team = Team.objects.create(
            name=name,
            pin=generate_pin(),
        )

        # Assign all accepted players + creator to the team
        all_players = list(self.accepted_players.all())
        # Creator may or may not be in accepted_players; ensure they are included
        creator_in_list = any(p.pk == self.creator_id for p in all_players)
        if not creator_in_list:
            all_players.append(self.creator)

        for player in all_players:
            # Move player to the new team
            player.team = team
            player.save(update_fields=["team"])

        # Mark the creator as captain
        self.creator.is_captain = True
        self.creator.save(update_fields=["is_captain"])

        # Mark session complete
        self.created_team = team
        self.status = self.SESSION_COMPLETE
        self.completed_at = timezone.now()
        self.save(update_fields=["created_team", "status", "completed_at"])

        return team
