# PFC Tournament Match Lifecycle — Isolated PostgreSQL Implementation Report

**Source baseline:** `Diprobouthe/PFC` `main` at `ed357d43c098bad7007ddaae29890f9b5491316a`
**Experimental branch reviewed but not adopted as authoritative:** `fix/tournament-races-20260922` at `6e305bc6de55e521a6f55b255cc542e61d41e3b9`
**Environment:** isolated Manus working copy at `/home/ubuntu/pfc-tournament-lifecycle` using isolated PostgreSQL 16
**Repository and production safety:** no commit, push, branch modification, pull-request modification, deployment, Render access, or production database access occurred.

## Executive summary

This implementation replaces scattered Tournament Match lifecycle writes with a small set of transactional services. It adds persistent lifecycle records, database constraints, short PostgreSQL row-lock scopes, a Round-owned lineup deadline, batch Court allocation, and idempotent Round completion. The goal is that **Match completion is Match-scoped**, while standings, Super Mêlée preparation, next-Round creation, leaderboard publication, and final-history recording are **Round-scoped and exactly-once**.

The source preserves existing Match, Team, Tournament, Round, and Court identifiers. It does not create a general membership model and does not change Friendly Game lifecycle behavior. Tournament/Mêlée lineups continue to use the existing `MatchPlayer` snapshot mechanism and existing P4 Mêlée roster resolution.

## Lifecycle design

| Lifecycle concern | Implemented owner | Persistence and concurrency guarantee |
|---|---|---|
| Court reservation and activation | `matches.lifecycle` | Locks base Match/Court rows with `select_for_update(of=("self",))`; uses `SKIP LOCKED` for candidate Courts; the partial unique Court constraint is a database backstop. |
| Official result submission and validation | `matches.lifecycle` | Locks the Match and result record; only one submitted result is created; result validation completes the Match exactly once. |
| Match-level projections | `MatchLifecycleTransition` | One-to-one transition record with status, attempts, error, and processed time. Ratings, participant snapshots, certifying ratings, VS points, and Mêlée stats run once per Match. |
| Round completion and successor work | `RoundLifecycleTransition` | One-to-one transition record claimed under the Round row lock only after every Match is `completed`. Swiss/Buchholz, Super Mêlée preparation, automation, leaderboard publication, and final history run once per Round. |
| Court queue handoff | `matches.lifecycle` | The completed Match keeps its historical Court FK. One compatible queued Match may claim the released Court under locks; otherwise the Court is returned to availability. |
| Lineup selection | `tournaments.lineup_lifecycle` | One persisted deadline per Round, explicit `MatchPlayer` selections while open, safe defaults only when the existing roster/format is unambiguous, and an all-or-nothing Round freeze. |
| Deadline observation | `tournaments.lineup_clock` | A lightweight in-process Daphne thread observes persisted deadlines. Multiple processes are harmless because the actual decision locks the Round row. No browser polling, Celery, Redis queue, scheduler, or separate service is required. |
| Leaderboard publication | `leaderboards.views` and `leaderboards.swiss_ranking` | Public GET handlers no longer rebuild. The lifecycle publishes in a transactionally serialized write path, and entries enforce one team and one position per leaderboard. |
| Mutation authority | `matches.authorization` and score endpoints | Tournament score/result mutations use trusted Team-session or QR authority; JSON/body identity is not authoritative. |

### State flow

```text
Round generated
  → persisted lineup_deadline_at
  → editable MatchPlayer selections while window is open
  → all-or-nothing frozen Round lineups
  → selected Matches ACTIVE if Courts are available; otherwise PENDING_VERIFICATION + waiting_for_court
  → official result submitted
  → opposing authorized side validates
  → Match COMPLETED + MatchLifecycleTransition
  → final Match of Round claims RoundLifecycleTransition
  → standings / Super Mêlée preparation / successor Round / leaderboard publication
```

`lineup_selection_seconds=0` is the backwards-compatible default. A new Round then freezes only valid automatic defaults immediately; organisers who require a visible selection period configure a positive value in Tournament admin. The deadline is server time, not a browser timer.

