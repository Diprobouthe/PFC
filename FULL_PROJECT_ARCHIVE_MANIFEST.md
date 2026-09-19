# Full PFC Project Archive Manifest

**Source:** exact current `/home/ubuntu/merge/project` sandbox tree at packaging time.

**Archive type:** complete project snapshot, not a changed-files-only patch.

## Included deployment roots

- `manage.py`
- `requirements.txt`
- `Procfile`
- `render.yaml`
- `runtime.txt`
- `templates`
- `static`
- `locale`
- `matches`
- `tournaments`
- `teams`
- `pfc_core`
- `pfc_events`

## Intentional exclusions

Secrets and `.env*` files; local SQLite/database dumps; user media; virtual environments; caches/bytecode; logs; generated `staticfiles`; nested archives; and temporary files.
