# Results

Every number here comes from a command that was actually run; the command (and, for
pipeline metrics, the BigQuery query in `bench/queries/`) is listed with it.

## Summary

| # | Metric | Target | Measured | Met? |
|---|---|---|---|---|
| T1 | Sustained throughput | >= 1,000 ev/s for 10 min | 686,008 events published in 686 s; processed avg 999.5 ev/s over the 10-min window (per-second min 361, p5 475) | Yes (average); see per-second note |
| T2 | Publish -> state updated | p50 < 150 ms, p99 < 1 s | 4 full runs at 1,000 ev/s: p50 1,328 / 779 / 85 / 756 ms; p99 9.3 / 7.0 / 7.1 / 15.1 s (processor's own request time p50 23 ms) | **No** (p50 met in 1 of 4 runs, p99 in none); time is spent inside Pub/Sub before push dispatch |
| T5 | Duplicate safety, 10% forced redelivery | 0 double-applied; final scores match | 68,797 redeliveries; 0 double-applied, 0 lost; 1,230/1,230 final scores exact; alerts identical to clean run (1,615 = 1,615) | Yes |
| T6 | Crash recovery (redeploy mid-replay) | no loss, correct final state; stretch recovery < 30 s | 0 lost of 686,008; 1,230/1,230 exact; alerts identical; no throughput gap; latency back to baseline ~70 s after the redeploy started | Yes; stretch: no stall at all, latency bump ~40 s |
| T4 | Event loss, full season | 0 lost of ~600K | 0 lost of 686,008 in each of 5 full-season runs (load1, chaos5, chaos6, chaos7, load2); DLQ empty; 1,230/1,230 games correct in Redis every time | Yes |
| T7 | Model quality | Brier beats baselines; calibration <= 0.05/decile | Brier 0.1641 (baselines 0.2500 / 0.2497); max decile error 0.0310 | Yes (+ stretch) |
| T8 | Alert recall | >= 90% of games <=3 pts or OT get CLOSE_LATE | 221/221 = 100% | Yes (+ stretch) |
| T9 | Alert spam | <= 5% of blowouts alerted; <= 1.5 alerts/game | 17/259 = 6.6% of blowouts; 1.31 alerts/game | **No** (blowouts, narrowly); alerts/game yes |

T3, T10, T11: see below / pending.

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

Target met: test Brier beats both baselines, every decile within 0.05. Stretch (Brier ≤ 0.18) met.

![calibration](model/calibration_test_2024.png)

Caveats worth saying out loud: rows within a game are correlated, so the effective sample size
is closer to the 1,230 test games than to 144K events; and calibration is reported per decile of
predicted probability pooled over all game states, not per game phase. The weakest band is
0.6-0.7 (predicted 0.643, observed 0.612).
