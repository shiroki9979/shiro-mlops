#!/usr/bin/env bash
# Upload a built Forecast View to the bucket's site/ prefix in the order hosting spec §5
# (docs/reference/forecast-view-hosting.md) requires: every file but index.html first, then
# index.html, then a `sync --delete` that removes the previous release's assets. No CloudFront
# invalidation: index.html is not cached at the edge and assets carry content hashes. Called by
# the CI deploy job with the site deploy role's credentials, which may write site/* only.
#
# Usage: scripts/upload_forecast_view_site.sh <dist-dir> <bucket>
#   dist-dir  the Forecast View build output (frontend/apps/forecast-view/dist)
#   bucket    the `s3_bucket_name` Terraform output
set -euo pipefail

if (($# != 2)); then
  echo "Usage: $0 <dist-dir> <bucket>" >&2
  exit 2
fi

readonly DIST_DIR="${1%/}"
readonly BUCKET="$2"
readonly SITE_URI="s3://${BUCKET}/site/"

main() {
  # A missing or empty build would make the final `sync --delete` empty site/.
  if [[ ! -f "${DIST_DIR}/index.html" ]]; then
    echo "No ${DIST_DIR}/index.html: build the Forecast View before uploading" >&2
    exit 2
  fi

  echo "==> Uploading assets to ${SITE_URI}"
  # Before index.html, so a viewer never gets an index.html whose assets are not there yet.
  aws s3 sync "${DIST_DIR}/" "$SITE_URI" --exclude index.html --no-progress

  echo "==> Uploading index.html"
  aws s3 cp "${DIST_DIR}/index.html" "${SITE_URI}index.html" --no-progress

  echo "==> Deleting assets of the previous release"
  # Last, so pages still holding the previous index.html keep loading until it is replaced;
  # deleted objects expire after 30 days under the bucket's version rule.
  aws s3 sync "${DIST_DIR}/" "$SITE_URI" --delete --no-progress

  echo "Forecast View uploaded to ${SITE_URI}"
}

main
