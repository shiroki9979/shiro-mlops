variable "github_repo" {
  type = string
  # SYNC(infra/terraform/variables.tf): the plan and apply roles here and the site deploy role
  # there must trust the same repository.
  default     = "shiroki9979/shiro-mlops"
  description = "GitHub repository name (org/repo) whose workflow tokens the plan and apply roles trust"
}
