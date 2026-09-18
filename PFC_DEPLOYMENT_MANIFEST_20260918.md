# PFC Complete Sandbox Deployment Snapshot

**Artifact purpose:** Full source snapshot prepared from the latest PFC sandbox project for deployment to the existing Render service.

## Included

This snapshot includes the Django/ASGI application source, templates, static/PWA assets, localization resources, all Django migrations, application management commands, dependency manifests, and Render/ASGI deployment configuration. It contains the latest implemented work, including the Mêlée P1–P4 assignment architecture, the coordinated Super Mêlée shuffle repair, Home weather loading changes, Smart Router corrections, Friendly changes, Live Score and Match Tracking work, Push/PWA source, and current Tournament features.

## Deliberately excluded

The archive does not include sandbox-only or production-owned data and secrets: `.env` files, credential/key files, the sandbox `db.sqlite3`, media uploads, generated `staticfiles`, caches and bytecode, Git metadata, dependency folders, logs, nested delivery archives, and historical developer notes. Production PostgreSQL and persistent Render media must remain in place.

## Existing Render deployment procedure

Deploy this source to the existing Render web service through its normal source upload or repository workflow. Preserve the existing production environment variables, PostgreSQL database, Redis service, and persistent media disk. Do not reset or replace the production database, and do not delete the mounted media volume.

The included `render.yaml`, `Procfile`, `requirements.txt`, and `runtime.txt` retain the current service contract. The configured Render build sequence is:

```bash
pip install -r requirements.txt
python manage.py collectstatic --noinput
python manage.py migrate
```

The ASGI start command is:

```bash
daphne -b 0.0.0.0 -p $PORT pfc_core.asgi:application
```

`python manage.py migrate` is required so that the full migration history, including the current Mêlée assignment and roster-history migrations, is applied to the existing PostgreSQL database. It does not require a database reset or data deletion.

## Production configuration to preserve

Keep the existing values for `SECRET_KEY`, `DATABASE_URL`, `REDIS_URL`, `MEDIA_ROOT`, and the PFC Web Push VAPID settings where Push is enabled. Do not replace the existing production database URL, Redis connection, media mount, or production secrets with sandbox values. No new environment variable is required by this snapshot.

## Post-deployment

After Render reports a successful deploy, confirm the normal application health path and perform the planned functional testing. This packaging step does not deploy the service or modify Render data.