## File-by-file implementation inventory

| Files | Change |
|---|---|
| `matches/lifecycle.py` *(new)* | Central Court, activation, result, Match projection, Round transition, and retry services. |
| `matches/authorization.py` *(new)* | Request-time trusted Match-side authorization helper. |
| `matches/models.py`, `matches/migrations/0017_tournament_lifecycle_guards.py` *(new migration)* | Live-Court partial unique constraint and durable `MatchLifecycleTransition`. |
| `tournaments/models.py`, `tournaments/migrations/0033_tournament_lifecycle_guards.py`, `tournaments/migrations/0034_round_lineup_lifecycle.py` *(new migrations)* | Round identity constraint, durable `RoundLifecycleTransition`, Round deadlines/freezing fields, Tournament lineup duration, and supporting indexes. |
| `tournaments/lineup_lifecycle.py`, `tournaments/lineup_clock.py` *(new)* | Server-owned lineup save/finalize workflow and safe deadline observer. |
| `matches/views.py`, `templates/matches/match_activate.html`, `templates/matches/match_detail.html` | Existing activation UI now edits Round lineups when applicable; detail pages expose the Round state and no longer initiate a competing lifecycle. |
| `matches/views_scoreboard.py` | Tournament score update/reset authority resolves from trusted session/QR state rather than request-body identity. |
| `matches/utils.py`, `matches/signals.py`, `courts/views.py`, `courts/admin.py`, `matches/admin.py`, waiting-Court/stale-presence commands | Routes remaining Court and Match lifecycle paths through the central service; raw admin writes are removed or read-only. |
| `tournaments/automation_engine.py`, `tournaments/signals.py`, `tournaments/views.py`, `tournaments/apps.py`, `tournaments/admin.py` | Round-state locking, successor lineup window opening, removal of duplicate completion writers/GET-side leaderboard writes, deadline-clock startup, and admin configuration. |
| `leaderboards/models.py`, `leaderboards/views.py`, `leaderboards/swiss_ranking.py`, `leaderboards/migrations/0004_tournament_lifecycle_guards.py` *(new migration)* | Serial leaderboard publication, unique entry invariants, batched Swiss/Buchholz projection, and read-only GET behavior. |
| `pfc_events/signals.py` | Direct Match-based websocket state events without per-recipient Smart Router resolution; batch Round state delivery. |
| `pfc_core/settings.py` | `TOURNAMENT_LINEUP_CLOCK_ENABLED` setting, defaulting to `true`. |
| `matches/management/commands/retry_tournament_lifecycle_transitions.py` *(new)* | Explicit retry command for failed/pending durable transitions. |
| `tournaments/management/commands/seed_tournament_lineup_demo.py` *(new)* | Sandbox-only disposable 20-player lineup demonstration fixture. |
| `tools/tournament_lifecycle_load_test.py` *(new)* | Isolated PostgreSQL load harness; excluded from application runtime. |
| `matches/test_tournament_lifecycle_postgres.py`, `tournaments/test_round_lineup_lifecycle.py` *(new)* plus updated existing Match tests | PostgreSQL locks, constraints, idempotency, lineup timing, trusted mutation authority, P3/P4 compatibility, and read-only rendering regressions. |

The complete literal file diff is delivered separately as `PFC_TOURNAMENT_LIFECYCLE_DIFF_20260924.patch`.

## PostgreSQL verification

The isolated test database used PostgreSQL 16. The test module explicitly asserts `connection.vendor == "postgresql"`; lifecycle race tests use separate database connections and are skipped on SQLite because its locking semantics are not representative.

### Focused regression result

```text
python manage.py check                         → no system-check issues
python manage.py makemigrations --check --dry-run → no changes detected
python manage.py test [focused lifecycle suite] → 47 tests passed
```

