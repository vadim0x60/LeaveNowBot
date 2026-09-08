provider "google" {
  project = var.project_id
  region  = var.region
}

locals {
  services = toset([
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    "cloudtasks.googleapis.com",
    "firestore.googleapis.com",
    "iam.googleapis.com",
    "routes.googleapis.com",
    "run.googleapis.com",
    "secretmanager.googleapis.com",
  ])
}

resource "google_project_service" "services" {
  for_each           = local.services
  service            = each.value
  disable_on_destroy = false
}

resource "google_artifact_registry_repository" "app" {
  location      = var.region
  repository_id = "leavenowbot"
  format        = "DOCKER"
  depends_on    = [google_project_service.services]
}

resource "google_firestore_database" "app" {
  name                        = "(default)"
  location_id                 = var.region
  type                        = "FIRESTORE_NATIVE"
  deletion_policy             = "ABANDON"
  delete_protection_state     = "DELETE_PROTECTION_ENABLED"
  app_engine_integration_mode = "DISABLED"
  depends_on                  = [google_project_service.services]
}

resource "google_cloud_tasks_queue" "checks" {
  name     = "leavenowbot-checks"
  location = var.region

  rate_limits {
    max_concurrent_dispatches = 1
    max_dispatches_per_second = 2
  }

  retry_config {
    max_attempts       = 20
    min_backoff        = "5s"
    max_backoff        = "300s"
    max_doublings      = 5
    max_retry_duration = "3600s"
  }

  depends_on = [google_project_service.services]
}

resource "google_service_account" "runtime" {
  account_id   = "leavenowbot-runtime"
  display_name = "LeaveNowBot Cloud Run runtime"
  depends_on   = [google_project_service.services]
}

resource "google_service_account" "tasks" {
  account_id   = "leavenowbot-tasks"
  display_name = "LeaveNowBot Cloud Tasks caller"
  depends_on   = [google_project_service.services]
}

resource "google_service_account" "build" {
  account_id   = "leavenowbot-build"
  display_name = "LeaveNowBot Cloud Build"
  depends_on   = [google_project_service.services]
}

resource "google_project_iam_member" "runtime_firestore" {
  project = var.project_id
  role    = "roles/datastore.user"
  member  = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_project_iam_member" "runtime_tasks" {
  project = var.project_id
  role    = "roles/cloudtasks.enqueuer"
  member  = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_service_account_iam_member" "runtime_acts_as_tasks" {
  service_account_id = google_service_account.tasks.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_project_iam_member" "build_artifacts" {
  project = var.project_id
  role    = "roles/artifactregistry.writer"
  member  = "serviceAccount:${google_service_account.build.email}"
}

resource "google_project_iam_member" "build_logs" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.build.email}"
}

resource "google_secret_manager_secret" "secrets" {
  for_each  = toset(["telegram-token", "maps-api-key", "webhook-secret"])
  secret_id = "leavenowbot-${each.value}"
  replication {
    auto {}
  }
  depends_on = [google_project_service.services]
}

resource "google_secret_manager_secret_iam_member" "runtime_secrets" {
  for_each  = google_secret_manager_secret.secrets
  secret_id = each.value.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.runtime.email}"
}
