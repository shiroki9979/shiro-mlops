output "state_bucket_name" {
  value       = aws_s3_bucket.state.id
  description = "S3 bucket holding both layers' state; the bucket value of infra/terraform/state.s3.tfbackend"
}

output "terraform_plan_role_arn" {
  value       = aws_iam_role.terraform_plan.arn
  description = "IAM Role ARN that pull request workflows assume to plan the main configuration; read-only"
}

output "terraform_apply_role_arn" {
  value       = aws_iam_role.terraform_apply.arn
  description = "IAM Role ARN that workflows on main assume to apply the main configuration"
}
