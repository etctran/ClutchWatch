# Design decisions

## Container images use a Dockerfile, not buildpacks
Spec pins Python 3.12. Google's current Cloud Run buildpack builder only resolves Python 3.13+, so `--source` deploys with `.python-version=3.12` fail. A 3-line `python:3.12-slim` Dockerfile pins the runtime exactly and is what the real services need anyway.

## Live data via `nba_api.live`
M0 smoke test: plain `urllib` from Cloud Run and `curl` from a laptop both get 403 from `cdn.nba.com` live JSON, so the block is on request headers, not cloud IPs (the spec's "run the poller locally" fallback would not help). `nba_api.live`, which sends browser-like headers, succeeds from Cloud Run (`{"ok": true, "games": 4}` on 2026-11-12). Chosen: `nba_api.live` for the live poller. Alternative was replay-only, which loses only the live-night demo.

## One normalizer for both sources (historical = archived CDN JSON)
`shufinskiy/nba_data` ships `cdnnba_<season>` files: the same action schema as the live CDN play-by-play. So a single `normalize(action, game_id, home, away, source)` handles both, and "both sources produce identical-shaped events" holds by construction rather than by two parsers kept in sync. Cost: `cdnnba` starts at 2020-21, not 2018-19, so the model trains on 2020-21 to 2022-23 (3 seasons, ~3,700 games) instead of 5. Alternative was `nbastats` (v2 format) for 1996+, which needs a second parser.

## GameEvent carries `order_number` (schema addition)
Measured on all 1,230 games of 2024-25: in `actionNumber` order the score decreases at some point in 1,161 games; in `orderNumber` order it never does. `actionNumber` is append order (late-entered/corrected plays get high numbers), `orderNumber` is game order. So: the live poller diffs on `actionNumber` (catches late entries), the replayer publishes in `orderNumber` order, and the processor only advances game state when an event's `order_number` is newer than the state's, so a late-entered play can't roll the score back.

## Pub/Sub redelivery is real, even on a trivial pull
M1 verification on one 538-event game: one pull run received 588 messages (50 redeliveries), another exactly 538. In both, first deliveries were in order. The processor must be idempotent; ordering keys alone are not enough.

## Home/away inferred for historical games
The archive has no home/away column. The team whose basket increases `scoreHome` is home (`infer_home_away`). Live mode takes home/away from the scoreboard instead.
