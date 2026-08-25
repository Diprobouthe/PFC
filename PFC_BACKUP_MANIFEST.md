# PFC Complete Source Backup

- Created: 20260825
- Scope: Complete current PFC source after the public Live Score white-score visual correction.
- Includes: Django applications, templates, source static assets, migrations, locale catalogs, PWA/service-worker source, Push implementation, Match Tracking Broadcast work, Tournament/Friendly/Live Score functionality, requirements, Procfile, render.yaml, and project configuration.
- Excludes: runtime SQLite data, uploaded media, logs, caches, virtual environments, node_modules, generated staticfiles, Git metadata, and secret environment files.
- Deploy: Extract the top-level directory and deploy its contents. Configure production secrets in Render, then run the normal release migration command: python manage.py migrate.
