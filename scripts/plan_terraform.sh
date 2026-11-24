#!/usr/bin/env bash
# Plan the main Terraform configuration (infra/terraform) against the remote state, save the
# plan, export it as JSON and judge it with scripts/check_plan_safety.py. Shared by the CI
# `terraform-plan` and `deploy` jobs and by a person planning locally
# (docs/reference/terraform-state-and-deployment.md). It never applies: the deploy job applies
# the saved plan in a later step, only once this script has exited 0.
#
# The saved plan and its JSON hold sensitive values such as the budget alert email in plain
# text, so CI keeps them on the runner and never uploads them as artifacts.
#
# Usage: scripts/plan_terraform.sh [--lock=false] [--out <plan-file>] [--summary <file>]
#                                  <backend-config>
#   --lock=false     plan without the state lock (the plan role cannot write the lockfile)
#   --out            saved plan path (default infra/terraform/tfplan); JSON goes to <plan-file>.json
#   --summary        append the Markdown summary to this file (default: stdout)
#   backend-config   passed to `terraform init -backend-config=`: `bucket=<state bucket>`, or a
#                    file path relative to infra/terraform such as state.s3.tfbackend
# Exit code: 0 safe, 1 unsafe (deletes, replaces or forgets), 2 bad arguments or plan JSON; a
# failing terraform command exits with its own code.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly REPO_ROOT
readonly TERRAFORM_DIR="${REPO_ROOT}/infra/terraform"

usage() {
  echo "Usage: $0 [--lock=false] [--out <plan-file>] [--summary <file>] <backend-config>" >&2
  exit 2
}

absolute_path() {
  if [[ "$1" == /* ]]; then
    printf '%s\n' "$1"
  else
    printf '%s\n' "${PWD}/$1"
  fi
}

PLAN_ARGS=()
PLAN_FILE="${TERRAFORM_DIR}/tfplan"
SUMMARY_FILE=""
while (($# > 0)); do
  case "$1" in
    --lock=false)
      PLAN_ARGS+=(-lock=false)
      shift
      ;;
    --out)
      (($# >= 2)) || usage
      PLAN_FILE="$(absolute_path "$2")"
      shift 2
      ;;
    --summary)
      (($# >= 2)) || usage
      SUMMARY_FILE="$(absolute_path "$2")"
      shift 2
      ;;
    -*)
      usage
      ;;
    *)
      break
      ;;
  esac
done
(($# == 1)) || usage
readonly BACKEND_CONFIG="$1"
readonly PLAN_ARGS PLAN_FILE SUMMARY_FILE
readonly PLAN_JSON="${PLAN_FILE}.json"

check_plan() {
  uv run --no-project python "${REPO_ROOT}/scripts/check_plan_safety.py" "$PLAN_JSON"
}

main() {
  cd "$TERRAFORM_DIR"

  echo "==> Initialising infra/terraform against the remote state"
  # -reconfigure: a local directory last initialised by `make infra-check` (-backend=false)
  # otherwise stops on the backend change; nothing is migrated, the remote state is used as is.
  # -lockfile=readonly: the plan uses the provider versions and hashes reviewed in the committed
  # .terraform.lock.hcl, never a newer release published since.
  terraform init -input=false -reconfigure -lockfile=readonly "-backend-config=${BACKEND_CONFIG}"

  echo "==> Planning infra/terraform"
  terraform plan -input=false "${PLAN_ARGS[@]}" "-out=${PLAN_FILE}"

  echo "==> Exporting the saved plan as JSON"
  terraform show -json "$PLAN_FILE" > "$PLAN_JSON"

  echo "==> Checking the plan deletes, replaces or forgets nothing"
  if [[ -n "$SUMMARY_FILE" ]]; then
    check_plan >> "$SUMMARY_FILE"
  else
    check_plan
  fi
}

main
