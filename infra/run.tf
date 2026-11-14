resource "google_cloud_run_v2_service" "processor" {
  lifecycle {
    # CI (scripts/release.sh) owns the running image; infra applies must not roll code back
    ignore_changes = [template[0].containers[0].image, client, client_version]
  }
  name                = "processor"
  location            = var.region
  deletion_protection = false
  ingress             = "INGRESS_TRAFFIC_ALL" # Pub/Sub push; callers still need run.invoker

  template {
    service_account                  = google_service_account.processor.email
    max_instance_request_concurrency = 80
    scaling {
      min_instance_count = 0
      max_instance_count = 10
    }
    vpc_access { # Direct VPC egress to reach Memorystore's private IP
      network_interfaces {
        network    = "default"
        subnetwork = "default"
      }
      egress = "PRIVATE_RANGES_ONLY"
    }
    containers {
      image = var.image
      resources {
        limits = { cpu = "1", memory = "512Mi" }
      }
      env {
        name  = "REDIS_HOST"
        value = google_redis_instance.state.host
      }
      env {
        name  = "STATE_TOPIC"
        value = google_pubsub_topic.state_updates.id
      }
      env {
        name  = "ALERTS_TOPIC"
        value = google_pubsub_topic.alerts.id
      }
      env {
        name  = "FORCE_NACK_RATE"
        value = tostring(var.force_nack_rate)
      }
    }
  }
}

resource "google_cloud_run_v2_service_iam_member" "pusher_invokes_processor" {
  name     = google_cloud_run_v2_service.processor.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.pusher.email}"
}

variable "force_nack_rate" {
  type        = number
  default     = 0
  description = "T5 chaos: fraction of successfully applied events the processor NACKs anyway"
}

# Replayer runs on Google's NTP-synced machines so published_at/processed_at share a clock.
#   gcloud run jobs execute replayer --region us-central1 --args=<replayer flags>
resource "google_cloud_run_v2_job" "replayer" {
  lifecycle {
    ignore_changes = [template[0].template[0].containers[0].image, client, client_version]
  }
  name                = "replayer"
  location            = var.region
  deletion_protection = false
  template {
    task_count = 1
    template {
      service_account = google_service_account.publisher.email
      max_retries     = 0
      timeout         = "3600s"
      containers {
        image   = var.image
        command = ["python", "-m", "ingest.replayer"]
        args = ["--csv", "data/replay/season_2024.parquet", "--topic", google_pubsub_topic.game_events.id,
        "--target-rate", "100", "--limit-games", "1"]
        resources {
          limits = { cpu = "2", memory = "4Gi" }
        }
      }
    }
  }
}
