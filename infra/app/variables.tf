variable "project_id" {
  type = string
}

variable "image" {
  description = "Immutable Artifact Registry image reference, preferably with a digest."
  type        = string
}

variable "region" {
  type    = string
  default = "europe-west2"
}

variable "timezone" {
  type    = string
  default = "Europe/London"
}
