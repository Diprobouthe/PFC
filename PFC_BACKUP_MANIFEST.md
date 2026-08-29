# PFC Complete Current Source and Render Deployment Backup

**Package date:** 2026-08-29

This archive is a complete clean source reference for the current PFC platform. It is intended for Render deployment, rollback, and long-term project reference.

## Included

The archive includes all current Django application source, templates, source static assets, migrations, locale catalogs, package manifests, deployment configuration, `requirements.txt`, `Procfile`, `render.yaml`, `runtime.txt`, PWA/service-worker source, Push implementation, current Friendly Game creator and Players-at-Courts work, Manual/Random/Balanced team-building work, Match Tracking/Broadcast work, Live Score work, Invitation work, and Tournament/Pool/Multi-Stage/Scenario-limit work.

## Excluded deliberately

The archive excludes runtime and sensitive/generated artifacts: `db.sqlite3`, uploaded media, `staticfiles`, `.env` files, cookies, logs, caches, `__pycache__`, compiled Python files, virtual environments, `node_modules`, Git metadata, and prior ZIP archives.

## Render deployment

Extract the archive and deploy the contents of the top-level project directory. Configure production secrets as Render environment variables. Run the existing release migration process:

```bash
python manage.py migrate
```

Use the included `Procfile`, `render.yaml`, and `requirements.txt` for the current project configuration.

## Revision note

The restored source tree does not contain a `.git` directory, so no commit hash is available for this package.
