-- T2 over time: per-minute latency percentiles for one run (shows warm-up vs steady state).
-- bq query --use_legacy_sql=false --parameter=tag::load1 < bench/queries/t2_by_minute.sql
WITH e AS (
  SELECT ANY_VALUE(published_at) pub, MIN(processed_at) proc
  FROM clutchwatch.wp_timeline WHERE STARTS_WITH(game_id, CONCAT(@tag, '-')) GROUP BY event_id
), b AS (SELECT MIN(pub) t0 FROM e)
SELECT DIV(TIMESTAMP_DIFF(pub, t0, SECOND), 60) AS minute, COUNT(*) n,
       APPROX_QUANTILES(TIMESTAMP_DIFF(proc, pub, MICROSECOND) / 1000, 100)[OFFSET(50)] p50_ms,
       APPROX_QUANTILES(TIMESTAMP_DIFF(proc, pub, MICROSECOND) / 1000, 100)[OFFSET(99)] p99_ms
FROM e, b GROUP BY 1 ORDER BY 1
