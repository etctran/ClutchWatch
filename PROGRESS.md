# Progress

## M0: Setup and smoke test (2026-11-12)
- Project `clutchwatch-bywa6u` (us-central1), billing linked.
- Budget `clutchwatch-25usd`: $25, scoped to this project, alerts at 20/50/90/100% (confirmed via `gcloud billing budgets list`).
- APIs enabled: Run, Pub/Sub, BigQuery, Artifact Registry, Memorystore (Redis), Cloud Build, Secret Manager.
- Smoke service (`smoke/`, Python 3.12 Dockerfile) deployed to Cloud Run, then deleted.
- **Result:** plain fetch of `cdn.nba.com/.../todaysScoreboard_00.json` returns **HTTP 403** from Cloud Run, and also 403 from a residential laptop with curl.
  The block is on request headers (non-browser client), not on cloud IPs, so the spec's "run the poller locally" fallback does not help.
- Live-mode data access: re-tested with `nba_api.live` from Cloud Run: **succeeds** (`{"ok": true, "gameDate": "2026-11-12", "games": 4}`). Smoke service deleted.
- **Exit met.**

## M1: Event model and ingestion (2026-11-12)
- `ingest/normalize.py`: `GameEvent` (+ `order_number`, see DECISIONS) and one normalizer for live JSON and historical CSV (same CDN schema).
- `ingest/replayer.py` (`--speedup` / `--target-rate`, games heap-merged by `timeActual`, per-game `orderNumber` order), `ingest/live_poller.py` (`actionNumber` cursor per game, 5 s poll), `ingest/publisher.py` (ordering key = game_id).
- Tests: 8 pass (`uv run pytest`). Fixtures are real: 2024-25 ATL@BOS (`22400001`, historical CSV) and 2026-11-11 OKC@POR (`0022600226`, live CDN JSON via nba_api).
- Exit check: replayed `0022400001` to `game-events` (`--target-rate 200`): published=538 failed=0; pulled back from an ordered subscription: 538 unique, first deliveries in order, final ATL 117 @ BOS 116. One earlier pull run saw 50 redeliveries (588 received).
- Temp topic/subscription deleted; Terraform owns them from M2.
- **Exit met.**

## M3: Win-probability model (2026-11-12)
- `model/train.py` (one row per scoring event, train 2020-21..2022-23), `model/evaluate.py`, exported `processor/wp_model.json`; runtime `processor/winprob.py` (no ML deps), shared `features()`.
- T7 on test 2024-25: Brier 0.1641 vs 0.2500 (const) / 0.2497 (leader wins); max decile calibration error 0.0310. See RESULTS.md.
- Wired into processor: every `state-updates` row carries `home_wp`.
- **Exit met.**

## M2: Core pipeline on GCP (2026-11-12)
- `infra/*.tf` (21 resources): topics game-events / state-updates / game-events-dlq; ordered push subscription to the processor (OIDC, DLQ after 5 attempts); BigQuery dataset + `raw_events` / `wp_timeline` via BigQuery subscriptions; Memorystore Redis 7.2 basic 1 GB; Cloud Run `processor` with Direct VPC egress; least-privilege service accounts. `scripts/deploy.sh` builds the image (Cloud Build) and applies; first apply 6m27s (Redis 4m27s).
- Processor: idempotent Lua apply, `home_wp`, `GET /games/{id}` for verification.
- Exit check: replayed `0022400001` (`--target-rate 50`, published from laptop). Redis via `GET /games/0022400001`: applied=538, BOS 116 / ATL 117. `bench/queries/counts_by_game.sql`: raw_events 538 = processed 538, redeliveries 0, final BOS 116 / ATL 117. DLQ pull: empty.
- **Exit met.**
- Finding for M5: one game drained at only ~20 events/s (applied 52 -> 233 -> 445 -> 538 at ~10 s intervals), so publish->processed latency on this run was p50 18.0 s / p99 25.8 s: pure queueing behind the per-key limit (ordered push = one message in flight per game). Not a T2 measurement (published from a laptop, single game, over-driven); see DECISIONS.

## M4: Alerts (2026-11-13)
- `processor/alerts.py`: CLOSE_LATE / WP_SWING / COMEBACK + 4-per-game cap as a pure function over a per-game JSON state in Redis (survives restarts). Evaluated only for events that advance game state (`apply() == 2`), never for late-entered plays or duplicates.
- `notifier/app.py`: push endpoint, Redis claim on `alert_id` before posting, Discord 429/5xx -> release claim + 503 so Pub/Sub backs off. Deliveries go to `alert-deliveries` -> BigQuery `alert_deliveries` (for T3); fired alerts go to BigQuery `alerts` straight from the `alerts` topic (for T8/T9). Webhook in Secret Manager (`discord-webhook`).
- Tests: 24 pass (alert rules incl. window/cooldown/cap/restart, notifier dedup + 429 retry).
- Exit check: replayed OT game `0022400119` (BOS 132 @ IND 135 OT, BOS came back from 24 down), `--target-rate 20`. Expected alerts (computed offline with the same code): CLOSE_LATE Q4, COMEBACK BOS, WP_SWING, CLOSE_LATE OT. `bench/queries/alerts_for_game.sql`: exactly those 4, each fired once, each delivered once, Discord 204.
- Duplicate check: replayed the same game a second time. wp_timeline: 1,328 rows / 664 distinct / 664 duplicate rows; Redis applied stays 664; alerts still 4, deliveries still 4.
- **Exit met.**
- Not T3: publish->Discord was ~23-25 s here, queueing behind the ~20 ev/s per-game drain rate (see M2 note).
- Offline preview of the spec's rules over all of 2024-25 (`evaluate` run locally, NOT a T8/T9 measurement): CLOSE_LATE on 157/221 games decided by <=3 or OT (71%); 129/259 blowouts (>=20) got an alert; 2.23 alerts/game. WP_SWING (2,031 of 2,739 alerts) fills the 4-alert cap first. Decision on tuning deferred to M5.

## M5: Load, chaos, measurement (2026-11-13/14)
- Alert rules tuned on 2023-24 (DECISIONS), replayer moved to a Cloud Run Job (`--align`, `--run-tag`), queries in `bench/queries/`, `bench/check_state.py` for Redis-vs-source.
- Runs: `load1`, `chaos5` (10% forced NACK), `chaos6` (clean in effect), `chaos7` (mid-run redeploy), `load2`, `t3a`, `t3b`. All numbers and commands in RESULTS.md.
- Met: T1 (avg), T3 (+stretch, at real pace), T4 (5 full-season runs, 0 lost), T5, T6, T7, T8 (+stretch), T9 alerts/game.
- Missed: T2 (p50 met in 1 of 4 runs; delay inside Pub/Sub before push dispatch), T9 blowout rate (6.6% vs 5%).
- Not measured yet: T10 (needs the billing report, which lags ~1 day), T11 (timed from-scratch deploy).
- Torn down with `scripts/teardown.sh redis` (Memorystore + Cloud Run services + push subscriptions); BigQuery kept so every query in RESULTS.md can be rerun. `scripts/deploy.sh` restores.