The 47 passing tests covered Court claim races, the database Court uniqueness backstop, concurrent duplicate result submission, Match transition exactly-once behavior, final-Match Round transition exactly-once behavior, Round identity uniqueness, concurrent leaderboard rebuild serialization, lineup save/freeze/default/invalid behavior, trusted score authority, Mêlée consumer compatibility, Simple Creator draft dispatch, and Friendly regression coverage.

The known `teams.teamprofile already registered` runtime warning appeared during Django startup. It was already present in the project and did not cause a failed check or test.

### 300-participant PostgreSQL load result

The reproducible harness created a disposable 300-player Doubles Tournament containing 150 Teams, 75 first-Round Matches, and 12 Courts. It froze the Round, ran 300 concurrent public HTTP reads during active result completion/Court handoff, completed the full Round, and required successor generation.

| Measure | Actual result |
|---|---:|
| Participants / first-Round Matches / Courts | 300 / 75 / 12 |
| Freeze duration | 0.295 s |
| Freeze SQL queries | 20 |
| Immediately active / Court-queued Matches | 12 / 63 |
| Full first-Round completion | 75/75 Matches; no completion errors |
| Final completion batch | 3.396 s |
| Full queued Round completion | 14.884 s after initial concurrent batch |
| Successor Round | one Round created, 75 Matches |
| Initial concurrent result validations | 12 attempted; 0 errors; p50 1468.12 ms; p95 1497.62 ms |
| Concurrent GETs during lifecycle activity | 300; 300 × HTTP 200; 0 HTTP 5xx/network failures; p50 1200.68 ms; p95 2511.84 ms |
| PostgreSQL wait locks after run | 0 |

The batched Round freeze was measured before and after replacing the per-Match write loop within this isolated implementation: **1,091 queries / 1.459 s** became **20 queries / 0.295 s** for the 300-player fixture. This is an internal implementation optimization comparison, not a baseline measurement of the unmodified production service.

At an idle snapshot immediately after the load run, the Daphne test process used approximately **184 MB RSS** on a 6-vCPU/7-GB sandbox host; the isolated database reported one active connection and zero wait events. This is a point-in-time sandbox observation, not a production capacity commitment.

## Manual sandbox validation

A disposable PFC sandbox was started against the isolated PostgreSQL database. The demonstrated Tournament contained 20 NPC Players, 10 Teams, 5 pending Matches, and 2 Courts. An authenticated Team session successfully displayed the existing Match Detail page, opened the new **Update Lineup** screen, changed a role, saved the lineup, and returned the existing confirmation message. The same clock subsequently finalized a short test window, applied default valid lineups, allocated two Courts, and queued three Matches without browser-side polling.

The current resettable manual demo uses this private sandbox URL:

- `https://8010-i7rc5q114c5r7b2kncumm-8f4f4118.us1.manus.computer/matches/detail/381/`
- Team PIN for Demo Team 01: `970001`

These credentials and records exist only in the isolated test database. They are not production accounts and are excluded from the deliverable.

## Deployment risks and mitigations

| Risk | Mitigation in this delivery |
|---|---|
| Existing duplicate live Court occupancy | Migration preflight fails descriptively rather than choosing or deleting a Match. |
| Existing duplicate Round identity | Migration preflight fails descriptively rather than merging historical Rounds. |
| Existing duplicate leaderboard positions | Migration preflight fails descriptively rather than silently renumbering history. |
| Runtime error after final Match | Durable Match/ Round transition records retain failure status and error text; explicit retry command is provided. |
| Multiple Daphne processes observe the same deadline | The Round row is locked; only one process finalizes it. |
| Server restart during a lineup window | Deadline state is persisted; a restarted process discovers and finalizes overdue Rounds. |
| Browser opened multiple times or stale event routing | Match pages navigate from direct Match state events and no longer need a global Smart Router lookup on Match events. |

## Deployment decision points

Before deployment, the operator should choose a non-zero `lineup_selection_seconds` only for Tournament formats where each side should actively choose a Match lineup. Keep the default `0` for existing formats that require no lineup pause. Review preflight failures manually; the migrations intentionally do not repair historical ambiguity automatically.

No production deployment was performed as part of this work.
