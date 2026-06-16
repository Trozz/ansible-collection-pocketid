#!/usr/bin/env bash
#
# integration-bootstrap.sh - bring up a Pocket-ID test instance and seed it for
# the trozz.pocketid integration suite.
#
# Topology: Pocket-ID runs in Docker published on localhost:1411; the ansible
# play runs in a host venv targeting localhost (connection: local). This script
# starts the compose stack, waits for the SQLite DB + container health, seeds an
# admin user and an API key (schema-aware) whose `key` column is the unsalted
# SHA-256 hex of a FIXED token, runs a pre-flight authenticated smoke check, and
# renders tests/integration/integration_config.yml from its template.
#
# Requires: docker (compose v2), sqlite3, curl, sha256sum or shasum.
#
# Usage:
#   bash scripts/integration-bootstrap.sh          # bring up + seed + smoke
#   bash scripts/integration-bootstrap.sh --down   # tear down the stack
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
TEST_TOKEN="test-ansible-pocketid-token-0123456789"
BASE_URL="http://localhost:1411"
COMPOSE_FILE="$PROJECT_ROOT/docker-compose.test.yml"
TEST_DATA_DIR="$PROJECT_ROOT/tests/integration/test-data"
DB_PATH="$TEST_DATA_DIR/data/pocket-id.db"
CONFIG_TEMPLATE="$PROJECT_ROOT/tests/integration/integration_config.yml.template"
CONFIG_FILE="$PROJECT_ROOT/tests/integration/integration_config.yml"

export POCKET_ID_IMAGE="${POCKET_ID_IMAGE:-ghcr.io/pocket-id/pocket-id:v2}"
export ENCRYPTION_KEY="${ENCRYPTION_KEY:-test-ansible-pocketid-encryption-key}"
export PUID="${PUID:-$(id -u)}"
export PGID="${PGID:-$(id -g)}"

# Pick a compose command (docker compose v2 preferred, docker-compose fallback).
if docker compose version >/dev/null 2>&1; then
    COMPOSE=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE=(docker-compose)
else
    echo "ERROR: docker compose (v2) or docker-compose is required." >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
sha256_hex() {
    # Print the unsalted SHA-256 hex of stdin, matching utils.CreateSha256Hash.
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum | cut -d' ' -f1
    else
        shasum -a 256 | cut -d' ' -f1
    fi
}

gen_uuid() {
    # Prefer uuidgen; fall back to the kernel uuid; finally to sqlite randomblob.
    if command -v uuidgen >/dev/null 2>&1; then
        uuidgen | tr '[:upper:]' '[:lower:]'
    elif [ -r /proc/sys/kernel/random/uuid ]; then
        cat /proc/sys/kernel/random/uuid
    else
        sqlite3 "$DB_PATH" "SELECT lower(hex(randomblob(16)));"
    fi
}

require_cmd() {
    command -v "$1" >/dev/null 2>&1 || { echo "ERROR: '$1' is required but not installed." >&2; exit 1; }
}

down() {
    echo "Tearing down Pocket-ID test stack..."
    "${COMPOSE[@]}" -f "$COMPOSE_FILE" down -v --remove-orphans || true
    rm -f "$CONFIG_FILE"
    rm -rf "$TEST_DATA_DIR/data"
    echo "Done."
}

# ---------------------------------------------------------------------------
# Tear-down mode
# ---------------------------------------------------------------------------
if [ "${1:-}" = "--down" ]; then
    down
    exit 0
fi

require_cmd sqlite3
require_cmd curl
require_cmd docker

TOKEN_HASH="$(printf '%s' "$TEST_TOKEN" | sha256_hex)"

# ---------------------------------------------------------------------------
# Start the stack (fresh DB each run for deterministic seeding)
# ---------------------------------------------------------------------------
echo "Using Pocket-ID image: $POCKET_ID_IMAGE"
mkdir -p "$TEST_DATA_DIR/data"
rm -f "$DB_PATH" "$DB_PATH-wal" "$DB_PATH-shm"

