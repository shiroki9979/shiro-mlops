terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "shiro-mlops"
      ManagedBy   = "Terraform"
      Environment = var.environment
    }
  }
}

# 1. S3 bucket for the Forecast View release artefacts (ADR-0015 §2.2).
#    site/      : forecast-view build output, written by the CI role.
#    published/ : exported public JSON, written by the on-prem publisher user.
resource "aws_s3_bucket" "forecast_view" {
  bucket        = var.s3_bucket_name
  force_destroy = var.environment == "dev"
}

resource "aws_s3_bucket_versioning" "forecast_view" {
  bucket = aws_s3_bucket.forecast_view.id
  versioning_configuration {
    status = "Enabled"
  }
}

# Old versions stay recoverable for 30 days, then expire (ADR-0015 §2.6).
resource "aws_s3_bucket_lifecycle_configuration" "forecast_view" {
  bucket = aws_s3_bucket.forecast_view.id

  rule {
    id     = "expire-noncurrent-versions"
    status = "Enabled"

    filter {}

    noncurrent_version_expiration {
      noncurrent_days = 30
    }

    # Remove delete markers left by `sync --delete` once their old versions expire.
    expiration {
      expired_object_delete_marker = true
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }

  depends_on = [aws_s3_bucket_versioning.forecast_view]
}

resource "aws_s3_bucket_server_side_encryption_configuration" "forecast_view" {
  bucket = aws_s3_bucket.forecast_view.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "forecast_view" {
  bucket = aws_s3_bucket.forecast_view.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# 2. GitHub Actions OIDC provider and CI role: deploys the frontend to site/ only.
resource "aws_iam_openid_connect_provider" "github" {
  count = var.create_oidc_provider ? 1 : 0
  url   = "https://token.actions.githubusercontent.com"

  client_id_list = [
    "sts.amazonaws.com"
  ]

  thumbprint_list = [
    "6938fd4d98bab03faadb97b34396831e3780aea1",
    "1c58a21a5a0d317b07b4172f3e72166e408d63c5"
  ]
}

resource "aws_iam_role" "github_actions_role" {
  name = "shiro-mlops-github-actions-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Federated = var.create_oidc_provider ? aws_iam_openid_connect_provider.github[0].arn : "arn:aws:iam::${var.aws_account_id}:oidc-provider/token.actions.githubusercontent.com"
        }
        Action = "sts:AssumeRoleWithWebIdentity"
        Condition = {
          StringLike = {
            "token.actions.githubusercontent.com:sub" = "repo:${var.github_repo}:*"
          }
        }
      }
    ]
  })
}

# `aws s3 sync --delete` to site/ needs to list, put and delete under site/ only.
resource "aws_iam_policy" "ci_site_deploy" {
  name        = "shiro-mlops-ci-site-deploy"
  description = "CI deploys the Forecast View build output to site/ only"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ListSitePrefix"
        Effect   = "Allow"
        Action   = "s3:ListBucket"
        Resource = aws_s3_bucket.forecast_view.arn
        Condition = {
          StringLike = {
            "s3:prefix" = ["site/", "site/*"]
          }
        }
      },
      {
        Sid    = "WriteSitePrefix"
        Effect = "Allow"
        Action = [
          "s3:PutObject",
          "s3:DeleteObject"
        ]
        Resource = "${aws_s3_bucket.forecast_view.arn}/site/*"
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "ci_site_deploy" {
  role       = aws_iam_role.github_actions_role.name
  policy_arn = aws_iam_policy.ci_site_deploy.arn
}

# 3. On-prem publisher user: uploads the exported JSON to published/ only
#    (ADR-0015 §2.3). Its access key is created and rotated outside Terraform,
#    so the secret never enters Terraform state.
resource "aws_iam_user" "onprem_publisher" {
  name = "shiro-mlops-onprem-publisher"
}

resource "aws_iam_policy" "onprem_publish" {
  name        = "shiro-mlops-onprem-publish"
  description = "On-prem export uploads the public JSON to published/ only"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "PutPublishedPrefix"
        Effect   = "Allow"
        Action   = "s3:PutObject"
        Resource = "${aws_s3_bucket.forecast_view.arn}/published/*"
      }
    ]
  })
}

resource "aws_iam_user_policy_attachment" "onprem_publish" {
  user       = aws_iam_user.onprem_publisher.name
  policy_arn = aws_iam_policy.onprem_publish.arn
}

# 4. Cost guardrail: email when monthly actual spend reaches 5 USD or
#    forecasted spend reaches 10 USD (ADR-0015 §2.6).
resource "aws_budgets_budget" "monthly_cost" {
  name         = "shiro-mlops-monthly-cost"
  budget_type  = "COST"
  limit_amount = "10"
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 5
    threshold_type             = "ABSOLUTE_VALUE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.budget_alert_email]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 10
    threshold_type             = "ABSOLUTE_VALUE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.budget_alert_email]
  }
}
