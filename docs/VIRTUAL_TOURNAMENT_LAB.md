# PFC Virtual Tournament Laboratory

## Safety boundary

**Phase 1 tests real HTTP and WebSocket transport, player sessions and Smart routing. It is NOT yet a complete virtual Super Mêlée or an Android/browser simulation.**

- Disposable PostgreSQL 16 database named pfc_vtl_test and Redis 7 in GitHub Actions.
- Daphne listens on 127.0.0.1:8765 only.
- Script refuses to run without PFC_VTL_ISOLATED=1 and exact localhost/pfc_vtl_test database URL.
- No connection to pfc.events, production Render or live players. No deployments, merges or production mutations.
- Session cookies stay in /tmp on the Actions runner and are not included in report artifacts.
- Production tournaments can continue undisturbed.

## Phase 1 implemented

1. Seed 30 synthetic players with distinct Django sessions and codenames, seven doublettes Matches and two byes.
2. Start real Daphne with the Django ASGI application, PostgreSQL and Redis.
3. Open five and then 30 independent authenticated client sessions.
4. Concurrently execute real HTTP Smart URL decisions via /my-matches/next-url/.
5. Open Invites WebSockets per session and Match state WebSockets for participating players.
6. Verify real event delivery via Redis to those sockets, not mocked Django consumers.
7. Force close/reconnect cycles; record handshake time, Smart p50/p95, message delivery and failures.
8. Repeat with Invites sockets disabled as a basic A/B transport comparison.

The three scenarios generate JSON reports as the pfc-virtual-lab-phase1 workflow artifact. A test fails if any client cannot connect, Smart returns an incorrect destination, or subscribed messages are missing.

## Limitations (do not overinterpret)

- This is a concurrent protocol client, not Playwright or mobile Chrome. It does not execute the PFC page JavaScript.
- The synthetic Matches are pending. Phase 1 does NOT yet execute full court allocation, timed lineup windows, activation, Live Score, Match Tracking or progression to later rounds.
- Runner CPU/DB limits are not identical to the Render production plans; CI timings are not production capacity guarantees.
- The Invites A/B variation changes the number of sockets; it cannot establish causal production CPU cost by itself.

## Next planned phases

- Add real Playwright browser contexts, JS WebSocket monitoring and lifecycle/visibility tests.
- Concurrent lineup writes and deadline finalization with PostgreSQL lock diagnostics.
- Match activation, Live Score writes, Match Tracking permissions and score validation.
- Full 30-player multi-round lifecycle and 5/10/20/30 scaling.
- Controlled WS reconnect storms, browser backgrounding and DB resource profiling.

## Usage

Update the draft PR, push the test/virtual-tournament-lab-20261020 branch, or manually dispatch the PFC Virtual Tournament Laboratory workflow. Download the JSON/log artifacts from Actions. Do not merge to main until separately approved.
