output "image_repository" {
  value = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.app.repository_id}/leavenowbot"
}

output "runtime_service_account" {
  value = google_service_account.runtime.email
}

output "task_service_account" {
  value = google_service_account.tasks.email
}

output "workload_identity_provider" {
  description = "Set this as the WIF_PROVIDER GitHub Actions repository variable."
  value       = google_iam_workload_identity_pool_provider.github.name
}

output "deployer_service_account" {
  description = "Set this as the WIF_SERVICE_ACCOUNT GitHub Actions repository variable."
  value       = google_service_account.deployer.email
}
