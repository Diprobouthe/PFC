# PFC — Live Simple Tournament Player Registration Removal

## Scope

This package adds a compact `×` control only to the live Simple Tournament Management page for individual Mêlée registrations. It removes a single `MeleePlayer` registration from its current Tournament before team generation, without deleting or altering the Player, their Team, profile, or registration in any other Tournament.

The live route is `/simple/manage/<tournament_id>/`, handled by `pfc_core.simple_creator.manage_tournament` and rendered by `templates/simple_tournament_manage.html`. No historical or parallel Simple Tournament implementation was modified.

## Authorization and lifecycle

The new POST-only removal route is:

```text
/simple/manage/<tournament_id>/players/<melee_player_id>/remove/
```

It accepts the existing `simple_tournament_info` creator session for that exact Tournament or a staff user. It is CSRF-protected. It refuses removal when the Tournament is not Mêlée, is inactive, has generated Mêlée teams, or the registration has an assigned generated Team.

## Deployment

No migration or environment-variable change is required. Deploy the listed source/template files normally. The existing Django deployment migration step may continue to run but has no new migration for this patch.

## Verification

The following focused checks passed:

```text
python3 manage.py test \
  pfc_core.tests.test_simple_management_persistence \
  pfc_core.tests.test_simple_tournament_registration_removal \
  --verbosity 2

12 tests passed
python3 manage.py check -> 0 issues
python3 manage.py makemigrations --check --dry-run -> No changes detected
```

The browser flow was also verified with a temporary sandbox tournament: normal player registration, visible compact `×`, removal with the updated count/list, and normal re-registration. The temporary tournament and registration were removed after verification.

## Changed-file manifest

See `CHANGED_FILES.md` in this archive.
