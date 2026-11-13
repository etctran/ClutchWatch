-- T2: publish -> state updated, per distinct event (first processing), Google clocks on both ends.
-- bq query --use_legacy_sql=false --parameter=tag::load1 < bench/queries/t2_latency.sql
WITH first_proc AS (
  SELECT event_id, ANY_VALUE(published_at) published_at, MIN(processed_at) processed_at
  FROM clutchwatch.wp_timeline WHERE STARTS_WITH(game_id, CONCAT(@tag, '-')) GROUP BY event_id
), lat AS (SELECT TIMESTAMP_DIFF(processed_at, published_at, MICROSECOND) / 1000 AS ms FROM first_proc)
SELECT COUNT(*) n,
  APPROX_QUANTILES(ms, 1000)[OFFSET(500)] p50_ms,
  APPROX_QUANTILES(ms, 1000)[OFFSET(900)] p90_ms,
  APPROX_QUANTILES(ms, 1000)[OFFSET(990)] p99_ms,
  APPROX_QUANTILES(ms, 1000)[OFFSET(999)] p999_ms,
  MAX(ms) max_ms
FROM lat
