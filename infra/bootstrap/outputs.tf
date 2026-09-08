output "image_repository" {
  value = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.app.repository_id}/leavenowbot"
}

output "runtime_service_account" {
  value = google_service_account.runtime.email
}

output "task_service_account" {
  value = google_service_account.tasks.email
}