echo "Starting Pocket-ID test stack..."
"${COMPOSE[@]}" -f "$COMPOSE_FILE" up -d

# ---------------------------------------------------------------------------
# Wait for the database file to exist and migrations to create the tables
# ---------------------------------------------------------------------------
echo "Waiting for the Pocket-ID database and migrations..."
MAX_RETRIES=60
RETRY_COUNT=0
while [ "$RETRY_COUNT" -lt "$MAX_RETRIES" ]; do
    if [ -f "$DB_PATH" ] && \
       sqlite3 "$DB_PATH" "SELECT name FROM sqlite_master WHERE type='table' AND name='api_keys';" 2>/dev/null | grep -q "api_keys" && \
       sqlite3 "$DB_PATH" "SELECT name FROM sqlite_master WHERE type='table' AND name='users';" 2>/dev/null | grep -q "users"; then
        echo "Database ready (users + api_keys tables present)."
        break
    fi
    RETRY_COUNT=$((RETRY_COUNT + 1))
    echo "  waiting for DB/migrations... (attempt $RETRY_COUNT/$MAX_RETRIES)"
    sleep 2
done

if [ "$RETRY_COUNT" -ge "$MAX_RETRIES" ]; then
    echo "ERROR: timed out waiting for the Pocket-ID database/migrations." >&2
    echo "Container logs:" >&2
    "${COMPOSE[@]}" -f "$COMPOSE_FILE" logs --no-color || true
    exit 1
fi

# ---------------------------------------------------------------------------
# Schema-aware seeding
# ---------------------------------------------------------------------------
# Discover the actual columns so we never blind-insert into a drifted schema
# (and never null unspecified NOT NULL columns via INSERT OR REPLACE).
USERS_COLS="$(sqlite3 "$DB_PATH" "SELECT name FROM pragma_table_info('users');")"
APIKEYS_COLS="$(sqlite3 "$DB_PATH" "SELECT name FROM pragma_table_info('api_keys');")"

has_col() {
    # has_col <newline-separated-column-list> <column-name>
    printf '%s\n' "$1" | grep -qx "$2"
}

# Columns we must be able to populate. If any are missing, the upstream schema
# has drifted in a way this bootstrap does not understand: fail loudly rather
# than emit a raw SQLite error mid-INSERT.
REQUIRED_USERS_COLS="id username is_admin"
REQUIRED_APIKEYS_COLS="id key user_id name expires_at"

MISSING=""
for c in $REQUIRED_USERS_COLS; do
    has_col "$USERS_COLS" "$c" || MISSING="$MISSING users.$c"
done
for c in $REQUIRED_APIKEYS_COLS; do
    has_col "$APIKEYS_COLS" "$c" || MISSING="$MISSING api_keys.$c"
done
if [ -n "$MISSING" ]; then
    echo "ERROR: Pocket-ID schema drift detected; missing expected column(s):$MISSING" >&2
    echo "  users columns:    $(echo $USERS_COLS | tr '\n' ' ')" >&2
    echo "  api_keys columns: $(echo $APIKEYS_COLS | tr '\n' ' ')" >&2
    echo "Update scripts/integration-bootstrap.sh to match the new schema." >&2
    exit 1
fi

ADMIN_ID="$(gen_uuid)"
APIKEY_ID="$(gen_uuid)"
NOW="$(date -u +'%Y-%m-%d %H:%M:%S')"

# Build the users INSERT dynamically from the columns that actually exist,
# supplying sensible values only for columns we know about and that are present.
build_insert() {
    # build_insert <table> <available-cols-newline> <colspec...>
    # colspec entries are "column=sql_value"; only emitted when the column exists.
    local table="$1"; shift
    local avail="$1"; shift
    local cols="" vals=""
    local spec col val
    for spec in "$@"; do
        col="${spec%%=*}"
        val="${spec#*=}"
        if has_col "$avail" "$col"; then
            if [ -n "$cols" ]; then
                cols="$cols, $col"
                vals="$vals, $val"
            else
                cols="$col"
                vals="$val"
            fi
        fi
    done
    printf "INSERT INTO %s (%s) VALUES (%s);" "$table" "$cols" "$vals"
}

