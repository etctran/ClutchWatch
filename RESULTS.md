# Results

Every number here comes from a command that was actually run; the command (and, for
pipeline metrics, the BigQuery query in `bench/queries/`) is listed with it.

## Summary

Final design: push delivery (`processor_mode = "push"`), alert rules as retuned on 2023-24 (DECISIONS). Seasons: model trained 2020-21..2022-23, tuned on 2023-24, tested on 2024-25 and on 2025-26 (never used for any choice).

| # | Metric | Target | Measured | Met? |
|---|---|---|---|---|
| T1 | Sustained throughput | >= 1,000 ev/s for 10 min | Every full-season run kept up: e.g. `load1` 686,008 events in 686 s, processed avg 999.5 ev/s (per-second min 361); `fresh25` 999.7 ev/s (min 583) | Yes (average) |
| T2 | Publish -> state updated | p50 < 150 ms, p99 < 1 s | Push, 5 full runs at 1,000 ev/s: p50 1,328 / 779 / 85 / 756 / 461 ms, p99 7-15 s. StreamingPull, 2 runs: p50 11.2 s, 2.2 s. Processor's own time p50 23 ms | **No** (p50 met in 1 of 7 runs, p99 in none); time is inside Pub/Sub before delivery, see sections below |
| T3 | Alert latency, publish -> Discord accepted | p95 < 2 s (stretch < 1 s) | 10 OT games at real pace x30: p50 385 ms, p95 914 ms, 36/36 delivered once (same games over-driven at 50 ev/s into 1-2 games: p95 30.1 s) | Yes (+ stretch) |
| T4 | Event loss | 0 lost | 0 lost in each of 8 full-season runs (7 x 686,008 events on 2024-25, 1 x 708,268 on 2025-26); DLQ empty; every game's final Redis state exact every time | Yes |
| T5 | Duplicate safety, 10% forced redelivery | 0 double-applied; final scores match | 68,797 redeliveries; 0 double-applied, 0 lost; 1,230/1,230 final scores exact; alerts identical to a clean run (1,615 = 1,615) | Yes |
| T6 | Crash recovery (redeploy mid-replay) | no loss, correct final state; stretch recovery < 30 s | 0 lost; 1,230/1,230 exact; alerts identical; no throughput gap; latency back to baseline ~70 s after the redeploy started | Yes; stretch: no stall, latency bump ~40 s |
| T7 | Model quality | Brier beats baselines; calibration <= 0.05/decile | 2024-25: Brier 0.1641 (baselines 0.2500 / 0.2497), max decile error 0.031. 2025-26: 0.1612 (0.2500 / 0.2485), 0.023 | Yes (+ stretch), both seasons |
| T8 | Alert recall | >= 90% of games <= 3 pts or OT get CLOSE_LATE | 2025-26 (final rules): 210/210 = 100%. 2024-25 (first tuning): 221/221 | Yes (+ stretch) |
| T9 | Alert spam | <= 5% of blowouts alerted; <= 1.5 alerts/game | 2025-26 (final rules): **10/281 = 3.6%**, **0.97/game**. 2024-25 (first tuning): 17/259 = 6.6%, 1.31/game | **Yes** on the held-out season (missed with the first tuning) |
| T10 | Cost | campaign < $10; idle ~ $0 | pending: billing report lags ~1 day | pending |
| T11 | Reproducible deploy | one script stands it up; stretch < 10 min | `scripts/deploy.sh` from the torn-down state: 409 s (6 min 49 s) incl. image build | Yes (+ stretch) |

## Load run `load1` (T1, T2, T4, T8, T9)

Run 2026-11-13, 20:59-21:11 UTC, from the `replayer` Cloud Run Job (Google clocks on both ends):

```
bench/run_load.sh load1 1000
# = replayer --csv data/replay/season_2024.parquet --target-rate 1000 --align --run-tag load1
```

The whole 2024-25 regular season (1,230 games, 686,008 events) with every game starting at the same instant (`--align`). Why aligned: ordered push allows one in-flight message per game, so a real night's ~15 simultaneous games can't reach 1,000 ev/s however fast the pipeline is (see DECISIONS). Aligned, it is 1,230 simultaneous games at ~0.8 ev/s each: a fan-out test, not a one-hot-game test. Discord posting was off (`notify_discord=false`); alerts were still evaluated and recorded. Replayer log: `published=686008 failed=0 sent=686008 seconds=686.0 rate=1000/s`.

### T1: throughput (`bench/queries/t1_throughput.sql`)

