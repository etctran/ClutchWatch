-- Per game: distinct events in raw_events vs processed (wp_timeline), redeliveries, final score.
-- Usage: bq query --use_legacy_sql=false --parameter=game_id::0022400001 < bench/queries/counts_by_game.sql
WITH raw AS (
  SELECT game_id, COUNT(*) AS raw_rows, COUNT(DISTINCT event_id) AS raw_events
  FROM clutchwatch.raw_events WHERE game_id = @game_id GROUP BY game_id
), proc AS (
  SELECT game_id, COUNT(DISTINCT event_id) AS processed_events, COUNTIF(duplicate) AS redeliveries,
         ARRAY_AGG(STRUCT(home_team, home_score, away_team, away_score) ORDER BY order_number DESC LIMIT 1)[OFFSET(0)] AS final
  FROM clutchwatch.wp_timeline WHERE game_id = @game_id GROUP BY game_id
)
SELECT * FROM raw FULL JOIN proc USING (game_id)
