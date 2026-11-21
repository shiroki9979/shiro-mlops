variable "aws_region" {
  type        = string
  default     = "ap-northeast-1"
  description = "AWS region for deployments"
}

variable "environment" {
  type        = string
  default     = "dev"
  description = "Deployment environment (dev, staging, prod)"
}

variable "s3_bucket_name" {
  type        = string
  default     = "shiro-mlops-forecast-view"
  description = "Name of the S3 bucket for the Forecast View release artefacts"
}

variable "github_repo" {
  type        = string
  default     = "shiroki9979/shiro-mlops"
  description = "GitHub repository name (org/repo) for OIDC trust"
}

variable "create_oidc_provider" {
  type        = bool
  default     = true
  description = "Whether to create the GitHub OIDC provider in AWS"
}

variable "budget_alert_email" {
  type        = string
  description = "Email address that receives the AWS Budgets cost alerts"
  # Keeps the personal address out of plan output and workflow logs.
  sensitive = true

  validation {
    condition     = can(regex("^[^@[:space:]]+@[^@[:space:]]+\\.[^@[:space:]]+$", var.budget_alert_email))
    error_message = "budget_alert_email must be a valid email address."
  }
}
