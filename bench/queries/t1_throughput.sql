-- T1: per-second throughput for one run. "in" = events published that second (raw_events),
-- "out" = events first processed that second (wp_timeline). Summary over the busiest 10 minutes.
-- bq query --use_legacy_sql=false --parameter=tag::load1 < bench/queries/t1_throughput.sql
WITH tagged_raw AS (
  SELECT TIMESTAMP_TRUNC(published_at, SECOND) s FROM clutchwatch.raw_events WHERE STARTS_WITH(game_id, CONCAT(@tag, '-'))
), tagged_proc AS (
  SELECT TIMESTAMP_TRUNC(MIN(processed_at), SECOND) s FROM clutchwatch.wp_timeline
  WHERE STARTS_WITH(game_id, CONCAT(@tag, '-')) GROUP BY event_id
), per_sec AS (
  SELECT s, COUNTIF(k = 'in') ev_in, COUNTIF(k = 'out') ev_out
  FROM (SELECT s, 'in' k FROM tagged_raw UNION ALL SELECT s, 'out' k FROM tagged_proc) GROUP BY s
), bounds AS (SELECT MIN(s) t0, MAX(s) t1 FROM per_sec WHERE ev_in > 0)
SELECT
  (SELECT TIMESTAMP_DIFF(t1, t0, SECOND) + 1 FROM bounds) AS publish_seconds,
  (SELECT SUM(ev_in) FROM per_sec) AS total_in,
  (SELECT SUM(ev_out) FROM per_sec) AS total_out,
  -- steady-state window: 10 minutes starting 60 s after the first publish
  (SELECT AVG(ev_in) FROM per_sec, bounds WHERE s BETWEEN TIMESTAMP_ADD(t0, INTERVAL 60 SECOND) AND TIMESTAMP_ADD(t0, INTERVAL 659 SECOND)) AS avg_in_per_s_10min,
  (SELECT AVG(ev_out) FROM per_sec, bounds WHERE s BETWEEN TIMESTAMP_ADD(t0, INTERVAL 60 SECOND) AND TIMESTAMP_ADD(t0, INTERVAL 659 SECOND)) AS avg_out_per_s_10min,
  (SELECT APPROX_QUANTILES(ev_out, 100)[OFFSET(5)] FROM per_sec, bounds WHERE s BETWEEN TIMESTAMP_ADD(t0, INTERVAL 60 SECOND) AND TIMESTAMP_ADD(t0, INTERVAL 659 SECOND)) AS p5_out_per_s_10min,
  (SELECT MIN(ev_out) FROM per_sec, bounds WHERE s BETWEEN TIMESTAMP_ADD(t0, INTERVAL 60 SECOND) AND TIMESTAMP_ADD(t0, INTERVAL 659 SECOND)) AS min_out_per_s_10min
