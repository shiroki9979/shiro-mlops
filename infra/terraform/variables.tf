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
  default     = "shiro-mlops-artifacts-prod"
  description = "Name of the S3 bucket for artifacts"
}

variable "github_repo" {
  type        = string
  default     = "shiro/shiro-mlops"
  description = "GitHub repository name (org/repo) for OIDC trust"
}

variable "aws_account_id" {
  type        = string
  default     = "123456789012"
  description = "AWS Account ID"
}

variable "create_oidc_provider" {
  type        = bool
  default     = true
  description = "Whether to create the GitHub OIDC provider in AWS"
}
