# Live poller: on only for game nights (`-var live_poller=true`). One always-on instance with CPU
# always allocated, since it polls in a background thread rather than serving requests.
variable "live_poller" {
  type    = bool
  default = false
}

resource "google_cloud_run_v2_service" "live_poller" {
  count               = var.live_poller ? 1 : 0
  name                = "live-poller"
  location            = var.region
  deletion_protection = false
  ingress             = "INGRESS_TRAFFIC_INTERNAL_ONLY" # health endpoint only; nothing calls it
  lifecycle {
    ignore_changes = [template[0].containers[0].image, client, client_version]
  }
  template {
    service_account = google_service_account.publisher.email
    scaling {
      min_instance_count = 1
      max_instance_count = 1 # one poller: two would double-publish (absorbed by dedup, but wasteful)
    }
    containers {
      image   = var.image
      command = ["python", "-m", "ingest.live_poller"]
      resources {
        cpu_idle = false
        limits   = { cpu = "1", memory = "512Mi" }
      }
      env {
        name  = "TOPIC"
        value = google_pubsub_topic.game_events.id
      }
    }
  }
}