| publish seconds | total in (raw_events) | total out (wp_timeline, distinct) | avg in/s, 10 min | avg out/s, 10 min | p5 out/s | min out/s |
|---|---|---|---|---|---|---|
| 687 | 686,008 | 686,008 | 999.99 | 999.53 | 475 | 361 |

Sustained average met: everything published was processed and the backlog stayed bounded (latency p99 under ~5 s every minute, below). Per second, output is bursty (lowest second 361, p5 475) because ordered push releases each game's queued events in clumps. Stretch (5,000 ev/s) not attempted; at 1,000 ev/s push latency was already rising with load (T2), so it would mostly measure that.

### T2: latency (`bench/queries/t2_latency.sql`, all full-season runs at 1,000 ev/s)

| run | conditions | p50 | p90 | p99 | p99.9 |
|---|---|---|---|---|---|
| `load1` | clean | 1,328 ms | 3,006 ms | 9,290 ms | 14,590 ms |
| `chaos6` | clean in effect (its redeploy landed after the replay) | 779 ms | 1,999 ms | 6,999 ms | 11,507 ms |
| `chaos7` | processor redeployed mid-run (T6) | 85 ms | 742 ms | 7,142 ms | 12,583 ms |
| `load2` | clean | 756 ms | 2,085 ms | 15,085 ms | 18,373 ms |

**Missed.** p50 < 150 ms held in one run of four; p99 < 1 s in none. Where the time goes, measured:

1. **Not the processor.** Cloud Run request logs under load (`load1`, 2,000 requests, 9 instances): p50 23 ms, p99 55 ms, all 204. Pub/Sub's own `push_request_latencies` (Cloud Monitoring) shows a ~35 ms mean push round trip in every steady minute of both `chaos7` and `load2`.
2. **Not a concurrency cap.** `num_outstanding_messages` sat at ~30-45 in both runs, which is just Little's law for 1,000 ev/s x 35 ms. Backlog (`num_undelivered_messages`) was ~150-500 in both.
3. **Same-game bursts queue behind each other (ordering), by design.** `bench/queries/t2_by_gap.sql`: events published < 100 ms after the previous event of the same game are slower than events after a >= 5 s quiet gap (`load2`: p50 802 vs 399 ms; `chaos7`: 179 vs 41 ms).
4. **The run-to-run difference is inside Pub/Sub, before push dispatch.** Quiet events have nothing ahead of them in their game, yet their p50 was 41 ms in `chaos7` and 399 ms in `load2`, with the same ~35 ms push round trip and the same processor. Root cause not isolated: it is in the managed service, not in anything this project controls.
5. **Minute 0 is an artifact of `--align`.** All 1,230 games' first events land in the same second: first-event p50 11.5 s (`chaos7`) to 17.6 s (`load2`); minute-0 p99 12.8-18.5 s (`bench/queries/t2_by_minute.sql`). Steady minutes in the fast run were p50 43-68 ms, p99 444-1,023 ms (outside the redeploy minutes).

An earlier version of this section attributed the miss to a fixed per-load ceiling in ordered push, and a later draft to warm-up. Both were wrong; the four-run table above is what supports the conclusion. The design response (not implemented) is in DECISIONS: a StreamingPull worker, or dropping ordering keys in favor of the processor's existing `order_number` check.

### T4: loss (`bench/queries/t4_loss.sql`, `bench/check_state.py`, DLQ pull)

| source events | raw_events distinct | raw rows | processed distinct | redelivered rows | published but not processed |
|---|---|---|---|---|---|
| 686,008 | 686,008 | 686,008 | 686,008 | 5 | 0 |

DLQ (`game-events-dlq`): 0 messages. Redis (`uv run python -m bench.check_state load1`): `games_in_redis=1230 mismatched=0 applied_total=686008 source_events=686008`, i.e. every game's `applied` counter equals its source event count and its final score equals the source final score.

### T8 / T9: alerts (`bench/queries/t8_t9_alerts.sql`)

Rules as tuned on 2023-24 (DECISIONS: "Alert rules tuned on 2023-24"); 2024-25 is held out.

| close games (<=3 or OT) | with CLOSE_LATE | T8 recall | blowouts (>=20) | blowouts alerted | T9 rate | alerts/game | max in a game |
|---|---|---|---|---|---|---|---|
| 221 | 221 | **100%** | 259 | 17 | **6.6%** | **1.31** | 4 |

T8 met (stretch too). T9 alerts/game met; blowout rate missed narrowly: 6.6% vs 5% (validation had 4.7%). For reference, the spec's untuned rules on the same season (offline, same `evaluate` code): 71% recall, 50% of blowouts alerted, 2.23/game.

