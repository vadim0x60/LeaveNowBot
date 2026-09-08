provider "google" {
  project = var.project_id
  region  = var.region
}

resource "google_cloud_run_v2_service" "app" {
  name                = "leavenowbot"
  location            = var.region
  deletion_protection = false
  ingress             = "INGRESS_TRAFFIC_ALL"

  template {
    service_account                  = "leavenowbot-runtime@${var.project_id}.iam.gserviceaccount.com"
    timeout                          = "60s"
    max_instance_request_concurrency = 1

    scaling {
      min_instance_count = 0
      max_instance_count = 1
    }

    containers {
      image = var.image

      ports {
        container_port = 8080
      }

      resources {
        cpu_idle          = true
        startup_cpu_boost = true
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }

      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }
      env {
        name  = "ALLOWED_USER_IDS"
        value = var.allowed_user_ids
      }
      env {
        name  = "BOT_TIMEZONE"
        value = var.timezone
      }
      env {
        name  = "TASK_LOCATION"
        value = var.region
      }
      env {
        name  = "TASK_QUEUE"
        value = "leavenowbot-checks"
      }
      env {
        name  = "TASK_SERVICE_ACCOUNT"
        value = "leavenowbot-tasks@${var.project_id}.iam.gserviceaccount.com"
      }
      env {
        name = "TELEGRAM_BOT_TOKEN"
        value_source {
          secret_key_ref {
            secret  = "leavenowbot-telegram-token"
            version = "latest"
          }
        }
      }
      env {
        name = "GOOGLE_MAPS_API_KEY"
        value_source {
          secret_key_ref {
            secret  = "leavenowbot-maps-api-key"
            version = "latest"
          }
        }
      }
      env {
        name = "TELEGRAM_WEBHOOK_SECRET"
        value_source {
          secret_key_ref {
            secret  = "leavenowbot-webhook-secret"
            version = "latest"
          }
        }
      }
    }
  }
}

resource "google_cloud_run_v2_service_iam_member" "telegram" {
  name     = google_cloud_run_v2_service.app.name
  location = google_cloud_run_v2_service.app.location
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_cloud_run_v2_service_iam_member" "tasks" {
  name     = google_cloud_run_v2_service.app.name
  location = google_cloud_run_v2_service.app.location
  role     = "roles/run.invoker"
  member   = "serviceAccount:leavenowbot-tasks@${var.project_id}.iam.gserviceaccount.com"
}
