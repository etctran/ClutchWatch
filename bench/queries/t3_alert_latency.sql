-- T3: publish of the triggering event -> Discord accepted (2xx), per alert.
-- bq query --use_legacy_sql=false --parameter=tag::t3a < bench/queries/t3_alert_latency.sql
WITH d AS (
  SELECT alert_id, ANY_VALUE(published_at) pub, ANY_VALUE(alerted_at) alerted, MIN(delivered_at) delivered,
         ANY_VALUE(discord_status) status, COUNT(*) deliveries
  FROM clutchwatch.alert_deliveries WHERE STARTS_WITH(game_id, CONCAT(@tag, '-')) AND sent_to_discord GROUP BY alert_id
)
SELECT COUNT(*) alerts_delivered, COUNTIF(status BETWEEN 200 AND 299) discord_2xx, MAX(deliveries) max_deliveries_per_alert,
  (SELECT COUNT(DISTINCT alert_id) FROM clutchwatch.alerts WHERE STARTS_WITH(game_id, CONCAT(@tag, '-'))) alerts_fired,
  APPROX_QUANTILES(TIMESTAMP_DIFF(delivered, pub, MILLISECOND), 100)[OFFSET(50)] p50_ms,
  APPROX_QUANTILES(TIMESTAMP_DIFF(delivered, pub, MILLISECOND), 100)[OFFSET(95)] p95_ms,
  MAX(TIMESTAMP_DIFF(delivered, pub, MILLISECOND)) max_ms,
  APPROX_QUANTILES(TIMESTAMP_DIFF(alerted, pub, MILLISECOND), 100)[OFFSET(95)] p95_publish_to_alert_ms,
  APPROX_QUANTILES(TIMESTAMP_DIFF(delivered, alerted, MILLISECOND), 100)[OFFSET(95)] p95_alert_to_discord_ms
FROM d
