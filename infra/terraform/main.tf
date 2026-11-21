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

locals {
  # Bucket prefixes (ADR-0015 §2.2); the CI and on-prem policies scope to these.
  site_prefix      = "site/"
  published_prefix = "published/"

  # Cost guardrail (ADR-0015 §2.6). The forecasted-spend alert level doubles as
  # the budget limit, so the two cannot drift apart.
  budget_forecasted_alert_usd = 10
  budget_actual_alert_usd     = 5
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

    # Empty filter: the rule applies to the whole bucket. The provider requires
    # a filter or prefix on every rule.
    filter {}

    noncurrent_version_expiration {
      noncurrent_days = 30
    }

    # Remove delete markers left by `sync --delete` once their old versions expire.
    expiration {
      expired_object_delete_marker = true
    }

    # The publisher key cannot s3:AbortMultipartUpload, so parts left by a failed
    # large upload would otherwise accrue storage cost indefinitely.
    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }

  # AWS requires versioning to be enabled before noncurrent-version rules apply.
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
          # Accept only tokens minted for AWS STS, not ones issued to another audience.
          StringEquals = {
            "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
          }
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
            "s3:prefix" = [local.site_prefix, "${local.site_prefix}*"]
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
        Resource = "${aws_s3_bucket.forecast_view.arn}/${local.site_prefix}*"
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

resource "aws_iam_policy" "onprem_publisher_put" {
  name        = "shiro-mlops-onprem-publisher-put"
  description = "On-prem export uploads the public JSON to published/ only"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "PutPublishedPrefix"
        Effect   = "Allow"
        Action   = "s3:PutObject"
        Resource = "${aws_s3_bucket.forecast_view.arn}/${local.published_prefix}*"
      }
    ]
  })
}

resource "aws_iam_user_policy_attachment" "onprem_publisher_put" {
  user       = aws_iam_user.onprem_publisher.name
  policy_arn = aws_iam_policy.onprem_publisher_put.arn
}

# 4. Cost guardrail: email when monthly actual or forecasted spend reaches the
#    levels in locals (ADR-0015 §2.6). AWS Budgets only offers GREATER_THAN,
#    EQUAL_TO and LESS_THAN; GREATER_THAN is the closest to "reaches" (達).
resource "aws_budgets_budget" "monthly_cost" {
  name         = "shiro-mlops-monthly-cost"
  budget_type  = "COST"
  limit_amount = tostring(local.budget_forecasted_alert_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = local.budget_actual_alert_usd
    threshold_type             = "ABSOLUTE_VALUE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.budget_alert_email]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = local.budget_forecasted_alert_usd
    threshold_type             = "ABSOLUTE_VALUE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.budget_alert_email]
  }
}

# 5. CloudFront serves the Forecast View from the bucket through OAC
#    (forecast-view-hosting.md §2, §3). One distribution, two origins on the same
#    bucket: site (origin path /site) and published (no origin path).
locals {
  site_origin_id      = "site"
  published_origin_id = "published"
  # The bucket is read-only to viewers; only these methods are allowed and cached.
  read_only_methods = ["GET", "HEAD"]
}

