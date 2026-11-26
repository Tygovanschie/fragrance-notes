#!/bin/sh
# Deploys fragrancenotes.app (site/ + worker/) with Wrangler in a throwaway Node container.
# Run on the server from a copy of the repo's site/ and worker/ folders:  sh worker/deploy.sh [--dry-run]
# ~/site-deploy.env holds CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID, ALERT_EMAIL and STATE_KV_ID; the token is
# never printed, and the alert address only goes into a generated config that isn't committed.
set -eu
cd "$(dirname "$0")/.."
envfile="${SITE_DEPLOY_ENV:-$HOME/site-deploy.env}"
get() { sed -n "s/^$1=//p" "$envfile" | tr -d '\r'; }
alert=$(get ALERT_EMAIL)
kv=$(get STATE_KV_ID)
if [ -z "$alert" ] || [ -z "$kv" ]; then
  echo "ALERT_EMAIL and STATE_KV_ID must be set in $envfile" >&2
  exit 1
fi
# The key of the private review page (made by the API next to its database, see gate.py): the daily email links to
# the page with it. It only goes into the generated config, and is hidden in the output below like the address.
review=$(tr -cd 'A-Za-z0-9_-' < "${REVIEW_KEY_FILE:-$HOME/fragrance-api/data/review.key}" 2>/dev/null || true)
review=${review:-__REVIEW_KEY__}
sed -e "s|__ALERT_EMAIL__|$alert|g" -e "s|__STATE_KV_ID__|$kv|g" -e "s|__REVIEW_KEY__|$review|g" \
  worker/wrangler.jsonc > worker/wrangler.deploy.jsonc
log=$(mktemp)
status=0
docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp --env-file "$envfile" -e WRANGLER_SEND_METRICS=false \
  -v "$PWD/site:/w/site:ro" -v "$PWD/worker:/w/worker" -w /w/worker \
  node:22-alpine npx --yes wrangler@4.42.0 deploy --config wrangler.deploy.jsonc ${1:+"$1"} > "$log" 2>&1 || status=$?
sed -E -e 's/cfut_[A-Za-z0-9_]+/[hidden]/g' -e "s|$alert|[alert address]|g" -e "s|$review|[review key]|g" "$log"
rm -f "$log" worker/wrangler.deploy.jsonc
exit $status
