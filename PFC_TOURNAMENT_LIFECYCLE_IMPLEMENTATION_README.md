# PFC Tournament Match Lifecycle Implementation

## Source baseline and scope

This complete source snapshot was produced from the **`main` branch of `Diprobouthe/PFC` at commit `ed357d43c098bad7007ddaae29890f9b5491316a`**. All changes were made only in the isolated Manus working copy. No commits, branches, pull requests, Render services, or production databases were changed.

The implementation establishes a server-owned Tournament Match lifecycle. It centralizes tournament Match state and Court allocation, serializes the completion of a Round, introduces bounded server-authoritative lineup selection windows, keeps public GET endpoints read-only, and hardens tournament score/result mutation authority. Friendly Game behavior remains outside the new lifecycle service.

## Deployment procedure

1. **Back up the Render PostgreSQL database and current deployable source** before changing the service. This release adds database constraints, lifecycle-record tables, and Round deadline fields.
2. Unpack this archive into the Render-connected source repository or deployment source directory. Preserve production-only assets and settings, including `.env`, `DATABASE_URL`, Redis configuration, media storage, VAPID values, and any Render-managed secrets. None are included in this archive.
3. Review the migration plan with `python manage.py migrate --plan` and then run `python manage.py migrate` exactly once. Do not reset, recreate, or delete the production database.
4. Keep the existing build and start commands. The included `Procfile` remains the authoritative start configuration. The Round deadline observer is an in-process Daphne thread and does **not** require Celery, a scheduler, a separate Render worker, or a new paid service.
5. Verify one tournament with a configured non-zero **Lineup selection window**. Confirm that each side can save its lineup before the deadline; then confirm that the Round automatically freezes lineups and allocates available Courts at the deadline.

The optional environment switch `TOURNAMENT_LINEUP_CLOCK_ENABLED` defaults to `true`. Set it to `false` only for a deliberate operational pause while investigating Round finalization; it is not required for normal deployment.

## Migration preflight conditions

The migrations deliberately stop rather than modify production data if any required invariant is already violated. Resolve the reported records explicitly, then retry `migrate`.

| Migration | Preflight condition | Operational response if it stops |
|---|---|---|
| `matches.0017_tournament_lifecycle_guards` | More than one `active` or `waiting_validation` Match occupies the same Court | Resolve the duplicate live Court state through the established Match procedure; do not delete records blindly. |
| `tournaments.0033_tournament_lifecycle_guards` | Duplicate `(tournament, overall round number)` or duplicate unstaged Round identity | Resolve duplicated Rounds before retrying. Historical Match IDs are not changed automatically. |
| `leaderboards.0004_tournament_lifecycle_guards` | Duplicate position inside one leaderboard | Rebuild or otherwise reconcile the affected leaderboard before retrying. |

## Rollback boundary

Code rollback is safest by restoring the immediately previous application release while retaining the database backup. Reversing schema migrations after this implementation can remove lifecycle transition records, including their retry history. If a database rollback is absolutely required, do it only from a verified backup and in dependency order: reverse `matches` to `0016_match_starting_team`, reverse `leaderboards` to `0003_leaderboardentry_stage_reached_tournament_status`, and reverse `tournaments` to `0032_player_tournament_history`. This source package does not run those commands automatically.

## Operational recovery

Failed but durable lifecycle projection records can be reviewed and retried explicitly with:

```bash
python manage.py retry_tournament_lifecycle_transitions
python manage.py retry_tournament_lifecycle_transitions --tournament-id <id>
```

The command is an operational recovery path, not a recurring worker. It retries only transitions recorded as `pending` or `failed`.

## Verification performed in the isolated sandbox

The implementation was validated against isolated PostgreSQL 16. The focused PostgreSQL regression suite ran **47 tests successfully** after `python manage.py check` and `python manage.py makemigrations --check --dry-run`, both of which completed cleanly. The existing `teams.teamprofile already registered` runtime warning appeared during Django command startup; it is a pre-existing warning and not a test failure.

A 300-player/75-Match PostgreSQL load run used 12 Courts. The Round freeze took **0.295 seconds and 20 SQL queries**, started 12 Matches and queued 63, completed all 75 Matches, generated the 75-Match successor Round exactly once, and served 300 concurrent HTTP reads with **0 HTTP 5xx/network failures**. Full measurements and method are in the accompanying implementation report.
