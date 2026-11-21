# Plans the bootstrap layer against a mocked AWS provider: no AWS credentials or state
# backend. override_during = plan gives the mocked computed attributes (ARNs) known values at
# plan time, so the policies can be decoded and compared.
mock_provider "aws" {
  override_during = plan

  mock_data "aws_caller_identity" {
    defaults = {
      account_id = "111122223333"
    }
  }

  mock_resource "aws_s3_bucket" {
    defaults = {
      arn = "arn:aws:s3:::shiro-mlops-tfstate-111122223333"
    }
  }

  mock_resource "aws_iam_openid_connect_provider" {
    defaults = {
      arn = "arn:aws:iam::111122223333:oidc-provider/token.actions.githubusercontent.com"
    }
  }
}

# Both roles are aws_iam_role, so each gets its own ARN; the apply policy denies them by ARN.
override_resource {
  target          = aws_iam_role.terraform_plan
  override_during = plan
  values = {
    arn = "arn:aws:iam::111122223333:role/shiro-mlops-terraform-plan"
  }
}

override_resource {
  target          = aws_iam_role.terraform_apply
  override_during = plan
  values = {
    arn = "arn:aws:iam::111122223333:role/shiro-mlops-terraform-apply"
  }
}

run "plan_role_trusts_only_pull_requests" {
  command = plan

  assert {
    condition = jsondecode(aws_iam_role.terraform_plan.assume_role_policy).Statement == [
      {
        Effect = "Allow"
        Principal = {
          Federated = "arn:aws:iam::111122223333:oidc-provider/token.actions.githubusercontent.com"
        }
        Action = "sts:AssumeRoleWithWebIdentity"
        Condition = {
          StringEquals = {
            "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
            "token.actions.githubusercontent.com:sub" = "repo:shiroki9979/shiro-mlops:pull_request"
          }
        }
      },
    ]
    error_message = "The plan role must trust only aud sts.amazonaws.com and pull_request tokens of shiroki9979/shiro-mlops, with no wildcard sub."
  }
}

run "apply_role_trusts_only_main_branch_pushes" {
  command = plan

  assert {
    condition = jsondecode(aws_iam_role.terraform_apply.assume_role_policy).Statement == [
      {
        Effect = "Allow"
        Principal = {
          Federated = "arn:aws:iam::111122223333:oidc-provider/token.actions.githubusercontent.com"
        }
        Action = "sts:AssumeRoleWithWebIdentity"
        Condition = {
          StringEquals = {
            "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
            "token.actions.githubusercontent.com:sub" = "repo:shiroki9979/shiro-mlops:ref:refs/heads/main"
          }
        }
      },
    ]
    error_message = "The apply role must trust only aud sts.amazonaws.com and the main branch ref of shiroki9979/shiro-mlops, with no wildcard sub."
  }
}

run "apply_role_iam_is_limited_to_project_names" {
  command = plan

  assert {
    condition     = aws_iam_role_policy.terraform_apply.role == aws_iam_role.terraform_apply.name
    error_message = "The apply policy must be attached to the apply role."
  }

  assert {
    condition = [
      for s in jsondecode(aws_iam_role_policy.terraform_apply.policy).Statement : s
      if s.Sid == "ManageProjectIam"
      ] == [
      {
        Sid    = "ManageProjectIam"
        Effect = "Allow"
        Action = "iam:*"
        Resource = [
          "arn:aws:iam::111122223333:role/shiro-mlops-*",
          "arn:aws:iam::111122223333:policy/shiro-mlops-*",
          "arn:aws:iam::111122223333:user/shiro-mlops-*",
        ]
      },
    ]
    error_message = "The apply role may manage only roles, policies and users named shiro-mlops-*."
  }

  assert {
    condition = alltrue([
      for s in jsondecode(aws_iam_role_policy.terraform_apply.policy).Statement :
      s.Effect != "Allow" || s.Sid == "ManageProjectIam" || alltrue([
        for a in flatten([try(s.Action, [])]) :
        !startswith(a, "iam:") || contains(["iam:GetOpenIDConnectProvider", "iam:ListOpenIDConnectProviderTags", "iam:ListOpenIDConnectProviders"], a)
      ])
    ])
    error_message = "Outside shiro-mlops-* names the apply role may only look up the OIDC provider."
  }

  assert {
    condition = alltrue([
      for s in jsondecode(aws_iam_role_policy.terraform_apply.policy).Statement :
      s.Effect != "Allow" || !can(s.NotAction)
    ])
    error_message = "No Allow statement may use NotAction, which would grant every other service."
  }
}