resource "aws_cloudfront_origin_access_control" "forecast_view" {
  name                              = "shiro-mlops-forecast-view"
  description                       = "CloudFront reads the Forecast View bucket with signed requests"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

# SPA fallback without a custom error response, which would turn a missing
# /published/ file into 200 and HTML. Tested offline by functions/spa-rewrite.test.mjs.
resource "aws_cloudfront_function" "spa_rewrite" {
  name    = "shiro-mlops-spa-rewrite"
  comment = "Rewrite extensionless paths to /index.html"
  runtime = "cloudfront-js-2.0"
  publish = true
  code    = file("${path.module}/functions/spa-rewrite.js")
}

# Edge TTLs per behavior; no cache key includes headers, cookies or query strings.
# A 0/0/0 policy disables caching and CloudFront then rejects the gzip and Brotli
# flags, leaving the behavior without edge compression. max_ttl = 1 keeps both
# flags; the uploads set no Cache-Control, so the edge still applies default_ttl = 0.
resource "aws_cloudfront_cache_policy" "index" {
  name        = "shiro-mlops-forecast-view-index"
  comment     = "Default behavior: index.html is not cached at the edge"
  min_ttl     = 0
  default_ttl = 0
  max_ttl     = 1

  parameters_in_cache_key_and_forwarded_to_origin {
    enable_accept_encoding_gzip   = true
    enable_accept_encoding_brotli = true

    cookies_config {
      cookie_behavior = "none"
    }
    headers_config {
      header_behavior = "none"
    }
    query_strings_config {
      query_string_behavior = "none"
    }
  }
}

resource "aws_cloudfront_cache_policy" "assets" {
  name        = "shiro-mlops-forecast-view-assets"
  comment     = "/assets/*: hashed file names, cached for one year"
  min_ttl     = 31536000
  default_ttl = 31536000
  max_ttl     = 31536000

  parameters_in_cache_key_and_forwarded_to_origin {
    enable_accept_encoding_gzip   = true
    enable_accept_encoding_brotli = true

    cookies_config {
      cookie_behavior = "none"
    }
    headers_config {
      header_behavior = "none"
    }
    query_strings_config {
      query_string_behavior = "none"
    }
  }
}

resource "aws_cloudfront_cache_policy" "published" {
  name        = "shiro-mlops-forecast-view-published"
  comment     = "/published/*: exported JSON, cached for 60 seconds"
  min_ttl     = 60
  default_ttl = 60
  max_ttl     = 60

  parameters_in_cache_key_and_forwarded_to_origin {
    enable_accept_encoding_gzip   = true
    enable_accept_encoding_brotli = true

    cookies_config {
      cookie_behavior = "none"
    }
    headers_config {
      header_behavior = "none"
    }
    query_strings_config {
      query_string_behavior = "none"
    }
  }
}

# Browser Cache-Control per behavior (forecast-view-hosting.md §2) plus the same
# security headers as the managed SecurityHeadersPolicy (§3). A behavior takes one
# response headers policy, so the managed policy is copied into each one rather
# than attached. The uploads set no Cache-Control metadata; override = true keeps
# these values even if an object gains some. Edge TTLs stay with the cache policies.
locals {
  browser_cache_control = {
    index     = "no-cache"
    assets    = "public, max-age=31536000, immutable"
    published = "public, max-age=60"
  }
}

resource "aws_cloudfront_response_headers_policy" "forecast_view" {
  for_each = local.browser_cache_control

  name    = "shiro-mlops-forecast-view-${each.key}"
  comment = "Cache-Control: ${each.value}; managed SecurityHeadersPolicy headers"

  custom_headers_config {
    items {
      header   = "Cache-Control"
      value    = each.value
      override = true
    }
  }

  # Field by field the managed SecurityHeadersPolicy
  # (67f7725c-6f97-4210-82d7-5512b31e9d03): only X-Content-Type-Options overrides
  # the origin; no CSP.
  security_headers_config {
    content_type_options {
      override = true
    }
    frame_options {
      frame_option = "SAMEORIGIN"
      override     = false
    }
    referrer_policy {
      referrer_policy = "strict-origin-when-cross-origin"
      override        = false
    }
    strict_transport_security {
      access_control_max_age_sec = 31536000
      include_subdomains         = false
      preload                    = false
      override                   = false
    }
    xss_protection {
      protection = true
      mode_block = true
      override   = false
    }
  }
}

# No default_root_object (spa-rewrite maps / to /index.html), and no custom error
# response, WAF, geo restriction or standard logging (forecast-view-hosting.md §3).
resource "aws_cloudfront_distribution" "forecast_view" {
  enabled      = true
  comment      = "shiro-mlops Forecast View"
  price_class  = "PriceClass_200"
  http_version = "http2and3"

  origin {
    origin_id                = local.site_origin_id
    domain_name              = aws_s3_bucket.forecast_view.bucket_regional_domain_name
    origin_path              = "/${trimsuffix(local.site_prefix, "/")}"
    origin_access_control_id = aws_cloudfront_origin_access_control.forecast_view.id
  }

  origin {
    origin_id                = local.published_origin_id
    domain_name              = aws_s3_bucket.forecast_view.bucket_regional_domain_name
    origin_access_control_id = aws_cloudfront_origin_access_control.forecast_view.id
  }

  default_cache_behavior {
    target_origin_id           = local.site_origin_id
    viewer_protocol_policy     = "redirect-to-https"
    allowed_methods            = local.read_only_methods
    cached_methods             = local.read_only_methods
    compress                   = true
    cache_policy_id            = aws_cloudfront_cache_policy.index.id
    response_headers_policy_id = aws_cloudfront_response_headers_policy.forecast_view["index"].id

    function_association {
      event_type   = "viewer-request"
      function_arn = aws_cloudfront_function.spa_rewrite.arn
    }
  }

  ordered_cache_behavior {
    path_pattern               = "/assets/*"
    target_origin_id           = local.site_origin_id
    viewer_protocol_policy     = "redirect-to-https"
    allowed_methods            = local.read_only_methods
    cached_methods             = local.read_only_methods
    compress                   = true
    cache_policy_id            = aws_cloudfront_cache_policy.assets.id
    response_headers_policy_id = aws_cloudfront_response_headers_policy.forecast_view["assets"].id
  }

  ordered_cache_behavior {
    path_pattern               = "/${local.published_prefix}*"
    target_origin_id           = local.published_origin_id
    viewer_protocol_policy     = "redirect-to-https"
    allowed_methods            = local.read_only_methods
    cached_methods             = local.read_only_methods
    compress                   = true
    cache_policy_id            = aws_cloudfront_cache_policy.published.id
    response_headers_policy_id = aws_cloudfront_response_headers_policy.forecast_view["published"].id
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }
}

# Only this distribution may read, and only site/* and published/*. Without
# s3:ListBucket a missing object returns 403, not 404. A fixed service principal
# and a fixed AWS:SourceArn keep the policy non-public, so the public access
# block stays fully on.
resource "aws_s3_bucket_policy" "forecast_view" {
  bucket = aws_s3_bucket.forecast_view.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "CloudFrontReadSiteAndPublished"
        Effect = "Allow"
        Principal = {
          Service = "cloudfront.amazonaws.com"
        }
        Action = "s3:GetObject"
        Resource = [
          "${aws_s3_bucket.forecast_view.arn}/${local.site_prefix}*",
          "${aws_s3_bucket.forecast_view.arn}/${local.published_prefix}*"
        ]
        Condition = {
          StringEquals = {
            "AWS:SourceArn" = aws_cloudfront_distribution.forecast_view.arn
          }
        }
      }
    ]
  })

  # S3 rejects concurrent changes to one bucket's configuration, so the public
  # access block is applied first.
  depends_on = [aws_s3_bucket_public_access_block.forecast_view]
}
