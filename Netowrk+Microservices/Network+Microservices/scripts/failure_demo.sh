#!/usr/bin/env bash
# Shows what the rest of the team builds on: when auth dies, the gateway
# reports it as DOWN and protected writes fail with 503 (network fault) while
# the public catalogue keeps serving. Person 5 automates the recovery step.
set -euo pipefail
GW="${GATEWAY_URL:-http://localhost:8080}"

echo "==> Baseline"; curl -s "$GW/api/status" | python3 -m json.tool

echo; echo "==> Stopping the auth container"; docker compose stop auth >/dev/null; sleep 3

echo "--- status now:"; curl -s "$GW/api/status" | python3 -m json.tool
echo "--- public catalogue still works (HTTP $(curl -s -o /dev/null -w '%{http_code}' "$GW/api/items"))"
echo "--- login now returns HTTP $(curl -s -o /dev/null -w '%{http_code}' -X POST "$GW/api/login" \
  -H 'Content-Type: application/json' -d '{"username":"tej","password":"cn2026"}')  (503 = unreachable, not 401)"

echo; echo "==> Restarting auth (this is the manual version of Person 5's healer)"
docker compose start auth >/dev/null; sleep 6
curl -s "$GW/api/status" | python3 -m json.tool