run "apply_role_denies_changes_to_the_bootstrap_layer" {
  command = plan

  assert {
    condition = [
      for s in jsondecode(aws_iam_role_policy.terraform_apply.policy).Statement : s
      if s.Effect == "Deny"
      ] == [
      {
        Sid       = "DenyStateBucketChanges"
        Effect    = "Deny"
        NotAction = "s3:ListBucket"
        Resource  = "arn:aws:s3:::shiro-mlops-tfstate-111122223333"
      },
      {
        Sid       = "DenyOidcProviderChanges"
        Effect    = "Deny"
        NotAction = ["iam:GetOpenIDConnectProvider", "iam:ListOpenIDConnectProviderTags"]
        Resource  = "arn:aws:iam::111122223333:oidc-provider/token.actions.githubusercontent.com"
      },
      {
        Sid    = "DenyBootstrapRoles"
        Effect = "Deny"
        Action = "iam:*"
        Resource = [
          "arn:aws:iam::111122223333:role/shiro-mlops-terraform-plan",
          "arn:aws:iam::111122223333:role/shiro-mlops-terraform-apply",
        ]
      },
    ]
    error_message = "The apply role must be explicitly denied changing or deleting the state bucket, the OIDC provider, and the plan and apply roles."
  }
}

run "apply_role_reaches_only_the_main_configuration_state" {
  command = plan

  assert {
    condition = [
      for s in jsondecode(aws_iam_role_policy.terraform_apply.policy).Statement : s
      if contains(["ManageS3", "ListStateBucket", "ReadWriteForecastViewState"], s.Sid)
      ] == [
      {
        Sid    = "ManageS3"
        Effect = "Allow"
        Action = "s3:*"
        NotResource = [
          "arn:aws:s3:::shiro-mlops-tfstate-111122223333",
          "arn:aws:s3:::shiro-mlops-tfstate-111122223333/*",
        ]
      },
      {
        Sid      = "ListStateBucket"
        Effect   = "Allow"
        Action   = "s3:ListBucket"
        Resource = "arn:aws:s3:::shiro-mlops-tfstate-111122223333"
      },
      {
        Sid    = "ReadWriteForecastViewState"
        Effect = "Allow"
        Action = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
        Resource = [
          "arn:aws:s3:::shiro-mlops-tfstate-111122223333/forecast-view/terraform.tfstate",
          "arn:aws:s3:::shiro-mlops-tfstate-111122223333/forecast-view/terraform.tfstate.tflock",
        ]
      },
    ]
    error_message = "In the state bucket the apply role may only list it and read, write and delete the main configuration's state and lockfile; S3 elsewhere stays manageable."
  }
}

run "plan_role_has_no_write_actions" {
  command = plan

  assert {
    condition = (
      aws_iam_role_policy_attachment.terraform_plan_read_only.role == aws_iam_role.terraform_plan.name
      && aws_iam_role_policy_attachment.terraform_plan_read_only.policy_arn == "arn:aws:iam::aws:policy/ReadOnlyAccess"
    )
    error_message = "The plan role must carry the AWS managed ReadOnlyAccess policy."
  }

  assert {
    condition = (
      aws_iam_role_policy.terraform_plan_state.role == aws_iam_role.terraform_plan.name
      && jsondecode(aws_iam_role_policy.terraform_plan_state.policy).Statement == [
        {
          Sid      = "ListStateBucket"
          Effect   = "Allow"
          Action   = "s3:ListBucket"
          Resource = "arn:aws:s3:::shiro-mlops-tfstate-111122223333"
        },
        {
          Sid      = "ReadForecastViewState"
          Effect   = "Allow"
          Action   = "s3:GetObject"
          Resource = "arn:aws:s3:::shiro-mlops-tfstate-111122223333/forecast-view/terraform.tfstate"
        },
      ]
    )
    error_message = "Beyond ReadOnlyAccess, the plan role may only list the state bucket and read the main configuration's state: no write, and no lockfile access."
  }
}

run "state_bucket_is_versioned_encrypted_and_private" {
  command = plan

  assert {
    condition     = aws_s3_bucket.state.bucket == "shiro-mlops-tfstate-111122223333"
    error_message = "The state bucket name must carry the account ID so it is globally unique."
  }

  assert {
    condition     = one(aws_s3_bucket_versioning.state.versioning_configuration).status == "Enabled"
    error_message = "The state bucket must have versioning enabled."
  }

  assert {
    condition     = one(one(aws_s3_bucket_server_side_encryption_configuration.state.rule).apply_server_side_encryption_by_default).sse_algorithm == "AES256"
    error_message = "The state bucket must encrypt objects by default."
  }

  assert {
    condition = (
      aws_s3_bucket_public_access_block.state.block_public_acls
      && aws_s3_bucket_public_access_block.state.block_public_policy
      && aws_s3_bucket_public_access_block.state.ignore_public_acls
      && aws_s3_bucket_public_access_block.state.restrict_public_buckets
    )
    error_message = "The state bucket must block all four kinds of public access."
  }
}
