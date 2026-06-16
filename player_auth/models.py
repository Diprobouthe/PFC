"""
player_auth/models.py
=====================

PFCUser — the authentication layer that sits ABOVE the existing Player model.

Architecture:
    PFCUser (auth layer)
        ↓ 1:1
    Player (existing PFC model)
        ↓ 1:1
    PlayerCodename (existing, internal identifier)

Design rules:
    - PFCUser is the ONLY new model added.
    - Player and PlayerCodename are NEVER modified.
    - Codename is auto-generated, hidden from users, immutable after creation.
    - Team PIN / tournament / match logic is completely untouched.
"""

import uuid
import random
import string
from django.db import models
from django.utils import timezone


# ---------------------------------------------------------------------------
# Codename generation (collision-safe, not guessable)
# ---------------------------------------------------------------------------
def _generate_codename():
    """
    Generate a unique 6-character alphanumeric codename.
    Uses uppercase letters + digits, excludes ambiguous chars (0, O, I, 1).
    """
    chars = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
    return ''.join(random.choices(chars, k=6))


def generate_unique_codename():
    """Generate a codename guaranteed to be unique in PlayerCodename table."""
    from friendly_games.models import PlayerCodename
    for _ in range(100):
        code = _generate_codename()
        if not PlayerCodename.objects.filter(codename=code).exists():
            return code
    # Fallback: UUID-based (first 6 chars of hex)
    return uuid.uuid4().hex[:6].upper()


# ---------------------------------------------------------------------------
# OTP storage (in-DB, short-lived)
# ---------------------------------------------------------------------------
class EmailOTP(models.Model):
    """
    Short-lived 6-digit OTP for email-based passwordless login.
    Expires after 10 minutes. One active OTP per email at a time.
    """
    email = models.EmailField(db_index=True)
    code = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Email OTP"
        verbose_name_plural = "Email OTPs"
        ordering = ['-created_at']

    def __str__(self):
        return f"OTP for {self.email} ({'used' if self.used else 'active'})"

    @classmethod
    def create_for_email(cls, email):
        """Create a new OTP for the given email, invalidating any previous ones."""
        cls.objects.filter(email=email, used=False).update(used=True)
        code = ''.join(random.choices(string.digits, k=6))
        otp = cls.objects.create(
            email=email,
            code=code,
            expires_at=timezone.now() + timezone.timedelta(minutes=10),
        )
        return otp

    def is_valid(self):
        """Check if OTP is still valid (not used, not expired)."""
        return not self.used and timezone.now() < self.expires_at

    def consume(self):
        """Mark OTP as used."""
        self.used = True
        self.save(update_fields=['used'])


# ---------------------------------------------------------------------------
# PFCUser — the auth identity layer
# ---------------------------------------------------------------------------
class PFCUser(models.Model):
    """
    Authentication identity for a PFC player.

    Bridges external auth providers (Google, Email OTP) to the internal
    Player + PlayerCodename system.

    Invariants:
        - email is unique and immutable after creation
        - player is set once (either at creation or via link flow)
        - codename is NEVER stored here; it lives in PlayerCodename
        - team PIN logic is completely separate and unaffected
    """
    PROVIDER_GOOGLE = 'google'
    PROVIDER_EMAIL = 'email'
    PROVIDER_CHOICES = [
        (PROVIDER_GOOGLE, 'Google'),
        (PROVIDER_EMAIL, 'Email OTP'),
    ]

    # Auth identity
    email = models.EmailField(unique=True, db_index=True)
    provider = models.CharField(
        max_length=10,
        choices=PROVIDER_CHOICES,
        help_text="Primary auth provider used to create this account"
    )
    google_sub = models.CharField(
        max_length=128,
        blank=True,
        null=True,
        unique=True,
        help_text="Google 'sub' (subject) ID — stable unique identifier from Google"
    )

    # Display info (from provider, optional)
    display_name = models.CharField(max_length=150, blank=True)
    avatar_url = models.URLField(blank=True)

    # Link to existing PFC player
    player = models.OneToOneField(
        'teams.Player',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='pfc_user',
        help_text="Linked PFC Player record"
    )

    # Session / security
    last_login = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    # Legacy link tracking
    legacy_codename_linked = models.BooleanField(
        default=False,
        help_text="True if user linked an existing player via legacy codename"
    )
    legacy_link_skipped = models.BooleanField(
        default=False,
        help_text="True if user explicitly skipped the legacy link step"
    )

    class Meta:
        verbose_name = "PFC User"
        verbose_name_plural = "PFC Users"
        ordering = ['-created_at']

    def __str__(self):
        player_name = self.player.name if self.player else "unlinked"
        return f"{self.email} ({self.provider}) → {player_name}"

    # ------------------------------------------------------------------
    # Codename helpers (read-only access to internal codename)
    # ------------------------------------------------------------------
    @property
    def codename(self):
        """Return the internal codename (for system use only, never shown in UI)."""
        if self.player:
            try:
                return self.player.codename_profile.codename
            except Exception:
                return None
        return None

    # ------------------------------------------------------------------
    # Player creation / linking
    # ------------------------------------------------------------------
    def create_and_link_player(self, name=None):
        """
        Create a new Player + PlayerCodename + PlayerProfile and link to this PFCUser.
        Called when a new user registers and does not link a legacy player.

        PlayerProfile is created immediately with is_active=True so that rating
        tracking, PFC Market, and ranking work from the moment the player joins.
        Admins can deactivate the profile later via the admin panel if needed.
        """
        from teams.models import Player, Team, PlayerProfile
        from friendly_games.models import PlayerCodename

        player_name = name or self.display_name or self.email.split('@')[0]

        # New players go to the "Friendly Games" holding team
        default_team, _ = Team.objects.get_or_create(
            pin='000000',
            defaults={'name': 'Friendly Games'}
        )

        player = Player.objects.create(
            name=player_name,
            team=default_team,
            is_captain=False,
        )

        codename = generate_unique_codename()
        PlayerCodename.objects.create(
            player=player,
            codename=codename,
        )

        # Auto-create an active PlayerProfile so rating/market tracking starts immediately.
        # default is_active=True — admin can disable later if needed.
        PlayerProfile.objects.get_or_create(
            player=player,
            defaults={'skill_level': 1, 'is_active': True},
        )

        self.player = player
        self.save(update_fields=['player'])
        return player

    def link_legacy_player(self, codename):
        """
        Link this PFCUser to an existing Player via their legacy codename.
        Returns (player, error_message).
        """
        from friendly_games.models import PlayerCodename

        try:
            pc = PlayerCodename.objects.get(codename=codename.upper())
        except PlayerCodename.DoesNotExist:
            return None, "No player found with that codename."

        # Check if that player is already claimed by another PFCUser
        if hasattr(pc.player, 'pfc_user') and pc.player.pfc_user != self:
            return None, "That player is already linked to another account."

        self.player = pc.player
        self.legacy_codename_linked = True
        self.save(update_fields=['player', 'legacy_codename_linked'])
        return pc.player, None

    def record_login(self):
        """Update last_login timestamp."""
        self.last_login = timezone.now()
        self.save(update_fields=['last_login'])