## T2, second attempt: StreamingPull instead of push

Hypothesis after the four push runs: the time was in Pub/Sub's push dispatch, so a StreamingPull client inside the processor (`processor_mode = "pull"`, same `process()` code, same ordering keys, same Redis apply, same DLQ) should remove it.

### `pull1`: 2 instances x 1 vCPU, 64 threads, 4,000 outstanding per instance

```
TF_EXTRA_VARS="-var notify_discord=false" ./scripts/deploy.sh   # processor_mode defaults to pull
bench/run_load.sh pull1 1000                                    # 2026-11-14 13:45-13:58 UTC
```

| | result |
|---|---|
| correctness | 686,008 / 686,008 processed, 0 lost, DLQ 0, 1,230/1,230 final scores exact, 5 natural redeliveries |
| throughput (`t1_throughput.sql`) | in 1,000.1 ev/s, out **936.1 ev/s** over the 10-min window: the processor fell behind |
| latency (`t2_latency.sql`) | p50 **11,169 ms**, p90 47 s, p99 291 s, max 580 s |
| by minute | p50 4.4 s / 2.6 s in minutes 0-1, then 13-14 s every minute from minute 3; p99 grew to 479 s |
| why (Cloud Monitoring) | both instances at **1.04 CPU** (of 1.0) from minute 6 to the end; `num_undelivered_messages` grew linearly to 40,200; `oldest_unacked_message_age` grew 60 s per minute to 477 s |
| also | the deploy that started the run left the previous revision serving until minute 5; 719 `expired_ack_deadlines` during the handover |

