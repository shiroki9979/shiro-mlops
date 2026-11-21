#!/usr/bin/env bash
# Check infra/terraform offline: the CloudFront Function tests, then for both Terraform layers
# (the main configuration and infra/terraform/bootstrap) formatting, configuration validation
# against the providers only, and `terraform test` plans against a mocked AWS provider. Shared
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
  cd "$layer_dir"

  echo "==> Initialising ${layer_dir#"${REPO_ROOT}/"} without a backend"
  # -backend=false: validation needs only the providers, not the S3 state backend or AWS
  # credentials.
  terraform init -backend=false -input=false

  echo "==> Validating ${layer_dir#"${REPO_ROOT}/"}"
  terraform validate

  echo "==> Running Terraform tests in ${layer_dir#"${REPO_ROOT}/"}"
  # tests/*.tftest.hcl plan against mock_provider "aws", so no AWS credentials are read.
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
