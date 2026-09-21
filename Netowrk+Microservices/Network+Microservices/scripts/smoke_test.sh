#!/usr/bin/env bash
# End-to-end check of Person 1's deliverable.
# Proves: services are up, the gateway forwards over HTTP, inventory reaches
# both auth and postgres, and a protected write completes.
set -euo pipefail

GW="${GATEWAY_URL:-http://localhost:8080}"
pass=0; fail=0

check() {
  local name="$1"; shift
  if "$@" >/dev/null 2>&1; then
    printf '  \033[32mPASS\033[0m  %s\n' "$name"; pass=$((pass+1))
  else
    printf '  \033[31mFAIL\033[0m  %s\n' "$name"; fail=$((fail+1))
  fi
}

echo "==> Waiting for gateway at $GW"
for _ in $(seq 1 60); do
  curl -sf "$GW/health" >/dev/null 2>&1 && break
  sleep 2
done

echo "==> Health"
check "gateway /health"        curl -sf "$GW/health"
check "all services UP"        bash -c "curl -sf '$GW/api/status' | grep -q '\"overall\": *\"HEALTHY\"'"

echo "==> Catalogue (gateway -> inventory -> postgres)"
check "GET /api/items"         bash -c "curl -sf '$GW/api/items' | grep -q 'SKU-1001'"
check "GET /api/items/SKU-1002" curl -sf "$GW/api/items/SKU-1002"

echo "==> Auth (gateway -> auth)"
check "bad password rejected"  bash -c "[ \"\$(curl -s -o /dev/null -w '%{http_code}' -X POST '$GW/api/login' -H 'Content-Type: application/json' -d '{\"username\":\"tej\",\"password\":\"wrong\"}')\" = 401 ]"

TOKEN="$(curl -s -X POST "$GW/api/login" -H 'Content-Type: application/json' \
  -d '{"username":"tej","password":"cn2026"}' | python3 -c 'import sys,json; print(json.load(sys.stdin)["token"])')"
check "login returned a token" bash -c "[ -n '$TOKEN' ]"

echo "==> Protected write (gateway -> inventory -> auth -> postgres)"
check "no token => 401"        bash -c "[ \"\$(curl -s -o /dev/null -w '%{http_code}' -X POST '$GW/api/items/SKU-1001/stock' -H 'Content-Type: application/json' -d '{\"delta\":1}')\" = 401 ]"
check "stock adjust with token" bash -c "curl -sf -X POST '$GW/api/items/SKU-1001/stock' -H 'Content-Type: application/json' -H 'Authorization: Bearer $TOKEN' -d '{\"delta\":-3}' | grep -q updated_by"

echo "==> Observability hooks"
check "GET /metrics"           bash -c "curl -sf '$GW/metrics' | grep -q requests_total"
check "GET /api/topology"      bash -c "curl -sf '$GW/api/topology' | grep -q postgres"
check "trace id propagated"    bash -c "curl -sf -D - -o /dev/null '$GW/api/items' | grep -qi 'x-trace-id'"

echo
echo "passed: $pass   failed: $fail"
[ "$fail" -eq 0 ]
