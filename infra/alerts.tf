resource "google_pubsub_topic" "alerts" { name = "alerts" }
resource "google_pubsub_topic" "alert_deliveries" { name = "alert-deliveries" }

# Webhook URL lives only in Secret Manager. The value is added out of band:
#   gcloud secrets versions add discord-webhook --data-file=-
resource "google_secret_manager_secret" "discord_webhook" {
  secret_id = "discord-webhook"
  replication {
    auto {}
  }
}

resource "google_service_account" "notifier" { account_id = "cw-notifier" }

resource "google_cloud_run_v2_service" "notifier" {
  name                = "notifier"
  location            = var.region
  deletion_protection = false
  ingress             = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = google_service_account.notifier.email
    scaling {
      min_instance_count = 0
      max_instance_count = 2
    }
    vpc_access {
      network_interfaces {
        network    = "default"
        subnetwork = "default"
      }
      egress = "PRIVATE_RANGES_ONLY"
    }
    containers {
      image   = var.image
      command = ["uvicorn", "notifier.app:app", "--host", "0.0.0.0", "--port", "8080"]
      resources {
        limits = { cpu = "1", memory = "512Mi" }
      }
      env {
        name  = "REDIS_HOST"
        value = google_redis_instance.state.host
      }
      env {
        name  = "DELIVERIES_TOPIC"
        value = google_pubsub_topic.alert_deliveries.id
      }
      env {
        name  = "NOTIFY_DISCORD"
        value = var.notify_discord ? "true" : "false"
      }
      env {
        name = "DISCORD_WEBHOOK"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.discord_webhook.secret_id
            version = "latest"
          }
        }
      }
    }
  }
  depends_on = [google_secret_manager_secret_iam_member.notifier_reads_webhook]
}

variable "notify_discord" {
  type        = bool
  default     = true
  description = "false during bulk replays: alerts are still recorded, not posted (Discord rate limits)"
}

resource "google_pubsub_subscription" "notifier" {
  name                 = "alerts-notifier"
  topic                = google_pubsub_topic.alerts.id
  ack_deadline_seconds = 30
  push_config {
    push_endpoint = google_cloud_run_v2_service.notifier.uri
    oidc_token { service_account_email = google_service_account.pusher.email }
  }
  retry_policy { # Discord 429s: back off up to a minute
    minimum_backoff = "2s"
    maximum_backoff = "60s"
  }
}

resource "google_bigquery_table" "alerts" {
  dataset_id          = google_bigquery_dataset.cw.dataset_id
  table_id            = "alerts"
  deletion_protection = false
  schema = jsonencode([
    { name = "alert_id", type = "STRING", mode = "REQUIRED" },
    { name = "game_id", type = "STRING", mode = "REQUIRED" },
    { name = "rule", type = "STRING", mode = "NULLABLE" },
    { name = "text", type = "STRING", mode = "NULLABLE" },
    { name = "event_id", type = "STRING", mode = "NULLABLE" },
    { name = "home_wp", type = "FLOAT64", mode = "NULLABLE" },
    { name = "published_at", type = "TIMESTAMP", mode = "NULLABLE" },
    { name = "alerted_at", type = "TIMESTAMP", mode = "NULLABLE" },
  ])
}

resource "google_bigquery_table" "alert_deliveries" {
  dataset_id          = google_bigquery_dataset.cw.dataset_id
  table_id            = "alert_deliveries"
  deletion_protection = false
  schema = jsonencode([
    { name = "alert_id", type = "STRING", mode = "REQUIRED" },
    { name = "game_id", type = "STRING", mode = "REQUIRED" },
    { name = "rule", type = "STRING", mode = "NULLABLE" },
    { name = "published_at", type = "TIMESTAMP", mode = "NULLABLE" },
    { name = "alerted_at", type = "TIMESTAMP", mode = "NULLABLE" },
    { name = "delivered_at", type = "TIMESTAMP", mode = "NULLABLE" },
    { name = "discord_status", type = "INT64", mode = "NULLABLE" },
    { name = "sent_to_discord", type = "BOOL", mode = "NULLABLE" },
  ])
}

resource "google_pubsub_subscription" "alerts_bq" {
  name  = "alerts-bq"
  topic = google_pubsub_topic.alerts.id
  bigquery_config {
    table               = "${var.project}.${google_bigquery_dataset.cw.dataset_id}.${google_bigquery_table.alerts.table_id}"
    use_table_schema    = true
    drop_unknown_fields = true
  }
  depends_on = [google_bigquery_dataset_iam_member.pubsub_bq]
}

resource "google_pubsub_subscription" "alert_deliveries_bq" {
  name  = "alert-deliveries-bq"
  topic = google_pubsub_topic.alert_deliveries.id
  bigquery_config {
    table               = "${var.project}.${google_bigquery_dataset.cw.dataset_id}.${google_bigquery_table.alert_deliveries.table_id}"
    use_table_schema    = true
    drop_unknown_fields = true
  }
  depends_on = [google_bigquery_dataset_iam_member.pubsub_bq]
}

# ---- IAM
resource "google_pubsub_topic_iam_member" "processor_alerts" {
  topic  = google_pubsub_topic.alerts.id
  role   = "roles/pubsub.publisher"
  member = "serviceAccount:${google_service_account.processor.email}"
}
resource "google_pubsub_topic_iam_member" "notifier_deliveries" {
  topic  = google_pubsub_topic.alert_deliveries.id
  role   = "roles/pubsub.publisher"
  member = "serviceAccount:${google_service_account.notifier.email}"
}
resource "google_secret_manager_secret_iam_member" "notifier_reads_webhook" {
  secret_id = google_secret_manager_secret.discord_webhook.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.notifier.email}"
}
resource "google_cloud_run_v2_service_iam_member" "pusher_invokes_notifier" {
  name     = google_cloud_run_v2_service.notifier.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.pusher.email}"
}