# Seed an admin user only if one does not already exist.
ADMIN_EXISTS="$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM users WHERE is_admin = 1;")"
if [ "$ADMIN_EXISTS" -eq 0 ]; then
    echo "Seeding admin user..."
    USER_INSERT="$(build_insert users "$USERS_COLS" \
        "id='$ADMIN_ID'" \
        "username='admin'" \
        "email='admin@test.local'" \
        "email_verified=1" \
        "first_name='Test'" \
        "last_name='Admin'" \
        "display_name='Test Admin'" \
        "is_admin=1" \
        "disabled=0" \
        "created_at='$NOW'" \
        "updated_at='$NOW'")"
    sqlite3 "$DB_PATH" "$USER_INSERT"
fi

ADMIN_ID="$(sqlite3 "$DB_PATH" "SELECT id FROM users WHERE is_admin = 1 ORDER BY username LIMIT 1;")"
if [ -z "$ADMIN_ID" ]; then
    echo "ERROR: no admin user present after seeding." >&2
    exit 1
fi

# Replace any existing test key, then insert ours bound to the admin.
echo "Seeding API key bound to admin ($ADMIN_ID)..."
sqlite3 "$DB_PATH" "DELETE FROM api_keys WHERE key = '$TOKEN_HASH';"
APIKEY_INSERT="$(build_insert api_keys "$APIKEYS_COLS" \
    "id='$APIKEY_ID'" \
    "name='ansible-integration-test'" \
    "key='$TOKEN_HASH'" \
    "description='trozz.pocketid integration token'" \
    "user_id='$ADMIN_ID'" \
    "expiration_email_sent=0" \
    "expires_at='2099-12-31 23:59:59'" \
    "created_at='$NOW'" \
    "updated_at='$NOW'")"
sqlite3 "$DB_PATH" "$APIKEY_INSERT"

# ---------------------------------------------------------------------------
# Wait for container health (HTTP listener up) before the smoke check
# ---------------------------------------------------------------------------
echo "Waiting for Pocket-ID HTTP listener..."
HTTP_READY=0
for i in $(seq 1 30); do
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
# GET /api/users with the token. This proves the token hash + schema seeding are
# correct AND that the bound user has admin scope (the endpoint is admin-only).
echo "Running pre-flight authenticated smoke check (GET /api/users)..."
SMOKE_BODY="$(mktemp)"
trap 'rm -f "$SMOKE_BODY"' EXIT
SMOKE_CODE="$(curl -s -o "$SMOKE_BODY" -w '%{http_code}' \
    -H "X-API-Key: $TEST_TOKEN" \
    -H "Accept: application/json" \
    "$BASE_URL/api/users")"

if [ "$SMOKE_CODE" != "200" ]; then
    echo "ERROR: pre-flight smoke check failed: GET /api/users returned HTTP $SMOKE_CODE." >&2
    echo "This usually means token-hash drift, schema drift, or missing admin scope." >&2
    echo "Response body:" >&2
    cat "$SMOKE_BODY" >&2 || true
    exit 1
fi

if ! grep -q '"admin"' "$SMOKE_BODY" && ! grep -q 'admin@test.local' "$SMOKE_BODY"; then
    echo "ERROR: smoke check returned HTTP 200 but the seeded admin user was not found." >&2
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

# Also export for callers that prefer env-based connection (e.g. lookups).
export POCKETID_BASE_URL="$BASE_URL"
export POCKETID_API_TOKEN="$TEST_TOKEN"
export POCKETID_VALIDATE_CERTS="false"

cat <<EOF

Pocket-ID integration environment ready.
  POCKETID_BASE_URL=$BASE_URL
  POCKETID_API_TOKEN=$TEST_TOKEN
  integration_config: $CONFIG_FILE

Next:
  ansible-test integration --local -v

Tear down with:
  bash scripts/integration-bootstrap.sh --down
EOF
