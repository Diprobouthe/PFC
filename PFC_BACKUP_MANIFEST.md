# PFC Complete Current Source — Render Parity Package

**Package date:** 2026-09-10  
**Source root:** `/home/ubuntu/merge/project`  
**Purpose:** Full current PFC application-source package for restoring source parity with the working sandbox on Render.

## Included application contents

This package contains the complete current Django/ASGI PFC source tree, including application modules, templates, source static assets, locale catalogs, migrations, requirements, and Render deployment configuration. It includes the current Court Complex live-detail redesign, per-Complex Billboard data integration, accuracy-aware location verification and ambiguity handling, robust manual geolocation retry/error handling, Friendly venue/activation protections, PWA/Push source, Tournament/Pool/Multi-Stage source, Match Tracking/Broadcast source, Invitations, and all other current source present in the sandbox project.

## Deliberate exclusions

The package excludes local runtime and non-deployable artifacts: `db.sqlite3`, `media/`, `.env` and credential files, cache directories, Python bytecode, virtual environments, `node_modules`, generated `staticfiles/`, Git metadata, logs, existing archives, and root-level legacy developer utility scripts (`test_*.py`). These exclusions do not remove application migrations or maintained application tests.

## Render architecture and deployment

`render.yaml` retains the existing PostgreSQL database, Redis channel-layer service, persistent `/var/media` disk, Daphne ASGI start command, and Render build flow:

```text
pip install -r requirements.txt
python manage.py collectstatic --noinput
python manage.py migrate
daphne -b 0.0.0.0 -p $PORT pfc_core.asgi:application
```

Run `python manage.py migrate` against the existing Render PostgreSQL database after deployment. This package includes all current migrations, including:

- `billboard.0017_billboardentry_location_verification`;
- `match_tracking.0003_rename_match_track_match_t_579c20_idx_match_track_match_t_37e104_idx`;
- `invites.0004_alter_invitation_message_alter_invitation_play_court_and_more`.

No database reset, schema deletion, media deletion, or data migration outside Django migrations is required.

## Environment variables

Keep the existing production values for `SECRET_KEY`, `DATABASE_URL`, `REDIS_URL`, `MEDIA_ROOT`, Google OAuth variables where used, and the existing PWA Web Push VAPID variables. Do not upload a `.env` file. The current source accepts the existing optional `PFC_FRIENDLY_COURT_PROXIMITY_METERS` value; its source default is 200 metres. There is no new environment variable required by the current accuracy-aware location logic.

## Validation record

Before packaging, the current source passed Django checks, reported no pending model migration changes, and passed 27 maintained application tests. The local runtime database had the current migrations applied. The project has no Git metadata, so a commit hash is unavailable.
