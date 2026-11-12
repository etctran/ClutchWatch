resource "google_cloud_run_v2_service" "processor" {
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
    }
  }
}

resource "google_cloud_run_v2_service_iam_member" "pusher_invokes_processor" {
  name     = google_cloud_run_v2_service.processor.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.pusher.email}"
}
