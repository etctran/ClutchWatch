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

## Idempotent apply = one Lua script (SET NX + state update)
Pub/Sub push is at-least-once. The processor runs one Lua script per event: `SET seen:<event_id> NX EX 7d`; if that succeeds, bump `applied` and update the game hash, but only if `order_number` is newer than the stored one. Atomic in Redis, so a crash can't leave "marked seen but state not updated". Alternative: `MULTI` with a `WATCH`, which needs a client-side retry loop for the same guarantee.

## The processor publishes a state row even for duplicates
If the processor crashes after the Redis apply but before publishing to `state-updates`, the redelivery would be its only chance to emit that row. So every delivery publishes a row built from the event itself (scores are absolute, so a duplicate row is identical apart from `processed_at`/`duplicate`). `wp_timeline` is read with `COUNT(DISTINCT event_id)` / `MIN(processed_at)`, and `duplicate=true` rows directly count redeliveries for T5.

## Win-prob features shared by training and serving
`processor/winprob.py` owns `features()`; `model/train.py` imports it, and `wp_model.json` records the feature names, which `WinProb` asserts on load. That rules out train/serve skew in feature code. The model file lives in `processor/` (spec said `model/`) so the processor image only needs that one directory.

## One container image for all components
The processor, replayer and live poller share code (`ingest/normalize.py`, `processor/winprob.py`), so one image with a per-service command means one build and no version skew between publisher and consumer.

## Direct VPC egress to Memorystore (no Serverless VPC Access connector)
Cloud Run reaches Redis's private IP through Direct VPC egress on the default subnet, `PRIVATE_RANGES_ONLY`. A connector is a separate always-on resource (min 2 e2-micro instances) that would bill while idle, which works against the idle ≈ $0 goal (T10).

## Processor handler is sync `def`, not `async def`
Redis and the Pub/Sub publish `.result()` are blocking calls. Inside `async def` they would stall the event loop and serialize every request on an instance. As a plain `def`, FastAPI runs them in its threadpool, so one instance serves many games' in-flight pushes concurrently.

## Ordered push caps per-game throughput (measured, open)
With ordering keys, Pub/Sub push keeps one message outstanding per key. M2's one-game replay drained at ~20 events/s (~50 ms per push round trip incl. Redis + state publish). Throughput is therefore ~20 ev/s x concurrently-active games: 1,000 ev/s needs ~50 games in flight. A real NBA night has <= 15 games and a live game produces < 1 ev/s, so live mode has ~100x headroom; the 1,000 ev/s load test (T1) is the stress case. Options for M5, to decide on measurement: replay many games concurrently (honest: models many simultaneous games), shave the per-message round trip, or switch the processor to a pull subscriber that can pipeline per key (bigger change).

## Alert state is a JSON blob per game, evaluated by a pure function
`evaluate(state, event, wp) -> (alerts, state)` has no I/O, so every rule (window, cooldown, cap, once-per-period) is unit-tested without Redis, and the M4 exit's "expected alerts" were computed by running the same function offline. The state lives in Redis (`alerts:<game_id>`), so dedup survives restarts. No lock is needed because ordered push keeps one message in flight per game.

## Alerts: publish first, then save state; deterministic `alert_id`
If the processor crashes after publishing alerts but before saving alert state, the next event re-fires the same alert with the same `alert_id` (`<game>:CLOSE_LATE:<period>`, `<game>:COMEBACK:<side>`) and the notifier drops it. Saving first would lose the alert instead. That is at-least-once plus dedup, rather than at-most-once. Known gap: a WP_SWING id includes the game second, so a crash in that window could produce a second, differently-timed swing alert.

## Notifier dedup: claim, send, mark
`SET sent:<alert_id> sending NX EX 60` -> POST to Discord -> `SET sent:<alert_id> sent`. Redelivered pushes find `sent` and ack; concurrent ones see `sending` and get a 503 to retry later; Discord failures release the claim. The remaining window (crash between Discord's 2xx and the mark) can double-post once. Closing it fully would need Discord to accept an idempotency key, which webhooks don't.

## Fired alerts and deliveries are separate tables
`alerts` (BigQuery subscription on the `alerts` topic) records what the rules decided, which is what T8/T9 are about. `alert_deliveries` (written via its own topic by the notifier) records Discord's answer and time, for T3. Bulk replays set `notify_discord=false` so Discord's webhook rate limit (~5 req / 2 s) can't distort T8/T9; deliveries are then recorded as `sent_to_discord=false`.

## Discord webhook URL in Secret Manager, injected as env
Cloud Run's `secret_key_ref` resolves `latest` at instance start, so rotating the webhook is `gcloud secrets versions add` + a new revision, with no code or Terraform change. The notifier identifies itself honestly (`User-Agent: ClutchWatch (...)`), as Discord requires of webhook clients.

## Alert rules tuned on 2023-24 (validation season), tested on 2024-25
The spec's rules miss the spec's own T8/T9 targets. Diagnosis on 2023-24 (`uv run python -m bench.tune_alerts`): all 51 close games that missed CLOSE_LATE missed it because the 4-alert cap was already full, and 124 of the 142 alerts in eventual blowouts were WP_SWING in Q1-Q3 (the rest were early COMEBACKs by teams that lost big anyway). Fix, matching the product goal ("moments worth switching to happen late"):
- WP_SWING and COMEBACK fire only in Q4/OT (deficits built earlier still count toward a comeback).
- The global cap stays at 4, but non-CLOSE_LATE alerts may use at most 2 slots, so CLOSE_LATE always has room.
- All thresholds (0.25 WP, 180 s window, 300 s cooldown, 15/3 comeback, 3:00/5 close-late) unchanged.

2023-24, 1,230 games (210 close, 235 blowouts):

| Variant | CLOSE_LATE recall | Blowouts alerted | Alerts/game |
|---|---|---|---|
| spec | 0.757 | 0.426 | 2.16 |
| reserve slots only (other <= 2) | 1.000 | 0.426 | 1.75 |
| late + reserve 3 | 1.000 | 0.047 | 1.45 |
| **late + reserve 2 (chosen)** | **1.000** | **0.047** | **1.30** |
| late + reserve 2 + swing 0.35 | 1.000 | 0.026 | 1.06 |

Chosen as the fewest changes that meet all three targets with margin on alerts/game, without touching any spec threshold. Raising the swing threshold would buy more blowout margin, but it changes the spec's definition of a swing and was not needed on validation. The blowout margin is thin (11/235 = 4.7% vs 5%), so the held-out 2024-25 result may land on either side; it is reported as measured. Alternative considered: exempting CLOSE_LATE from the cap entirely. Same recall, but it breaks the spec's hard "max 4 alerts per game".
