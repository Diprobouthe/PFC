"""Persistence for optional, device-specific PFC Web Push delivery."""

from django.db import models
from django.utils import timezone

from teams.models import Player


class WebPushSubscription(models.Model):
    """A browser/device Push subscription belonging to one authenticated player.

    This stores delivery credentials only. It does not represent a PFC message,
    Match state, invitation, action, or notification history.
    """

    player = models.ForeignKey(
        Player,
        on_delete=models.CASCADE,
        related_name="web_push_subscriptions",
    )
    endpoint = models.TextField(unique=True)
    p256dh = models.CharField(max_length=255)
    auth = models.CharField(max_length=255)
    content_encoding = models.CharField(max_length=32, default="aes128gcm")
    locale = models.CharField(max_length=12, default="en")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_success_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-updated_at"]
        verbose_name = "Web Push subscription"
        verbose_name_plural = "Web Push subscriptions"

    def __str__(self):
        return f"Push subscription for {self.player.name} ({'active' if self.is_active else 'inactive'})"

    def mark_success(self):
        self.last_success_at = timezone.now()
        self.is_active = True
        self.save(update_fields=["last_success_at", "is_active", "updated_at"])

    def deactivate(self):
        if self.is_active:
            self.is_active = False
            self.save(update_fields=["is_active", "updated_at"])
