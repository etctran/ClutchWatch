-- T8 recall + T9 precision/spam for one full-season run, against source final scores.
-- bq query --use_legacy_sql=false --parameter=tag::load1 < bench/queries/t8_t9_alerts.sql
WITH a AS (
  SELECT SUBSTR(game_id, LENGTH(@tag) + 2) game_id, COUNT(DISTINCT alert_id) n,
         COUNTIF(rule = 'CLOSE_LATE') > 0 close_late
  FROM clutchwatch.alerts WHERE STARTS_WITH(game_id, CONCAT(@tag, '-')) GROUP BY 1
), g AS (
  SELECT s.*, ABS(home_score - away_score) margin, IFNULL(a.n, 0) alerts, IFNULL(a.close_late, FALSE) close_late
  FROM clutchwatch.source_games s LEFT JOIN a USING (game_id)
)
SELECT
  COUNTIF(margin <= 3 OR max_period > 4) AS close_games,
  COUNTIF((margin <= 3 OR max_period > 4) AND close_late) AS close_games_with_close_late,
  ROUND(SAFE_DIVIDE(COUNTIF((margin <= 3 OR max_period > 4) AND close_late), COUNTIF(margin <= 3 OR max_period > 4)), 4) AS t8_recall,
  COUNTIF(margin >= 20) AS blowouts,
  COUNTIF(margin >= 20 AND alerts > 0) AS blowouts_alerted,
  ROUND(SAFE_DIVIDE(COUNTIF(margin >= 20 AND alerts > 0), COUNTIF(margin >= 20)), 4) AS t9_blowout_rate,
  ROUND(AVG(alerts), 3) AS t9_mean_alerts_per_game,
  MAX(alerts) AS max_alerts_in_a_game,
  COUNT(*) AS games
FROM g
