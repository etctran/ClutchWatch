-- T4: event loss. Source vs published (raw_events) vs processed (wp_timeline), distinct event_id.
-- bq query --use_legacy_sql=false --parameter=tag::load1 --parameter=season:INT64:2024 < bench/queries/t4_loss.sql
SELECT
  (SELECT SUM(events) FROM clutchwatch.source_games WHERE season = @season) AS source_events,
  (SELECT COUNT(DISTINCT event_id) FROM clutchwatch.raw_events WHERE STARTS_WITH(game_id, CONCAT(@tag, '-'))) AS raw_distinct,
  (SELECT COUNT(*) FROM clutchwatch.raw_events WHERE STARTS_WITH(game_id, CONCAT(@tag, '-'))) AS raw_rows,
  (SELECT COUNT(DISTINCT event_id) FROM clutchwatch.wp_timeline WHERE STARTS_WITH(game_id, CONCAT(@tag, '-'))) AS processed_distinct,
  (SELECT COUNTIF(duplicate) FROM clutchwatch.wp_timeline WHERE STARTS_WITH(game_id, CONCAT(@tag, '-'))) AS redelivered_rows,
  (SELECT COUNT(*) FROM clutchwatch.raw_events r WHERE STARTS_WITH(r.game_id, CONCAT(@tag, '-'))
     AND NOT EXISTS (SELECT 1 FROM clutchwatch.wp_timeline w WHERE w.event_id = r.event_id)) AS published_not_processed
