variable "project_id" {
  description = "Existing Google Cloud project ID with billing enabled."
  type        = string
}

variable "region" {
  description = "Region for Firestore, Cloud Tasks, Artifact Registry, and Cloud Run."
  type        = string
  default     = "europe-west2"
}

variable "github_repository" {
  description = "GitHub repository allowed to deploy, in owner/name form."
  type        = string
  default     = "vadim0x60/LeaveNowBot"
}
