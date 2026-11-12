terraform {
  required_version = ">= 1.9"
  required_providers {
    google = { source = "hashicorp/google", version = "~> 6.0" }
  }
}

variable "project" { type = string }
variable "region" {
  type    = string
  default = "us-central1"
}
variable "image" {
  type        = string
  description = "Pipeline image (set by scripts/deploy.sh)"
  default     = "us-docker.pkg.dev/cloudrun/container/hello"
}

provider "google" {
  project = var.project
  region  = var.region
}

data "google_project" "this" {}

locals {
  pubsub_agent = "serviceAccount:service-${data.google_project.this.number}@gcp-sa-pubsub.iam.gserviceaccount.com"
}

resource "google_artifact_registry_repository" "images" {
  repository_id = "clutchwatch"
  format        = "DOCKER"
  location      = var.region
}

# ---- Memorystore: the only resource that bills while idle (see scripts/teardown.sh)
resource "google_redis_instance" "state" {
  name               = "clutchwatch-state"
  tier               = "BASIC"
  memory_size_gb     = 1
  redis_version      = "REDIS_7_2"
  region             = var.region
  authorized_network = "projects/${var.project}/global/networks/default"
}

# ---- Service accounts (least privilege: each gets only the topics it touches)
resource "google_service_account" "processor" { account_id = "cw-processor" }
resource "google_service_account" "pusher" { account_id = "cw-pusher" }       # Pub/Sub push identity
resource "google_service_account" "publisher" { account_id = "cw-publisher" } # replayer + live poller

output "image_repo" {
  value = "${var.region}-docker.pkg.dev/${var.project}/${google_artifact_registry_repository.images.repository_id}"
}
output "redis_host" { value = google_redis_instance.state.host }
output "processor_url" { value = google_cloud_run_v2_service.processor.uri }
