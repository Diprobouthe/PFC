# PFC Complete Current Backup — Friendly Three-Hour Lifetime

**Date:** 2026-09-01

This is a complete source and Render deployment backup of the current PFC project after the isolated Friendly Game lifetime update.

## Targeted change in this version

New Friendly Games now set `expires_at` to three hours after creation rather than twenty-four hours. No other Friendly behavior was changed.

## Included

- Complete Django application source
- Templates and source static assets
- Migrations and locale catalogs
- PWA and Push source
- Friendly, Tournament, Match Tracking, Broadcast, Invitation, and Scenario-limit work
- Requirements and Render deployment configuration

## Excluded

- Database and uploaded media
- Secret environment files and credentials
- Virtual environments, dependency folders, caches, logs, generated static output, Git metadata, and prior archives

## Deployment

Extract the package root, configure Render environment variables, and run the normal release migration command:

```bash
python manage.py migrate
```
