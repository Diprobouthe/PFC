"""
teams/signals.py

Post-save signal for the Team model.

When a new Team is created, automatically create a TeamProfile with
profile_type='minimal'.  This ensures that every team has a profile
record from birth, and that teams created by automated processes
(mêlée generation, invite flow, tournament registration) are not
accidentally exposed in the public team directory.

The profile_type can be upgraded to 'full' later by the team captain
or admin when the team intentionally wants a public presence.
"""

from django.db.models.signals import post_save
from django.dispatch import receiver


@receiver(post_save, sender='teams.Team')
def create_team_profile(sender, instance, created, **kwargs):
    """
    Auto-create a minimal TeamProfile whenever a new Team is saved for
    the first time.  We skip this if a profile already exists (e.g. the
    team was created via the public registration form which creates a
    full profile explicitly).
    """
    if not created:
        return  # Only act on creation, not updates

    from teams.models import TeamProfile  # local import to avoid circular deps

    # Only create if no profile exists yet
    if not TeamProfile.objects.filter(team=instance).exists():
        TeamProfile.objects.create(
            team=instance,
            profile_type='minimal',
        )
