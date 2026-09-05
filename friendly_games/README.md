# PFC Friendly Active/Unresolved Overlap Guard

Deploy these files over the corresponding project paths.

## Purpose

This update allows overlapping Friendly membership during pre-game setup but blocks any transition into `ACTIVE` when a participant is already in another Friendly with status `ACTIVE` or `PENDING_VALIDATION`.

## Included files

- `friendly_games/models.py`
- `friendly_games/views.py`
- `friendly_games/tests/__init__.py`
- `friendly_games/tests/test_activation_guard.py`

## Migration

No database migration is required.
