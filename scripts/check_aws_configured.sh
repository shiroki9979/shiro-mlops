#!/usr/bin/env bash
# Decide whether a CI job that needs AWS runs. Until ops acceptance sets the job's role-ARN
# repository variable, AWS is not provisioned: the job emits a notice and one job summary line
# and its later steps are skipped, so the workflow stays green; setting the variable enables it.
# Writes configured=true|false to $GITHUB_OUTPUT for the later steps' `if:` and always exits 0
# on valid arguments.
#
# Usage: scripts/check_aws_configured.sh <variable-name> <skipped-work>
#   variable-name  environment variable holding the role ARN, e.g. AWS_TERRAFORM_PLAN_ROLE_ARN
#   skipped-work   what the job skips, shown in the notice and summary, e.g. "Terraform plan"
set -euo pipefail

if (($# != 2)); then
  echo "Usage: $0 <variable-name> <skipped-work>" >&2
  exit 2
fi

readonly VARIABLE="$1"
readonly SKIPPED_WORK="$2"

if [[ -z "${!VARIABLE:-}" ]]; then
  echo "::notice::AWS 尚未設定，略過 ${SKIPPED_WORK}"
  echo "AWS 尚未設定（repository variable \`${VARIABLE}\` 未設定），略過 ${SKIPPED_WORK}。" >> "$GITHUB_STEP_SUMMARY"
  echo "configured=false" >> "$GITHUB_OUTPUT"
else
  echo "configured=true" >> "$GITHUB_OUTPUT"
fi
