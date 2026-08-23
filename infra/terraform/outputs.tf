output "s3_bucket_name" {
  value       = aws_s3_bucket.artifacts.id
  description = "The S3 bucket for artifacts and Feast registry"
}

output "api_ecr_repository_url" {
  value       = aws_ecr_repository.api.repository_url
  description = "ECR URL for API container image"
}

output "dagster_ecr_repository_url" {
  value       = aws_ecr_repository.dagster.repository_url
  description = "ECR URL for Dagster container image"
}

output "github_actions_role_arn" {
  value       = aws_iam_role.github_actions_role.arn
  description = "IAM Role ARN to assume in GitHub Actions"
}
