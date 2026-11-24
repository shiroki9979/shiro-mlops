#!/usr/bin/env bash
# Run scripts/smoke_cloudfront.py on the host python3 for the CI `deploy` job, which holds an
# OIDC token and so downloads no uv at run time (#369); the check uses only the standard
# library. Arguments pass through unchanged and the exit code is the check's own, unlike
# `make cloud-smoke`, which reports every failure as exit 2.
#
# Usage: scripts/smoke_cloudfront.sh --base-url <forecast_view_url> [options]
set -euo pipefail

readonly REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

exec python3 "${REPO_ROOT}/scripts/smoke_cloudfront.py" "$@"
