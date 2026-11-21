#!/usr/bin/env bash
# Check infra/terraform offline: the CloudFront Function tests, Terraform formatting, and
# configuration validation against the providers only. Shared by CI and `make infra-check`;
# needs node and terraform on PATH, but no state backend or AWS credentials.
#
# Usage: scripts/infra_check.sh
set -euo pipefail

if (($# != 0)); then
  echo "Usage: $0" >&2
  exit 2
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly REPO_ROOT
readonly TERRAFORM_DIR="${REPO_ROOT}/infra/terraform"

main() {
  cd "$TERRAFORM_DIR"

  echo "==> Testing CloudFront Functions"
  # Runs the CloudFront Function source that Terraform reads with file(); no dependencies needed.
  node --test "functions/*.test.mjs"

  echo "==> Checking Terraform formatting"
  terraform fmt -check -recursive

  echo "==> Initialising Terraform without a backend"
  # -backend=false: validation needs only the providers, not the state backend or AWS credentials.
  terraform init -backend=false -input=false

  echo "==> Validating Terraform configuration"
  terraform validate

  echo "Infra check passed"
}

main
