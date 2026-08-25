# PFC Complete Source Backup

- Created: 20260825
- Scope: Complete current PFC source after the compact Accepted Invitations history and invite-oriented header icon update.
- Includes: All Django applications, templates, source static assets, migrations, locale catalogs, PWA/service-worker source, Push implementation, Tournament/Friendly/Live Score/Match Tracking Broadcast/Invitation work, requirements, Procfile, render.yaml, and project configuration.
- Excludes: Runtime SQLite data, uploaded media, logs, caches, virtual environments, node_modules, generated staticfiles, Git metadata, and secret environment files.
- Deploy: Extract the top-level directory and deploy its contents. Configure production secrets in Render, then run the normal release migration command: python manage.py migrate.
