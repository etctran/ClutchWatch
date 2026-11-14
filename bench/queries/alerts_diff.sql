-- Same season, two runs: are the fired alerts identical (ignoring the run tag)? T5 duplicate safety for alerts.
-- bq query --use_legacy_sql=false --parameter=a::load1 --parameter=b::chaos5 < bench/queries/alerts_diff.sql
WITH x AS (SELECT DISTINCT SUBSTR(alert_id, LENGTH(@a) + 2) id FROM clutchwatch.alerts WHERE STARTS_WITH(game_id, CONCAT(@a, '-'))),
     y AS (SELECT DISTINCT SUBSTR(alert_id, LENGTH(@b) + 2) id FROM clutchwatch.alerts WHERE STARTS_WITH(game_id, CONCAT(@b, '-')))
SELECT (SELECT COUNT(*) FROM x) a_alerts, (SELECT COUNT(*) FROM y) b_alerts,
       (SELECT COUNT(*) FROM x WHERE id NOT IN (SELECT id FROM y)) only_in_a,
       (SELECT COUNT(*) FROM y WHERE id NOT IN (SELECT id FROM x)) only_in_b,
       (SELECT COUNT(*) FROM clutchwatch.alerts WHERE STARTS_WITH(game_id, CONCAT(@b, '-'))) b_alert_rows
