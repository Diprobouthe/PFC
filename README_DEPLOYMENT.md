# PFC — Complete Current Sandbox Project

## Archive purpose

This is a **full current-project archive** created directly from the working Manus sandbox at the time of packaging. It contains the PFC application source, templates, static assets, migrations, tests, dependency manifests, and Render configuration required to deploy the current codebase.

It is **not** a changed-files-only patch archive.

## Deployment to the existing Render service

1. Back up the existing Render service configuration and database as required by the operating team.
2. Extract this archive and use the extracted `PFC_FULL_PROJECT_CURRENT_20260919/` directory as the deployment source.
3. Preserve the existing Render environment variables, PostgreSQL database, Redis service, media configuration, and secret values. They are intentionally not included here.
4. Use the project's existing deployment configuration:
   - Dependencies: `pip install -r requirements.txt`
   - Database migrations: `python manage.py migrate`
   - Static collection, if required by the service build: `python manage.py collectstatic --noinput`
   - Process command: use the existing `Procfile` / `render.yaml` configuration.
5. Do **not** reset or delete the production database, users, media, or secrets.

## Latest migration

The latest current change includes `matches/migrations/0016_match_starting_team.py`, which adds a nullable `Match.starting_team` foreign key. It is applied by the normal `python manage.py migrate` command and requires no destructive data action.

## Contents and intentional exclusions

Included: application source, all Django apps, templates, static assets, locale catalogs, migrations, tests, `requirements.txt`, `Procfile`, `render.yaml`, and `runtime.txt`.

Excluded intentionally: `.env` files, credentials, local SQLite databases, database dumps, user media, virtual environments, caches/bytecode, logs, generated `staticfiles`, nested archives, and temporary files.
