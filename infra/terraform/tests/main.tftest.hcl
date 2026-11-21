# Plans the main configuration against a mocked AWS provider: no AWS credentials
# or state backend. override_during = plan gives the mocked computed attributes
# (ARNs) known values at plan time, so the policies can be decoded and compared.
mock_provider "aws" {
  override_during = plan

  mock_resource "aws_s3_bucket" {
    defaults = {
      arn = "arn:aws:s3:::shiro-mlops-forecast-view"
    }
  }

  # The bootstrap layer (infra/terraform/bootstrap) owns the provider; this layer only reads it.
  mock_data "aws_iam_openid_connect_provider" {
    defaults = {
      arn = "arn:aws:iam::111122223333:oidc-provider/token.actions.githubusercontent.com"
    }
  }
}

variables {
  budget_alert_email = "ops@example.com"
}

run "site_deploy_role_trusts_only_main_branch_pushes" {
  command = plan

  assert {
    condition     = aws_iam_role.site_deploy.name == "shiro-mlops-site-deploy"
    error_message = "The site deploy role must be named shiro-mlops-site-deploy."
  }

  assert {
    condition     = jsondecode(aws_iam_role.site_deploy.assume_role_policy).Statement[0].Principal.Federated == "arn:aws:iam::111122223333:oidc-provider/token.actions.githubusercontent.com"
    error_message = "The site deploy role must trust the GitHub OIDC provider that the bootstrap layer created, read through a data source."
  }

  assert {
    condition = jsondecode(aws_iam_role.site_deploy.assume_role_policy).Statement[0].Condition == {
      StringEquals = {
        "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
        "token.actions.githubusercontent.com:sub" = "repo:shiroki9979/shiro-mlops:ref:refs/heads/main"
      }
    }
    error_message = "The site deploy role must trust only aud sts.amazonaws.com and the main branch ref of shiroki9979/shiro-mlops, with no wildcard sub."
  }
}

run "site_deploy_role_can_only_list_write_and_delete_under_site" {
  command = plan

  assert {
    condition     = aws_iam_role_policy_attachment.ci_site_deploy.role == aws_iam_role.site_deploy.name
    error_message = "The site deploy policy must be attached to the site deploy role."
  }

  assert {
    condition = jsondecode(aws_iam_policy.ci_site_deploy.policy).Statement == [
      {
        Sid      = "ListSitePrefix"
        Effect   = "Allow"
        Action   = "s3:ListBucket"
        Resource = "arn:aws:s3:::shiro-mlops-forecast-view"
        Condition = {
          StringLike = {
            "s3:prefix" = ["site/", "site/*"]
          }
        }
      },
      {
        Sid      = "WriteSitePrefix"
        Effect   = "Allow"
        Action   = ["s3:PutObject", "s3:DeleteObject"]
        Resource = "arn:aws:s3:::shiro-mlops-forecast-view/site/*"
      },
    ]
    error_message = "The site deploy policy must allow only listing, putting and deleting under site/."
  }
}

run "budget_alert_email_is_sensitive" {
  command = plan

  assert {
    condition     = issensitive(aws_budgets_budget.monthly_cost.notification)
    error_message = "budget_alert_email must be sensitive so the address stays out of plan output and logs."
  }
}
