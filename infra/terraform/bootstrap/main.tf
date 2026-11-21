# Bootstrap layer: the state bucket, the GitHub OIDC provider, and the plan and apply roles
# that CI assumes. Only a person with administrator credentials applies it; CI cannot change
# it. See docs/reference/terraform-state-and-deployment.md.
terraform {
  # S3 native locking (use_lockfile) is GA from 1.11.
  required_version = ">= 1.11.0"

  # Partial configuration, as in the main configuration: the bucket name comes from
  # -backend-config. The first apply runs on local state, then -migrate-state moves it here
  # (docs/how-to/deploy-aws-infrastructure.md).
  backend "s3" {
    key          = "bootstrap/terraform.tfstate"
    region       = "ap-northeast-1"
    encrypt      = true
    use_lockfile = true
  }

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  # SYNC(infra/terraform/main.tf): backend blocks cannot read variables, so both layers'
  # backends name this region literally; the state bucket must live where they look.
  region = "ap-northeast-1"

  default_tags {
    tags = {
      Project   = "shiro-mlops"
      ManagedBy = "Terraform"
      Layer     = "bootstrap"
    }
  }
}

data "aws_caller_identity" "current" {}

# Kept apart from the Forecast View bucket so CloudFront cannot read state and the 30-day
# noncurrent-version expiry there never removes the versions that recover a damaged state.
resource "aws_s3_bucket" "state" {
  # Bucket names are global; the account ID keeps this one unique.
  bucket = "shiro-mlops-tfstate-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "state" {
  bucket = aws_s3_bucket.state.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Shared by the plan, apply and site deploy roles; the main configuration reads it through a
# data source.
resource "aws_iam_openid_connect_provider" "github" {
  url = "https://token.actions.githubusercontent.com"

  client_id_list = [
    "sts.amazonaws.com"
  ]

  thumbprint_list = [
    "6938fd4d98bab03faadb97b34396831e3780aea1",
    "1c58a21a5a0d317b07b4172f3e72166e408d63c5"
  ]
}

locals {
  # SYNC(infra/terraform/main.tf): the key in the main configuration's backend block.
  forecast_view_state_key = "forecast-view/terraform.tfstate"

  # Each role trusts exactly one token subject; none accepts repo:<repo>:*.
  github_subjects = {
    terraform_plan  = "repo:${var.github_repo}:pull_request"
    terraform_apply = "repo:${var.github_repo}:ref:refs/heads/main"
  }

  github_trust_policies = {
    for role, subject in local.github_subjects : role => jsonencode({
      Version = "2012-10-17"
      Statement = [
        {
          Effect = "Allow"
          Principal = {
            Federated = aws_iam_openid_connect_provider.github.arn
          }
          Action = "sts:AssumeRoleWithWebIdentity"
          Condition = {
            # Accept only tokens minted for AWS STS, not ones issued to another audience.
            StringEquals = {
              "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
              "token.actions.githubusercontent.com:sub" = subject
            }
          }
        }
      ]
    })
  }
}

# Any pull request can assume the plan role, so it may not write anything. The PR plan runs
# with -lock=false, so it needs no lockfile access either.
resource "aws_iam_role" "terraform_plan" {
  name               = "shiro-mlops-terraform-plan"
  assume_role_policy = local.github_trust_policies.terraform_plan
}

resource "aws_iam_role_policy_attachment" "terraform_plan_read_only" {
  role       = aws_iam_role.terraform_plan.name
  policy_arn = "arn:aws:iam::aws:policy/ReadOnlyAccess"
}

# ReadOnlyAccess already covers these today; stating them keeps the plan working if AWS ever
# narrows the managed policy's S3 reads.
resource "aws_iam_role_policy" "terraform_plan_state" {
  name = "shiro-mlops-terraform-plan-state"
  role = aws_iam_role.terraform_plan.name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ListStateBucket"
        Effect   = "Allow"
        Action   = "s3:ListBucket"
        Resource = aws_s3_bucket.state.arn
      },
      {
        Sid      = "ReadForecastViewState"
        Effect   = "Allow"
        Action   = "s3:GetObject"
        Resource = "${aws_s3_bucket.state.arn}/${local.forecast_view_state_key}"
      }
    ]
  })
}

