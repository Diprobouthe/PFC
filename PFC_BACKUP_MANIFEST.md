# PFC Complete Render Deployment Package

**Package date:** 2026-09-10

## Purpose

This is a complete current PFC source and deployment package prepared from the working sandbox project at `/home/ubuntu/merge/project`.

It includes all current Django application source, templates, source static assets, migrations, locale catalogs, PWA and Push components, Render configuration, dependency manifests, and deployment entry files.

## Included current feature state

The package includes the latest Court Complex live-detail and Billboard integrations, Practice UI refreshes, Pointing Practice fixes, Friendly overlap and creator-GPS venue protections, accuracy-aware proximity verification, PWA/Push components, Match Tracking/Broadcast features, Invitations, Tournament/Pool/Multi-Stage features, registration/voucher work, and the Friendly starting-side communication update.

For the Friendly starting-side update, the existing random draw and selected-side-only Push behavior remain unchanged. The existing selected side sees the stored draw result after activation, until the first official non-zero score update is recorded. No manual dismissal, new recipient path, or Match scoring/lifecycle change is included.

## Render deployment

Use the existing `render.yaml`, `Procfile`, `requirements.txt`, and `runtime.txt` in the project root. Preserve existing production environment variables and Render service architecture, including PostgreSQL, Redis, persistent media storage, PWA/Push VAPID settings, and Django secrets.

Run the normal deployment migration command:

```bash
python manage.py migrate
```

No database reset, data deletion, or media replacement is required.

## Excluded by design

The archive excludes `db.sqlite3`, uploaded `media/`, `.env` and credential files, logs, cookies/sessions, caches, `__pycache__`, `*.pyc`, virtual environments, `node_modules`, generated `staticfiles`, `.git`, nested ZIP archives, test/runtime artifacts, and temporary developer scripts.

## Validation

The package is validated with `unzip -t` and a SHA-256 checksum before delivery. No Git commit is recorded because the restored project has no Git metadata.
