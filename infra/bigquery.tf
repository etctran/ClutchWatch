resource "google_bigquery_dataset" "cw" {
  dataset_id                 = "clutchwatch"
  location                   = "US"
  delete_contents_on_destroy = true
}

locals {
  event_cols = [
    { name = "event_id", type = "STRING", mode = "REQUIRED" },
    { name = "game_id", type = "STRING", mode = "REQUIRED" },
    { name = "order_number", type = "INT64", mode = "REQUIRED" },
    { name = "period", type = "INT64", mode = "NULLABLE" },
    { name = "clock_seconds", type = "FLOAT64", mode = "NULLABLE" },
    { name = "home_team", type = "STRING", mode = "NULLABLE" },
    { name = "away_team", type = "STRING", mode = "NULLABLE" },
    { name = "home_score", type = "INT64", mode = "NULLABLE" },
    { name = "away_score", type = "INT64", mode = "NULLABLE" },
    { name = "event_type", type = "STRING", mode = "NULLABLE" },
    { name = "source", type = "STRING", mode = "NULLABLE" },
    { name = "published_at", type = "TIMESTAMP", mode = "NULLABLE" },
  ]
}

resource "google_bigquery_table" "raw_events" {
  dataset_id          = google_bigquery_dataset.cw.dataset_id
  table_id            = "raw_events"
  deletion_protection = false
  schema = jsonencode(concat(local.event_cols, [
    { name = "action_number", type = "INT64", mode = "NULLABLE" },
  ]))
}

# One row per processed delivery (duplicates included, flagged); read with DISTINCT event_id
resource "google_bigquery_table" "wp_timeline" {
  dataset_id          = google_bigquery_dataset.cw.dataset_id
  table_id            = "wp_timeline"
  deletion_protection = false
  schema = jsonencode(concat(local.event_cols, [
    { name = "home_wp", type = "FLOAT64", mode = "NULLABLE" },
    { name = "processed_at", type = "TIMESTAMP", mode = "NULLABLE" },
    { name = "duplicate", type = "BOOL", mode = "NULLABLE" },
    { name = "revision", type = "STRING", mode = "NULLABLE" },
  ]))
}

resource "google_bigquery_dataset_iam_member" "pubsub_bq" {
  dataset_id = google_bigquery_dataset.cw.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = local.pubsub_agent
}
