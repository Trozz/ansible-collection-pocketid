#!/usr/bin/env bash
#
# integration-bootstrap.sh - bring up a Pocket-ID test instance for the
# trozz.pocketid integration suite.
#
# Topology: Pocket-ID runs in Docker published on localhost:1411; the ansible
# play runs in a host venv targeting localhost (connection: local).
#
# Authentication uses Pocket-ID's built-in STATIC_API_KEY (set in
# docker-compose.test.yml). On first authenticated use the server creates an
# admin-scoped user bound to that key, so NO database seeding is required. This
# is schema-drift-proof across the v2 and next images and needs no sqlite3.
#
# This script starts the compose stack, waits for the HTTP listener, runs a
# pre-flight authenticated smoke check (which also provisions the static admin
# user), and renders tests/integration/integration_config.yml.
#
# Requires: docker (compose v2), curl.
#
# Usage:
#   bash scripts/integration-bootstrap.sh          # bring up + smoke check
#   bash scripts/integration-bootstrap.sh --down   # tear down the stack
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
# The token MUST match STATIC_API_KEY in docker-compose.test.yml and be >= 16
# characters (enforced by Pocket-ID).
TEST_TOKEN="${POCKETID_STATIC_API_KEY:-test-ansible-pocketid-static-key-0123456789}"
BASE_URL="http://localhost:1411"
COMPOSE_FILE="$PROJECT_ROOT/docker-compose.test.yml"
CONFIG_TEMPLATE="$PROJECT_ROOT/tests/integration/integration_config.yml.template"
CONFIG_FILE="$PROJECT_ROOT/tests/integration/integration_config.yml"

export POCKET_ID_IMAGE="${POCKET_ID_IMAGE:-ghcr.io/pocket-id/pocket-id:v2}"
export ENCRYPTION_KEY="${ENCRYPTION_KEY:-test-ansible-pocketid-encryption-key}"
export POCKETID_STATIC_API_KEY="$TEST_TOKEN"

# Pick a compose command (docker compose v2 preferred, docker-compose fallback).
if docker compose version >/dev/null 2>&1; then
    COMPOSE=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE=(docker-compose)
else
    echo "ERROR: docker compose (v2) or docker-compose is required." >&2
    exit 1
fi

require_cmd() {
    command -v "$1" >/dev/null 2>&1 || { echo "ERROR: '$1' is required but not installed." >&2; exit 1; }
}

down() {
    echo "Tearing down Pocket-ID test stack..."
    "${COMPOSE[@]}" -f "$COMPOSE_FILE" down -v --remove-orphans || true
    rm -f "$CONFIG_FILE"
    echo "Done."
}

if [ "${1:-}" = "--down" ]; then
    down
    exit 0
fi

require_cmd curl
require_cmd docker

# ---------------------------------------------------------------------------
# Start the stack
# ---------------------------------------------------------------------------
echo "Using Pocket-ID image: $POCKET_ID_IMAGE"
echo "Starting Pocket-ID test stack..."
"${COMPOSE[@]}" -f "$COMPOSE_FILE" up -d

# ---------------------------------------------------------------------------
# Wait for the HTTP listener
# ---------------------------------------------------------------------------
echo "Waiting for Pocket-ID HTTP listener..."
HTTP_READY=0
for _ in $(seq 1 45); do
    if curl -fsS -o /dev/null "$BASE_URL/healthz" 2>/dev/null \
       || curl -fsS -o /dev/null "$BASE_URL/" 2>/dev/null; then
        HTTP_READY=1
        break
    fi
    sleep 2
done
if [ "$HTTP_READY" -ne 1 ]; then
    echo "ERROR: Pocket-ID HTTP listener did not come up at $BASE_URL." >&2
    "${COMPOSE[@]}" -f "$COMPOSE_FILE" logs --no-color || true
    exit 1
fi

# ---------------------------------------------------------------------------
# Pre-flight authenticated smoke check
# ---------------------------------------------------------------------------
# GET /api/users with the static key. The first authenticated call provisions
# the admin-scoped static user; a 200 proves the key works AND that it has admin
# scope (the endpoint is admin-only). Retried briefly to absorb startup races.
echo "Running pre-flight authenticated smoke check (GET /api/users)..."
SMOKE_BODY="$(mktemp)"
trap 'rm -f "$SMOKE_BODY"' EXIT
SMOKE_CODE=""
for _ in $(seq 1 10); do
    SMOKE_CODE="$(curl -s -o "$SMOKE_BODY" -w '%{http_code}' \
        -H "X-API-Key: $TEST_TOKEN" \
        -H "Accept: application/json" \
        "$BASE_URL/api/users" || true)"
    [ "$SMOKE_CODE" = "200" ] && break
    sleep 2
done

if [ "$SMOKE_CODE" != "200" ]; then
    echo "ERROR: pre-flight smoke check failed: GET /api/users returned HTTP $SMOKE_CODE." >&2
    echo "This usually means STATIC_API_KEY is unset/mismatched or the server is not ready." >&2
    echo "Response body:" >&2
    cat "$SMOKE_BODY" >&2 || true
    exit 1
fi
echo "Smoke check passed (admin scope confirmed)."

# ---------------------------------------------------------------------------
# Render integration_config.yml from the template
# ---------------------------------------------------------------------------
echo "Rendering $CONFIG_FILE..."
sed -e "s|@@POCKETID_BASE_URL@@|$BASE_URL|g" \
    -e "s|@@POCKETID_API_TOKEN@@|$TEST_TOKEN|g" \
    "$CONFIG_TEMPLATE" > "$CONFIG_FILE"

cat <<EOF

Pocket-ID integration environment ready.
  POCKETID_BASE_URL=$BASE_URL
  POCKETID_API_TOKEN=$TEST_TOKEN
  integration_config: $CONFIG_FILE

Next:
  ansible-test integration --local -v --allow-unsupported

Tear down with:
  bash scripts/integration-bootstrap.sh --down
EOF
