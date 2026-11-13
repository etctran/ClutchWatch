-- T2 diagnosis: latency vs. time since the previous event of the SAME game was published.
-- If ordered push (one in-flight message per game) causes the latency, events that follow a
-- long gap in their game should be fast and events inside a burst should be slow.
-- bq query --use_legacy_sql=false --parameter=tag::load1 < bench/queries/t2_by_gap.sql
WITH e AS (
  SELECT event_id, game_id, ANY_VALUE(published_at) pub, MIN(processed_at) proc
  FROM clutchwatch.wp_timeline WHERE STARTS_WITH(game_id, CONCAT(@tag, '-')) GROUP BY event_id, game_id
), g AS (
  SELECT TIMESTAMP_DIFF(proc, pub, MICROSECOND) / 1000 ms,
         TIMESTAMP_DIFF(pub, LAG(pub) OVER (PARTITION BY game_id ORDER BY pub), MILLISECOND) gap_ms
  FROM e
)
SELECT CASE WHEN gap_ms IS NULL THEN '0 first event'
            WHEN gap_ms < 100 THEN '1 <100ms (burst)'
            WHEN gap_ms < 1000 THEN '2 100ms-1s'
            WHEN gap_ms < 5000 THEN '3 1-5s'
            ELSE '4 >=5s (quiet)' END AS gap_since_prev_in_game,
       COUNT(*) n,
       APPROX_QUANTILES(ms, 100)[OFFSET(50)] p50_ms,
       APPROX_QUANTILES(ms, 100)[OFFSET(99)] p99_ms
FROM g GROUP BY 1 ORDER BY 1
