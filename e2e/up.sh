#!/usr/bin/env bash
# Start the forge, create an owner and an author, register the two runners.
set -euo pipefail
cd "$(dirname "$0")"
docker compose up -d gitea
until curl -fsS http://127.0.0.1:3000/api/healthz >/dev/null 2>&1; do sleep 1; done
g() { docker compose exec -T -u git gitea gitea "$@"; }
g admin user create --admin --username owner --password owner-pass-1234 --email owner@example.invalid --must-change-password=false >/dev/null 2>&1 || true
g admin user create --username author --password author-pass-1234 --email author@example.invalid --must-change-password=false >/dev/null 2>&1 || true
{
  echo "UNTRUSTED_TOKEN=$(g actions generate-runner-token)"
  echo "TRUSTED_TOKEN=$(g actions generate-runner-token)"
} > .env
docker compose up -d runner-untrusted runner-trusted
echo "forge up at http://127.0.0.1:3000"