**Worse than push on every latency number.** The Python Pub/Sub client is CPU-bound at roughly 470 events/s per vCPU here (lease management for thousands of outstanding messages, per-key ordered dispatch, 32-64 threads under the GIL, plus the handler's own ~2 ms). Push had Cloud Run autoscaling to 9-10 instances; this pull deployment had 2 fixed vCPUs, so the comparison was not like for like. Even before the backlog formed (minute 1, p50 2.6 s) pull was slower than push's steady state (p50 0.8-1.8 s).

### `pull2`: 4 instances x 2 vCPU, 32 threads, 1,000 outstanding per instance

```
bench/run_load.sh pull2 1000     # 2026-11-14 14:06-14:22 UTC; single revision serving throughout
```

| | result |
|---|---|
| correctness | 686,008 / 686,008, 0 lost, DLQ 0, 1,230/1,230 exact, 0 redeliveries |
| throughput | in 1,000.6 ev/s, out 999.4 ev/s (per-second min 666, p5 875: smoother than push's 361 / 475) |
| latency | p50 **2,191 ms**, p90 4,350 ms, p99 6,363 ms, p99.9 8,430 ms, max 12.5 s |
| by minute | p50 2.0-2.8 s in every steady minute (1.2 s in minute 5); p99 4.8-6.2 s |
| by gap | burst events p50 2.1 s; quiet events (nothing ahead of them in their game) p50 1.5 s |
| Cloud Monitoring | CPU 0.46-0.48 of 2.0 per instance (not CPU-bound); `num_undelivered_messages` steady at 1,500-2,500 (about 2 s of traffic) for the whole run, below the 4 x 1,000 the clients' flow control allowed (`num_outstanding_messages` is not emitted for pull subscriptions, so flow control not binding is inferred from that and the idle CPU); `oldest_unacked_message_age` 4-5 s; 0 expired ack deadlines |

Resourced like push, pull is still slower: p50 2.2 s against push's 0.8-1.3 s (best push run 85 ms). The steady ~2,000-message undelivered backlog with idle clients says the wait is on the Pub/Sub side before messages reach the stream, which this project can't change. T1 improves (smoother per-second output), T2 gets worse.

**Decision:** `processor_mode` defaults back to `push`; pull stays in the code and Terraform for comparison. The latency hypothesis was wrong and the two runs that disproved it are the result. T2 remains missed on the final design.

## Fresh season run `fresh25` (T8/T9 final rules; T1/T2/T4 again)

The alert retune was chosen on 2023-24; 2024-25 had already been looked at, so the test is 2025-26 (1,230 games, 708,268 events, 210 close games, 281 blowouts), which no model, rule or threshold was ever fitted or chosen on.

```
SEASON=2025 bench/run_load.sh fresh25 1000     # 2026-11-14 14:28-14:42 UTC, push mode
```

| query | result |
|---|---|
| `t8_t9_alerts.sql` (`season=2025`) | close games 210, with CLOSE_LATE 210 (**100%**); blowouts 281, alerted 10 (**3.6%**); **0.97** alerts/game; max 4 in a game |
| `t4_loss.sql` | source 708,268 = raw = processed distinct; 1 natural redelivery; 0 published-not-processed; DLQ 0 |
| `check_state fresh25 2025` | `games_in_redis=1230 mismatched=0 applied_total=708268` |
| `t1_throughput.sql` | in 1,000.3 ev/s, out 999.7 ev/s; per-second min 583, p5 668 |
| `t2_latency.sql` | p50 461 ms, p90 1,453 ms, p99 9,313 ms; steady minutes p50 204-590 ms, p99 1.1-2.9 s; minute 0 p99 14.9 s (aligned start) |

T9 now passes on a season nobody tuned on, with margin (3.6% vs 5%), though less margin than validation suggested (0.9%). Expect that gap: validation is the season the thresholds were picked on.

## T3: alert latency (runs `t3a`, `t3b`; `bench/queries/t3_alert_latency.sql`)

Discord posting on (`notify_discord=true`), the same 10 overtime games of 2024-25 (`0022400002,...,0022400144`, 6,237 events), from the replayer Job. Latency = Discord's 2xx time (`alert_deliveries.delivered_at`, notifier clock) minus the triggering event's `published_at` (replayer clock).

```
# t3b: real game timeline, 30x faster, all 10 games tipping off together (~2 ev/s per game)
gcloud run jobs execute replayer --args="^;^--csv;data/replay/season_2024.parquet;--topic;projects/clutchwatch-bywa6u/topics/game-events;--speedup;30;--align;--games;<10 ids>;--run-tag;t3b"
# t3a: same games, --target-rate 50, not aligned (games run 1-2 at a time, so ~50 ev/s into a single game)
```

| run | pace | alerts fired | delivered (2xx) | max deliveries/alert | p50 | p95 | max | p95 publish->alert | p95 alert->Discord |
|---|---|---|---|---|---|---|---|---|---|
| **`t3b`** | real x30 | 36 | 36 | 1 | **385 ms** | **914 ms** | 1,016 ms | 186 ms | 871 ms |
| `t3a` | 50 ev/s, 1-2 games at a time | 36 | 36 | 1 | 13,958 ms | 30,119 ms | 31,156 ms | 27,181 ms | 2,938 ms |

At a realistic per-game pace (still 30x denser than a live game) T3 and its stretch are met, and Discord's own response is most of the remaining time. `t3a` shows the same per-game limit as T2: driving one game at 50 ev/s against a ~20 ev/s ordered drain builds a backlog in front of the alert. Same alerts fired in both runs, each delivered exactly once.

The `t3b` run's events also give a low-load latency point for T2 (`t2_latency.sql`, tag `t3b`, ~17 ev/s total): p50 77 ms, p99 923 ms. That is within T2's thresholds, but T2 is defined at 1,000 ev/s, so it is a data point, not a pass.

## T5: duplicate safety (run `chaos5`)

Processor deployed with `force_nack_rate=0.1`: after an event is applied (Redis Lua apply succeeded, state row published), 10% get HTTP 500 anyway, so Pub/Sub redelivers events that were already applied. Then the full season:

```
terraform -chdir=infra apply -var force_nack_rate=0.1 ...   # FORCE_NACK_RATE=0.1 on the processor
bench/run_load.sh chaos5 1000                               # 2026-11-13 21:31-21:44 UTC
```

| source events | processed distinct | redelivered rows (`duplicate=true`) | published but not processed | DLQ |
|---|---|---|---|---|
| 686,008 | 686,008 | 68,797 | 0 | 0 |

- `uv run python -m bench.check_state chaos5`: `games_in_redis=1230 mismatched=0 applied_total=686008 source_events=686008`. Each game's `applied` counter (incremented only when `SET seen:<event_id> NX` succeeds) equals its source event count, so 0 events were double-applied, and every final score matches the source exactly.
- Alerts, `bench/queries/alerts_diff.sql` vs the clean `load1` run: 1,615 vs 1,615 distinct alerts, 0 only in either, 1,615 alert rows (no duplicate alert rows).
- Cost of the chaos: each forced NACK pauses its game's ordered stream for the retry backoff (min 1 s), so processing finished at 22:06:14 UTC, 22 min after publishing ended (21:43:58). Correctness held, latency did not, as expected.

## T6: crash recovery (run `chaos7`)

```
caffeinate -i bench/run_restart.sh chaos7 1000 250000
# full-season replay; once 250,000 events are in raw_events, `gcloud run services update processor`
```

Redeploy started 2026-11-13 23:53:02.228 UTC with 250,655 events published; new revision `processor-00010-cz2` ready at 23:53:36.357 (34 s). Cloud Run starts the new revision, shifts traffic, and drains in-flight requests on the old one; any request cut off is NACKed by Pub/Sub's ack deadline and redelivered (absorbed by the idempotent apply).

| check | result |
|---|---|
| loss (`t4_loss.sql`) | source 686,008 = raw distinct = processed distinct; published-not-processed 0 |
| final state (`check_state chaos7`) | `games_in_redis=1230 mismatched=0 applied_total=686008` |
| alerts vs `load1` (`alerts_diff.sql`) | 1,615 vs 1,615, 0 differences, 1,615 rows |

Around the redeploy (`bench/queries/t6_recovery.sql`, 10 s buckets of first-processing time):

| s from redeploy | processed | revision(s) | p50 ms | p99 ms |
|---|---|---|---|---|
| -20 | 9,995 | 00009 | 48 | 489 |
| -10 | 10,005 | 00009 | 40 | 398 |
| 0 | 10,974 | 00009 | 43 | 430 |
| +10 | 10,026 | 00009 + 00010 | 40 | 409 |
| +20 | 10,008 | 00010 | 40 | 329 |
| +30 | 9,647 | 00010 | 196 | 862 |
| +40 | 9,935 | 00010 | 390 | 1,450 |
| +50 | 9,665 | 00010 | 609 | 1,991 |
| +60 | 10,658 | 00010 | 352 | 1,521 |
| +70 | 10,019 | 00010 | 132 | 629 |
| +80 | 10,047 | 00010 | 99 | 395 |

Throughput never dropped (every 10 s bucket processed ~10,000 events, i.e. ~1,000/s); traffic moved to the new revision within 10-20 s; latency rose from +30 s to +60 s (new revision scaling out its instances, p50 peak 609 ms) and was back near baseline at +70 s. Under the "no processing stall" reading the 30 s stretch is met; under "latency back to baseline" it took ~70 s from the start of the redeploy (~36 s after the new revision was ready).

A first attempt (`chaos6`) used a fixed `sleep` before redeploying; the laptop slept, the redeploy landed 42 min after that replay had ended, so it tested nothing. It still counts as a clean full-season run: 0 lost, 1,230/1,230 exact.

## T11: reproducibility

```
time TF_EXTRA_VARS="-var notify_discord=false" ./scripts/deploy.sh    # 2026-11-14 13:29:36 -> 13:36:25 UTC
```

From the state `scripts/teardown.sh redis` leaves (no Redis, no Cloud Run services, no processor/notifier subscriptions; topics, BigQuery, IAM and WIF still there): **409 s** to a serving pipeline, including `terraform init`, the Cloud Build image build (~1 min) and the release. Memorystore creation is most of it (4-5 min). The first-ever apply on 2026-11-12 (21 resources from nothing, before the notifier/replayer/WIF existed) took 6 min 27 s plus a ~1 min build. Not timed: a completely fresh GCP project (APIs, budget, Secret Manager value), which needs a human for billing and the Discord webhook anyway.

## T7: Model quality

Command (2026-11-12):

```
uv run --group model python -m model.train      # train 2020-21..2022-23, export processor/wp_model.json
uv run --group model python -m model.evaluate   # val 2023-24, test 2024-25, saves the plot
```

Logistic regression on `[margin, minutes_left, margin / sqrt(seconds_left + 1)]`, one row per
scoring event. Trained on 415,765 scoring events from 3,540 games (2020-21 to 2022-23).

| Split | Scoring events | Games | Brier (model) | Brier (constant 0.5) | Brier (leader wins) | Max per-decile calibration error |
|---|---|---|---|---|---|---|
| val 2023-24 | 145,642 | 1,230 | 0.1614 | 0.2500 | 0.2420 | 0.0438 |
| **test 2024-25** | 144,139 | 1,230 | **0.1641** | 0.2500 | 0.2497 | **0.0310** |
| **test 2025-26** (added 2026-11-14; never used for any tuning) | 148,450 | 1,230 | **0.1612** | 0.2500 | 0.2485 | **0.0232** |

Target met: test Brier beats both baselines, every decile within 0.05. Stretch (Brier ≤ 0.18) met.

![calibration](model/calibration_test_2024.png)

Caveats worth saying out loud: rows within a game are correlated, so the effective sample size
is closer to the 1,230 test games than to 144K events; and calibration is reported per decile of
predicted probability pooled over all game states, not per game phase. The weakest band is
0.6-0.7 (predicted 0.643, observed 0.612).
