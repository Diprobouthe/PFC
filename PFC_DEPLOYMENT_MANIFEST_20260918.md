# PFC Complete Sandbox Deployment Snapshot

**Snapshot purpose:** complete Render-ready source package from the current independent sandbox, including all previous completed work and the **Lightweight Real-Time Tournament Overview** implementation.

## Included scope

This snapshot includes application code, templates, static source assets, Django migrations, ASGI/Channels configuration, PWA and Push source, Render configuration, and the newly added tournament Overview components. The Overview is a read-only spectator projection: it has a single tournament-scoped WebSocket, updates individual cards from existing score/tracking events, and fetches fresh card structure only after a Match lifecycle transition changes the visible Match set.

## Deliberately excluded

The archive excludes local/sandbox databases, production credentials and `.env` files, user media, generated static files, logs, caches, bytecode, virtual environments, `node_modules`, nested ZIP archives, and Git metadata. Production media continues to use the existing Render persistent disk at `/var/media`.

## Render deployment

1. Extract the archive into the Render service source directory, preserving its directory structure.
2. Preserve the existing Render environment values and services. In particular, do not replace the production `DATABASE_URL`, `REDIS_URL`, `SECRET_KEY`, media disk, or optional VAPID values with sandbox values.
3. Deploy normally. The included `render.yaml` build command remains:

   ```bash
   pip install -r requirements.txt
   python manage.py collectstatic --noinput
   python manage.py migrate
   ```

4. The included process command remains:

   ```bash
   daphne -b 0.0.0.0 -p $PORT pfc_core.asgi:application
   ```

## Migrations and environment

Run the standard `python manage.py migrate` command. This full package contains all migrations, including the prior Mêlée P1–P4 migrations. The new Tournament Overview does **not** add a migration.

No new environment variables are required for this implementation. Existing production settings must remain in place, including `DATABASE_URL`, `REDIS_URL`, `SECRET_KEY`, `MEDIA_ROOT`, and the optional `PFC_WEB_PUSH_VAPID_*` settings if Push is enabled.

## Data safety

No database reset, deletion, media deletion, or production data migration beyond the normal Django `migrate` command is required.
