#!/usr/bin/env bash
# Live demo for Review-2: break a real container and watch the healer fix it.
# Prereqs: docker stack up, and `python healer_api.py` running in another terminal.
set -u
HEAL="${HEALER_URL:-http://localhost:9002}"
TARGET="${1:-auth}"                     # service name: auth | inventory | postgres | gateway
CONTAINER="shn-$TARGET"

show() { curl -s "$HEAL/healing/status" | python3 -c "
import sys,json
d=json.load(sys.stdin)
for s in d['services']:
    print(f\"  {s['service']:<10} {s['state']:<11} restarts={s['total_restarts']} last_recovery={s['last_recovery_s']}\")"; }

echo "==> Before"; show
echo; echo "==> Killing $CONTAINER (simulated crash)"; docker kill "$CONTAINER" >/dev/null
for i in $(seq 1 12); do sleep 3; echo "--- t+$((i*3))s"; show; done
echo; echo "==> Healing events"
curl -s "$HEAL/healing/events?limit=10" | python3 -m json.tool