# Only code merged into main can assume the apply role.
resource "aws_iam_role" "terraform_apply" {
  name               = "shiro-mlops-terraform-apply"
  assume_role_policy = local.github_trust_policies.terraform_apply
}

# Inline rather than a managed policy: a managed policy named shiro-mlops-* would fall under
# ManageProjectIam, letting the role publish a wider version of its own policy. Inline, the
# policy is part of the role, which DenyBootstrapRoles covers.
resource "aws_iam_role_policy" "terraform_apply" {
  name = "shiro-mlops-terraform-apply"
  role = aws_iam_role.terraform_apply.name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # NotResource keeps the state bucket out of the S3 grant, so the bootstrap state and
        # any other object there stay unreachable; the next two statements open only what
        # the S3 backend needs for the main configuration's state.
        Sid    = "ManageS3"
        Effect = "Allow"
        Action = "s3:*"
        NotResource = [
          aws_s3_bucket.state.arn,
          "${aws_s3_bucket.state.arn}/*"
        ]
      },
      {
        Sid      = "ListStateBucket"
        Effect   = "Allow"
        Action   = "s3:ListBucket"
        Resource = aws_s3_bucket.state.arn
      },
      {
        Sid    = "ReadWriteForecastViewState"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject"
        ]
        Resource = [
          "${aws_s3_bucket.state.arn}/${local.forecast_view_state_key}",
          "${aws_s3_bucket.state.arn}/${local.forecast_view_state_key}.tflock"
        ]
      },
      {
        Sid      = "ManageCloudFront"
        Effect   = "Allow"
        Action   = "cloudfront:*"
        Resource = "*"
      },
      {
        Sid      = "ManageBudgets"
        Effect   = "Allow"
        Action   = "budgets:*"
        Resource = "*"
      },
      {
        # The role can still create a shiro-mlops-* role with a broad policy attached: an
        # accepted residual risk, see docs/reference/terraform-state-and-deployment.md.
        Sid    = "ManageProjectIam"
        Effect = "Allow"
        Action = "iam:*"
        Resource = [
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/shiro-mlops-*",
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:policy/shiro-mlops-*",
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:user/shiro-mlops-*"
        ]
      },
      {
        # The main configuration's aws_iam_openid_connect_provider data source finds the
        # provider by URL, which lists the account's providers first, then reads it and its
        # tags.
        Sid    = "LookUpOidcProvider"
        Effect = "Allow"
        Action = [
          "iam:GetOpenIDConnectProvider",
          "iam:ListOpenIDConnectProviderTags",
          "iam:ListOpenIDConnectProviders"
        ]
        Resource = "*"
      },
      {
        # Bucket-level actions only: deleting the bucket or changing its versioning,
        # encryption, public access block or policy. Object access is governed above.
        Sid       = "DenyStateBucketChanges"
        Effect    = "Deny"
        NotAction = "s3:ListBucket"
        Resource  = aws_s3_bucket.state.arn
      },
      {
        Sid    = "DenyOidcProviderChanges"
        Effect = "Deny"
        NotAction = [
          "iam:GetOpenIDConnectProvider",
          "iam:ListOpenIDConnectProviderTags"
        ]
        Resource = aws_iam_openid_connect_provider.github.arn
      },
      {
        # Both names match shiro-mlops-*, so without this ManageProjectIam would let CI widen
        # its own trust or permissions.
        Sid    = "DenyBootstrapRoles"
        Effect = "Deny"
        Action = "iam:*"
        Resource = [
          aws_iam_role.terraform_plan.arn,
          aws_iam_role.terraform_apply.arn
        ]
      }
    ]
  })
}
