#!/bin/sh
# Deploys fragrancenotes.app (site/ + worker/) with Wrangler in a throwaway Node container.
# Run on the server from a copy of the repo's site/ and worker/ folders:  sh worker/deploy.sh [--dry-run]
# The Cloudflare token is read from ~/site-deploy.env (CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID) and never printed.
set -eu
cd "$(dirname "$0")/.."
log=$(mktemp)
status=0
docker run --rm --env-file "$HOME/site-deploy.env" -e WRANGLER_SEND_METRICS=false \
  -v "$PWD/site:/w/site:ro" -v "$PWD/worker:/w/worker" -w /w/worker \
  node:22-alpine npx --yes wrangler@4.42.0 deploy ${1:+"$1"} > "$log" 2>&1 || status=$?
sed -E 's/cfut_[A-Za-z0-9_]+/[hidden]/g' "$log"
rm -f "$log"
exit $status
