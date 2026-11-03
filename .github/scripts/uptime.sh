#!/usr/bin/env bash
# Is production up and still guarded? Read-only GETs, no credentials.
# Run by .github/workflows/uptime.yml every 6 hours; runnable by hand:
#   API=https://… SITE=https://… .github/scripts/uptime.sh
#
# Each check names what it proves. A failure exits 1 and the workflow run
# fails, which GitHub emails to whoever last changed the schedule.
set -uo pipefail

API="${API:?set API, e.g. https://monorepo-eligo-production.up.railway.app}"
SITE="${SITE:?set SITE, e.g. https://eligolabs.com}"
failed=0

check() {  # name, expected status, url  → prints the body to $BODY
  local name=$1 want=$2 url=$3
  BODY=$(mktemp)
  local got
  got=$(curl -s -o "$BODY" -w '%{http_code}' -m 20 "$url" || true)  # curl prints 000 itself
  if [ "$got" = "$want" ]; then
    echo "ok    $name ($got)"
    return 0
  fi
  echo "FAIL  $name: expected $want, got $got — $url"
  failed=1
  return 1
}

# 1. The API answers and says so.
if check "API health" 200 "$API/api/v1/health"; then
  grep -q '"status":"ok"' "$BODY" || { echo "FAIL  API health body: $(head -c 200 "$BODY")"; failed=1; }
fi

# 2. Login is still enforced. 401, not 200 (open) and not 404 (route gone):
#    a check that accepted either would pass on exactly the outage it exists for.
check "login enforced on /candidates" 401 "$API/api/v1/candidates"

# 3. The Claude connector can still find its authorization server.
if check "Claude connector metadata" 200 "$API/.well-known/oauth-protected-resource/mcp"; then
  python3 - "$BODY" "$API/mcp" <<'PY' || failed=1
import json, sys
body, want = json.load(open(sys.argv[1])), sys.argv[2]
if body.get("resource") != want or not body.get("authorization_servers"):
    print(f"FAIL  Claude connector metadata: resource={body.get('resource')!r}, want {want!r}")
    sys.exit(1)
PY
fi

# 4. The site serves a page AND the script that page loads — an HTML shell
#    whose bundle 404s is a blank screen that still answers 200.
if check "site" 200 "$SITE"; then
  asset=$(grep -oE '/assets/[^"]+\.js' "$BODY" | head -1)
  if [ -z "$asset" ]; then
    echo "FAIL  site: no /assets/*.js in the page"; failed=1
  else
    check "site bundle $asset" 200 "$SITE$asset"
  fi
fi

exit $failed
