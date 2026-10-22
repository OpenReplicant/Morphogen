#!/usr/bin/env bash
# Milestone 1 smoke test against the local stack (docker compose up -d first).
# Submits the self-blueprint, waits for the system to observe itself, prints the map report.
set -euo pipefail
cd "$(dirname "$0")/.."

INTAKE=${MORPHOGEN_INTAKE:-http://localhost:8080}
API=${MORPHOGEN_READ_API:-http://localhost:3000}
export MORPHOGEN_READ_DATABASE_URL=${MORPHOGEN_READ_DATABASE_URL:-postgresql://morphogen_reader:change-me@localhost:5432/morphogen}

echo "waiting for intake"
for _ in $(seq 60); do curl -fsS "$INTAKE/healthz" >/dev/null 2>&1 && break; sleep 1; done
curl -fsS "$INTAKE/healthz" >/dev/null

echo "invalid event -> 400"
code=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$INTAKE/events" \
  -H 'content-type: application/cloudevents+json' -d '{"specversion":"1.0"}')
[ "$code" = 400 ] || { echo "expected 400, got $code"; exit 1; }

echo "blueprint -> 202"
curl -fsS -X POST "$INTAKE/events" -H 'content-type: application/cloudevents+json' \
  --data @examples/self-blueprint.json
echo

echo "blueprint visible through the read API"
n=$(curl -fsS "$API/slots?status=eq.hypothetical" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))')
[ "$n" -ge 7 ] || { echo "expected >= 7 hypothetical slots, got $n"; exit 1; }

echo "waiting for the stack's own traces (collector batch + export)"
for _ in $(seq 30); do
  obs=$(curl -fsS "$API/couplings?status=eq.observed" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))')
  [ "$obs" -ge 3 ] && break; sleep 2
done
[ "$obs" -ge 3 ] || { echo "no observed couplings after 60s"; exit 1; }

uv run morphogen-report --environment sandbox
echo "smoke OK"
