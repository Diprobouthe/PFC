# PFC Consolidated Baseline — Deployment Manifest
**Package:** `PFC_BASELINE_20260513.zip`
**Date:** 2026-05-13
**Status:** Stable — all Django checks pass, all pages return HTTP 200

---

## What This Package Is

This is the **single clean consolidated deployment baseline** for the PFC platform.
It contains the latest correct version of every file that has been modified or created
across all upgrade sessions since the original deployment.

Deploy by replacing these files on Render. No migrations are required unless
explicitly noted in the per-file notes below.

---

## Modified Files (25 files — latest versions)

### `billboard/`

| File | Change Summary |
|---|---|
| `billboard/models.py` | Court presence tracking model updates; AT_COURTS presence logic |
| `billboard/presence_views.py` | Presence registration views; court-local time for AT_COURTS |
| `billboard/templates/billboard/billboard_list.html` | Billboard UI improvements |

### `billboard/templatetags/` *(new directory)*

| File | Change Summary |
|---|---|
| `billboard/templatetags/__init__.py` | Package init (new) |
| `billboard/templatetags/court_tz_tags.py` | `court_localtime`, `court_time`, `court_timesince` template filters for venue-local time display (new) |

### `friendly_games/`

| File | Change Summary |
|---|---|
| `friendly_games/management/commands/expire_friendly_games.py` | Timeout/cleanup management command for stale games |
| `friendly_games/models.py` | FriendlyGame + FriendlyGameResult: court-local time for `started_at`, `completed_at`, `validated_at`; `expires_at` logic; three-tier validation; rating integration |
| `friendly_games/urls.py` | URL additions for new game flows |
| `friendly_games/views.py` | Game start uses court-local now; `get_court_local_now` import; all game creation/start/validation flows |

### `matches/`

| File | Change Summary |
|---|---|
| `matches/admin.py` | Admin improvements for match management |
| `matches/forms.py` | Match form updates |
| `matches/models.py` | `Match.complete_match()` uses court-local `end_time`; `ScoreUpdate` model with `get_scorekeeper_name()`; `LiveScoreboard` model |
| `matches/signals.py` | Auto-scoreboard creation signal; auto-court-assignment signal uses court-local `start_time` |
| `matches/urls.py` | Added `scoreboard/<id>/history/` route |
| `matches/utils.py` | Match utility functions |
| `matches/views.py` | Match activation/validation/completion uses court-local time; `get_court_local_now` import |
| `matches/views_scoreboard.py` | Live scoreboard views; `update_type` detection (pétanque-correct: increment/correction/reset); `_resolve_scorekeeper_names()` batch helper; `scorekeeper_display_name` annotation; `court_complex` in context for both views |

### `pfc_core/`

| File | Change Summary |
|---|---|
| `pfc_core/settings.py` | Settings updates (channels, installed apps, etc.) |
| `pfc_core/smart_router.py` | Smart routing logic |
| `pfc_core/admin_filters.py` | Custom admin filters (new) |

### `teams/`

| File | Change Summary |
|---|---|
| `teams/admin.py` | Admin improvements |
| `teams/models.py` | Team/Player model updates |

### `templates/matches/`

| File | Change Summary |
|---|---|
| `templates/matches/match_detail.html` | Score history link on completed match; court-local time display |
| `templates/matches/score_history.html` | **New** — dedicated score progression history page; `court_tz_tags` for venue-local timestamps; `scorekeeper_display_name` (no raw codenames) |
| `templates/matches/scoreboard_detail.html` | Inline score history table; history shortcut link; `court_tz_tags` for timestamps; `scorekeeper_display_name` (no raw codenames) |
| `templates/matches/scoreboard_embed.html` | Scoreboard embed template updates |

### `friendly_games/templates/`

| File | Change Summary |
|---|---|
| `friendly_games/templates/friendly_games/game_detail.html` | Score history link on completed game |

### `tournaments/`

| File | Change Summary |
|---|---|
| `tournaments/admin.py` | Tournament admin improvements |
| `tournaments/models.py` | Tournament model updates |
| `tournaments/poule_admin.py` | Poule admin (new) |
| `tournaments/poule_models.py` | Poule models (new) |

---

## Feature Summary

### Score Progression / History System
- `ScoreUpdate` model records every score change with timestamp, scores, scorekeeper codename, and type
- `update_type` correctly tagged: `increment` (one team scores any amount), `correction` (both teams change, any decrease, or non-standard), `reset`
- Inline history table on `/matches/scoreboard/<id>/`
- Dedicated history page at `/matches/scoreboard/<id>/history/`
- History accessible from completed match detail and completed friendly game detail pages

### Privacy / Security
- Raw scorekeeper codenames are **never** rendered in public-facing UI
- `_resolve_scorekeeper_names()` batch-resolves codenames → player names in one DB query
- Each `ScoreUpdate` is annotated with `scorekeeper_display_name` before template rendering
- Codenames remain stored in DB for audit purposes only

### Timezone Fixes (Court-Local Time)
- All game/match start, end, and validation timestamps use `get_court_local_now(court_complex)` when a venue is attached
- Fallback to `timezone.now()` when no court is assigned (safe for all existing data)
- Template timestamps use `court_localtime` filter from `billboard/templatetags/court_tz_tags.py`
- Covers: match activation, match completion, result validation, friendly game start, timer start, game completion

### Friendly Game Fixes
- Timeout/cleanup logic via `expire_friendly_games` management command
- Court-local time for all game lifecycle timestamps
- Score history accessible after game completion

### Live Scoreboard System
- Auto-created for every match and friendly game via signals
- Non-interfering with core match/game logic
- Scorekeeper rating infrastructure (optional, non-blocking)

---

## Migrations Required

**None.** All changes are in views, models (logic only, no schema changes), templates, and utility files.

---

## Deployment Instructions

1. Extract the zip maintaining directory structure
2. Copy all files to the Render deployment root, replacing existing versions
3. Trigger a Render deploy (no `manage.py migrate` needed)
4. Verify: home page, scoreboard page, score history page all return HTTP 200
