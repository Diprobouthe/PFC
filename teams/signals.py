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

from django.db.models.signals import post_save, pre_save
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


@receiver(pre_save, sender='teams.TeamProfile')
def validate_new_team_photo(sender, instance, **kwargs):
    """Bound a newly uploaded Team photo before Django persists it."""
    photo = getattr(instance, "team_photo_jpg", None)
    is_new_upload = bool(photo and not getattr(photo, "_committed", True))
    instance._pfc_team_photo_new_upload = is_new_upload
    if is_new_upload:
        from teams.team_photo_utils import validate_team_photo_upload

        validate_team_photo_upload(photo)


@receiver(post_save, sender='teams.TeamProfile')
def generate_team_photo_derivatives(sender, instance, **kwargs):
    """Generate lightweight public variants only when a new source was uploaded."""
    if not getattr(instance, "_pfc_team_photo_new_upload", False):
        return

    try:
        from teams.team_photo_utils import generate_team_photo_variants

        generate_team_photo_variants(instance, force=True)
    except Exception as exc:
        # The source upload remains the durable source of truth. Templates have
        # an original-image fallback until regeneration/backfill succeeds.
        print(
            f"Team photo derivative generation failed for Team "
            f"{instance.team_id}: {exc}"
        )
    finally:
        instance._pfc_team_photo_new_upload = False
