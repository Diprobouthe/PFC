"""Optional Push delivery hook for all persisted PFC Invitations."""

from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Invitation


@receiver(post_save, sender=Invitation)
def deliver_created_invitation_as_push(sender, instance, created, **kwargs):
    """Add optional post-commit Push delivery without changing Invitation behavior."""
    if not created:
        return
    from pfc_events.push_notifications import notify_invitation_created
    notify_invitation_created(instance)
