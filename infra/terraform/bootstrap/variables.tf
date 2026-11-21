variable "github_repo" {
  type        = string
  default     = "shiroki9979/shiro-mlops"
  description = "GitHub repository name (org/repo) whose workflow tokens the plan and apply roles trust"
}
