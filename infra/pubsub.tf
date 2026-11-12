resource "google_pubsub_topic" "game_events" { name = "game-events" }
resource "google_pubsub_topic" "state_updates" { name = "state-updates" }
resource "google_pubsub_topic" "game_events_dlq" { name = "game-events-dlq" }

# Processor: push, ordered per game (ordering_key = game_id), DLQ after 5 attempts
resource "google_pubsub_subscription" "processor" {
  name                    = "game-events-processor"
  topic                   = google_pubsub_topic.game_events.id
  enable_message_ordering = true
  ack_deadline_seconds    = 30

  push_config {
    push_endpoint = google_cloud_run_v2_service.processor.uri
    oidc_token { service_account_email = google_service_account.pusher.email }
  }
  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.game_events_dlq.id
    max_delivery_attempts = 5
  }
  retry_policy {
    minimum_backoff = "1s"
    maximum_backoff = "30s"
  }
}

# Holds dead-lettered events so they can be inspected (T4: must stay empty)
resource "google_pubsub_subscription" "dlq" {
  name                       = "game-events-dlq"
  topic                      = google_pubsub_topic.game_events_dlq.id
  message_retention_duration = "604800s"
}

# Pub/Sub writes straight to BigQuery: no custom writer code
resource "google_pubsub_subscription" "raw_events_bq" {
  name  = "game-events-bq"
  topic = google_pubsub_topic.game_events.id
  bigquery_config {
    table               = "${var.project}.${google_bigquery_dataset.cw.dataset_id}.${google_bigquery_table.raw_events.table_id}"
    use_table_schema    = true
    drop_unknown_fields = true
  }
  depends_on = [google_bigquery_dataset_iam_member.pubsub_bq]
}

resource "google_pubsub_subscription" "wp_timeline_bq" {
  name  = "state-updates-bq"
  topic = google_pubsub_topic.state_updates.id
  bigquery_config {
    table               = "${var.project}.${google_bigquery_dataset.cw.dataset_id}.${google_bigquery_table.wp_timeline.table_id}"
    use_table_schema    = true
    drop_unknown_fields = true
  }
  depends_on = [google_bigquery_dataset_iam_member.pubsub_bq]
}

# ---- IAM
resource "google_pubsub_topic_iam_member" "publisher_game_events" {
  topic  = google_pubsub_topic.game_events.id
  role   = "roles/pubsub.publisher"
  member = "serviceAccount:${google_service_account.publisher.email}"
}
resource "google_pubsub_topic_iam_member" "processor_state_updates" {
  topic  = google_pubsub_topic.state_updates.id
  role   = "roles/pubsub.publisher"
  member = "serviceAccount:${google_service_account.processor.email}"
}
# DLQ forwarding is done by the Pub/Sub service agent
resource "google_pubsub_topic_iam_member" "agent_dlq_publish" {
  topic  = google_pubsub_topic.game_events_dlq.id
  role   = "roles/pubsub.publisher"
  member = local.pubsub_agent
}
resource "google_pubsub_subscription_iam_member" "agent_processor_sub" {
  subscription = google_pubsub_subscription.processor.id
  role         = "roles/pubsub.subscriber"
  member       = local.pubsub_agent
}
