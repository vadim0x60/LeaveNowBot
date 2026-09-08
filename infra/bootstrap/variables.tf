variable "project_id" {
  description = "Existing Google Cloud project ID with billing enabled."
  type        = string
}

variable "region" {
  description = "Region for Firestore, Cloud Tasks, Artifact Registry, and Cloud Run."
  type        = string
  default     = "europe-west2"
}
