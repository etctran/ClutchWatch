-- T6: per-10s processed throughput and latency around a mid-replay redeploy.
-- bq query --use_legacy_sql=false --parameter=tag::chaos6 --parameter=t:TIMESTAMP:'2026-11-13T22:20:00Z' < bench/queries/t6_recovery.sql
WITH e AS (
  SELECT event_id, ANY_VALUE(published_at) pub, MIN(processed_at) proc,
         ARRAY_AGG(revision ORDER BY processed_at LIMIT 1)[OFFSET(0)] rev
  FROM clutchwatch.wp_timeline WHERE STARTS_WITH(game_id, CONCAT(@tag, '-')) GROUP BY event_id
)
SELECT DIV(TIMESTAMP_DIFF(proc, @t, SECOND) + 1000, 10) * 10 - 1000 AS sec_from_redeploy,
       COUNT(*) processed, STRING_AGG(DISTINCT rev) revisions,
       APPROX_QUANTILES(TIMESTAMP_DIFF(proc, pub, MILLISECOND), 100)[OFFSET(50)] p50_ms,
       APPROX_QUANTILES(TIMESTAMP_DIFF(proc, pub, MILLISECOND), 100)[OFFSET(99)] p99_ms
FROM e WHERE proc BETWEEN TIMESTAMP_SUB(@t, INTERVAL 60 SECOND) AND TIMESTAMP_ADD(@t, INTERVAL 120 SECOND)
GROUP BY 1 ORDER BY 1
