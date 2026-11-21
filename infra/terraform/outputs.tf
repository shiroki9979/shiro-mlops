output "s3_bucket_name" {
  value       = aws_s3_bucket.forecast_view.id
  description = "The S3 bucket holding the Forecast View release artefacts (site/ and published/)"
}

output "site_deploy_role_arn" {
  value       = aws_iam_role.site_deploy.arn
  description = "IAM Role ARN that GitHub Actions on main assumes to upload the Forecast View; may write site/ only"
}

output "aws_region" {
  value       = var.aws_region
  description = "AWS region holding the resources; the on-prem publisher's AWS_DEFAULT_REGION must equal it"
}

output "onprem_publisher_user_name" {
  value       = aws_iam_user.onprem_publisher.name
  description = "IAM user for the on-prem export; may PutObject to published/ only. Its access key is managed outside Terraform"
}

output "forecast_view_url" {
  value       = "https://${aws_cloudfront_distribution.forecast_view.domain_name}"
  description = "Full https:// URL of the Forecast View on the default *.cloudfront.net domain"
}

output "cloudfront_distribution_id" {
  value       = aws_cloudfront_distribution.forecast_view.id
  description = "ID of the CloudFront distribution serving the Forecast View"
}
