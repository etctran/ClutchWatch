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
