#!/usr/bin/env bash
# Check infra/terraform offline: the CloudFront Function tests, then for both Terraform layers
# (the main configuration and infra/terraform/bootstrap) formatting, a committed provider lock
# file, configuration validation against the providers only, and `terraform test` plans against
# a mocked AWS provider. Shared
# by CI and `make infra-check`; needs node and terraform on PATH, but no state backend or AWS
# credentials.
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
readonly TERRAFORM_LAYERS=("$TERRAFORM_DIR" "${TERRAFORM_DIR}/bootstrap")

check_layer() {
  local layer_dir="$1"
  local layer="${layer_dir#"${REPO_ROOT}/"}"
  cd "$layer_dir"

  echo "==> Checking ${layer}/.terraform.lock.hcl is committed"
  # A lock file `terraform init` wrote locally passes -lockfile=readonly below, yet CI and the
  # deploy job would not see it.
  if ! git -C "$REPO_ROOT" ls-files --error-unmatch "${layer}/.terraform.lock.hcl" >/dev/null 2>&1; then
    echo "${layer}/.terraform.lock.hcl is not tracked; commit it (see docs/reference/terraform-state-and-deployment.md)" >&2
    return 1
  fi

  echo "==> Initialising ${layer} without a backend"
  # -backend=false: validation needs only the providers, not the S3 state backend or AWS
  # credentials. -lockfile=readonly: fails when the lock file is missing a provider or no longer
  # satisfies the version constraints, instead of rewriting it.
  terraform init -backend=false -input=false -lockfile=readonly

  echo "==> Validating ${layer}"
  terraform validate

  echo "==> Running Terraform tests in ${layer}"
  # infra/terraform/tests/ and infra/terraform/bootstrap/tests/ plan against
  # mock_provider "aws", so no AWS credentials are read.
  terraform test
}

main() {
  cd "$TERRAFORM_DIR"

  echo "==> Testing CloudFront Functions"
  # Runs the CloudFront Function source that Terraform reads with file(); no dependencies needed.
  node --test "functions/*.test.mjs"

  echo "==> Checking Terraform formatting in both layers"
  terraform fmt -check -recursive

  local layer_dir
  for layer_dir in "${TERRAFORM_LAYERS[@]}"; do
    check_layer "$layer_dir"
  done

  echo "Infra check passed"
}

main
