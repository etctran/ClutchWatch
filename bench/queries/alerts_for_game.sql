-- Fired alerts vs Discord deliveries for one game, with publish -> Discord-accepted latency.
-- Usage: bq query --use_legacy_sql=false --parameter=game_id::0022400119 < bench/queries/alerts_for_game.sql
SELECT a.alert_id, a.rule, COUNT(*) OVER (PARTITION BY a.alert_id) AS fired_rows,
       d.discord_status, d.deliveries,
       TIMESTAMP_DIFF(d.delivered_at, a.published_at, MILLISECOND) AS publish_to_discord_ms,
       a.text
FROM clutchwatch.alerts a
LEFT JOIN (
  SELECT alert_id, ANY_VALUE(discord_status) AS discord_status, COUNT(*) AS deliveries, MIN(delivered_at) AS delivered_at
  FROM clutchwatch.alert_deliveries GROUP BY alert_id
) d USING (alert_id)
WHERE a.game_id = @game_id
ORDER BY a.alerted_at
