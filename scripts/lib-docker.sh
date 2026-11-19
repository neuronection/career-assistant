#!/bin/bash

# Career Assistant — shared helpers for the Docker ops scripts.
#
# Sourced by scripts/run-docker.sh and scripts/update-docker.sh; not meant
# to be run directly. Family-adapted from Health Assistant's lib-docker.sh.

# Colors for output
# shellcheck disable=SC2034  # YELLOW is used by the sourcing scripts
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

COMPOSE_FILE="docker/docker-compose.standalone.yml"
COMPOSE_ENV_ARGS=(--env-file docker/.env -f "${COMPOSE_FILE}")
HEALTH_URL="http://127.0.0.1:${HTTP_PORT:-80}/health"

die() {
    echo -e "${RED}Error: $1${NC}" >&2
    exit 1
}

check_cwd() {
    if [ ! -d "backend" ] || [ ! -d "frontend" ]; then
        die "Please run this script from the Career Assistant root directory"
    fi
}

check_docker() {
    if ! command -v docker &> /dev/null; then
        die "Docker is not installed. Please install Docker first."
    fi
    if ! docker info &> /dev/null; then
        die "Docker daemon is not running. Please start Docker first."
    fi
    DOCKER_COMPOSE_CMD="docker compose"
    if ! docker compose version &> /dev/null; then
        if command -v docker-compose &> /dev/null; then
            DOCKER_COMPOSE_CMD="docker-compose"
        else
            die "Docker Compose is not installed (neither 'docker compose' nor 'docker-compose' is available)."
        fi
    fi
}

require_env() {
    if [ ! -f "docker/.env" ]; then
        die "docker/.env not found. Run: cp docker/.env.production.example docker/.env && edit secrets"
    fi
}

# ── docker/.env helpers (shared installer/updater helpers) ───────────────────
# Used by the bundle installer/updater (scripts/install.sh, update.sh); the
# developer scripts keep using require_env above. Written to survive
# `set -euo pipefail` in the sourcing script.

ENV_FILE="docker/.env"

# Read one KEY from docker/.env (last occurrence wins, compose's own rule).
# Usage: env_value KEY [default]
env_value() {
    local VALUE
    VALUE="$(grep -E "^$1=" "$ENV_FILE" 2>/dev/null | tail -n1 | cut -d= -f2- || true)"
    printf '%s' "${VALUE:-$2}"
}

# Persist KEY=VALUE in docker/.env without disturbing anything else. Replaces
# every uncommented occurrence (a duplicate cannot shadow the new value),
# appends when absent, writes through a temp file so a failure cannot
# truncate docker/.env. The caller is responsible for never clobbering a
# KEY the operator set by hand — the installer only writes pins/ports and
# freshly generated secrets.
# Usage: set_env_value KEY VALUE
set_env_value() {
    local KEY="$1" VALUE="$2" TMP
    [ -f "$ENV_FILE" ] || die "set_env_value: $ENV_FILE not found in $(pwd)"
    TMP="$(mktemp)"
    awk -v k="$KEY" -v v="$VALUE" '
        index($0, k "=") == 1 { print k "=" v; next }
        { print }
    ' "$ENV_FILE" > "$TMP" || { rm -f "$TMP"; die "Could not update ${KEY} in ${ENV_FILE}"; }
    if ! grep -qE "^${KEY}=" "$TMP"; then
        printf '%s=%s\n' "$KEY" "$VALUE" >> "$TMP"
    fi
    cat "$TMP" > "$ENV_FILE"
    rm -f "$TMP"
}

# One scalar field from a JSON file, dotted-path form ("images.app").
# Strings and numbers (the schema's healthPath/setupMode/defaultPort…);
# booleans and null read as empty. python3 when available, sed fallback for
# flat fields, empty when the file or key is missing — callers carry their
# own defaults. Used for the release manifest (./manifest.json) and the
# product config (./installer.json) that ship with the source-free bundle.
# Usage: json_field FILE KEY[.KEY…]
json_field() {
    local FILE="$1" KEYPATH="$2" OUT=""
    [ -f "$FILE" ] || { printf ''; return 0; }
    if command -v python3 &>/dev/null; then
        OUT="$(python3 -c '
import json, sys
try:
    node = json.load(open(sys.argv[1]))
except Exception:
    sys.exit(0)
for part in sys.argv[2].split("."):
    node = node.get(part) if isinstance(node, dict) else None
    if node is None:
        sys.exit(0)
if isinstance(node, (str, int, float)) and not isinstance(node, bool):
    print(node)
' "$FILE" "$KEYPATH" 2>/dev/null || true)"
    fi
    if [ -z "$OUT" ]; then
        OUT="$(sed -n "s/.*\"${KEYPATH##*.}\"[[:space:]]*:[[:space:]]*\"\([^\"]*\)\".*/\1/p" "$FILE" 2>/dev/null | head -n1)"
    fi
    if [ -z "$OUT" ]; then
        # numeric scalar fallback (defaultPort, minRamGb…)
        OUT="$(sed -n "s/.*\"${KEYPATH##*.}\"[[:space:]]*:[[:space:]]*\([0-9][0-9]*\).*/\1/p" "$FILE" 2>/dev/null | head -n1)"
    fi
    printf '%s' "$OUT"
}

# A flat JSON array of strings as space-separated words (installer.json's
# imageKeys — the closed vocabulary of manifest image slots). Empty when the
# file or key is missing; callers warn and fall back.
# Usage: json_keys FILE KEY
json_keys() {
    local FILE="$1" KEY="$2" OUT=""
    [ -f "$FILE" ] || { printf ''; return 0; }
    if command -v python3 &>/dev/null; then
        OUT="$(python3 -c '
import json, sys
try:
    node = json.load(open(sys.argv[1])).get(sys.argv[2])
except Exception:
    sys.exit(0)
if isinstance(node, list):
    print(" ".join(str(v) for v in node))
' "$FILE" "$KEY" 2>/dev/null || true)"
    fi
    if [ -z "$OUT" ]; then
        OUT="$(sed -n "s/.*\"$KEY\"[[:space:]]*:[[:space:]]*\[\([^]]*\)\].*/\1/p" "$FILE" 2>/dev/null \
            | tr -d '"' | tr ',' ' ')"
    fi
    printf '%s' "$OUT"
}

# The compose project name (the pinned top-level `name:` — fallback
# "career-assistant") — used to reason about named volumes and port owners.
resolve_compose_project() {
    local PROJECT
    PROJECT="$(run_compose config --format json 2>/dev/null \
        | python3 -c 'import sys,json; print(json.load(sys.stdin).get("name",""))' 2>/dev/null || true)"
    [ -z "$PROJECT" ] && PROJECT="career-assistant"
    printf '%s' "$PROJECT"
}

# run_compose ARGS... — run docker compose with the standalone stack args.
run_compose() {
    # DOCKER_COMPOSE_CMD intentionally word-splits: "docker compose" or "docker-compose".
    # shellcheck disable=SC2086
    $DOCKER_COMPOSE_CMD "${COMPOSE_ENV_ARGS[@]}" "$@"
}

# Wait until the app reports healthy via the nginx entrypoint. The poll
# interval and attempt count are overridable (HEALTH_WAIT_INTERVAL /
# HEALTH_WAIT_ATTEMPTS — the installer selftest drives both). On failure,
# name the compose services and the last log lines instead of pointing at
# a bare curl.
wait_for_backend_healthy() {
    local interval="${HEALTH_WAIT_INTERVAL:-2}"
    local attempts="${HEALTH_WAIT_ATTEMPTS:-60}"
    local i
    echo -e "${GREEN}Waiting for the app to become healthy at ${HEALTH_URL}...${NC}"
    for i in $(seq 1 "$attempts"); do
        if curl -fsS "$HEALTH_URL" 2>/dev/null | grep -q '"status"'; then
            echo -e "${GREEN}App is healthy: ${HEALTH_URL}${NC}"
            return 0
        fi
        sleep "$interval"
    done
    echo -e "${RED}App did not become healthy within $((attempts * interval))s.${NC}" >&2
    report_compose_failure
    return 1
}

# Print what the stack actually looks like plus the last log lines of the
# one-shot migrate job and the app, so a failed boot names its culprit
# instead of pointing at a bare health URL.
report_compose_failure() {
    echo -e "${YELLOW}Compose services:${NC}" >&2
    run_compose ps -a 2>/dev/null | sed 's/^/  /' >&2 || true
    echo -e "${YELLOW}Last log lines — migrate:${NC}" >&2
    run_compose logs --tail 15 migrate 2>/dev/null | sed 's/^/  /' >&2 || true
    echo -e "${YELLOW}Last log lines — app:${NC}" >&2
    run_compose logs --tail 15 app 2>/dev/null | sed 's/^/  /' >&2 || true
    echo >&2
    echo -e "Fix the failure above, then re-run this script — it reuses ${ENV_FILE}." >&2
    echo -e "Dig deeper: ${DOCKER_COMPOSE_CMD[*]} ${COMPOSE_ENV_ARGS[*]} logs migrate" >&2
}

# ── Published-port pre-flight ────────────────────────────────────────────────
# A bind conflict otherwise surfaces mid-startup as a raw daemon error,
# after the pull, with no hint which knob to turn. The port set is read
# from the RENDERED compose model — the only source that knows about bind
# addresses and services added later — so this runs after docker/.env
# exists (compose interpolates it).

# Ports the stack would publish, as "<service>\t<port>" lines. Empty when
# the model cannot be rendered (no python3, compose v1, broken
# interpolation) — callers treat empty as "skip".
rendered_ports() {
    run_compose config --format json 2>/dev/null | python3 -c '
import json, sys
try:
    model = json.load(sys.stdin)
except Exception:
    sys.exit(0)
for name, svc in (model.get("services") or {}).items():
    for spec in svc.get("ports") or []:
        published = spec.get("published")
        if not published:
            continue
        # compose may render "<ip>:<port>" (bind address) or "<port>";
        # a range "a-b" publishes every port in it.
        for port in str(published).split(":")[-1].split("-"):
            if port:
                print("%s\t%s" % (name, port))
' 2>/dev/null || true
}

# True when something accepts IPv4 connections on this host port. Loopback
# is where the standalone stack binds and also covers 0.0.0.0.
port_in_use() {
    python3 - "$1" <<'PY'
import socket, sys
sock = socket.socket()
sock.settimeout(0.3)
try:
    sock.connect(("127.0.0.1", int(sys.argv[1])))
except OSError:
    sys.exit(1)
finally:
    sock.close()
sys.exit(0)
PY
}

# True when every container publishing this port belongs to OUR compose
# project — the normal re-run case, which must not read as a conflict.
port_owner_is_project() {
    local PROJECTS
    PROJECTS="$(docker ps --filter "publish=$1" \
        --format '{{.Label "com.docker.compose.project"}}' 2>/dev/null \
        | sed '/^$/d' | sort -u || true)"
    [ -n "$PROJECTS" ] && [ "$PROJECTS" = "$2" ]
}

# The docker/.env variable a published port comes from. Matched by VALUE —
# the variable's current .env value, else its compose default — because the
# rendered port is the overridden one ("${HTTP_PORT:-80}" publishes 8092
# when docker/.env says 8092). Empty for literals ("80:80"), which can only
# be changed in the compose file itself.
port_env_var() {
    local PORT="$1" VAR VALUE DEFAULT
    # shellcheck disable=SC2013  # word-split list of compose env names is intended
    for VAR in $(grep -oE '\$\{[A-Z][A-Z0-9_]*(:-[0-9]+)?\}' "$COMPOSE_FILE" 2>/dev/null \
        | sed -E 's/^\$\{([A-Z][A-Z0-9_]*).*/\1/' | sort -u); do
        VALUE="$(env_value "$VAR" "")"
        if [ -n "$VALUE" ] && [ "$VALUE" = "$PORT" ]; then
            printf '%s' "$VAR"
            return 0
        fi
        if [ -z "$VALUE" ]; then
            DEFAULT="$(sed -n "s/.*\${${VAR}:-\([0-9][0-9]*\)}.*/\1/p" "$COMPOSE_FILE" | head -n1)"
            if [ "$DEFAULT" = "$PORT" ]; then
                printf '%s' "$VAR"
                return 0
            fi
        fi
    done
    return 1
}

next_free_port() {
    local PORT="$1" TRIES=0
    while [ "$TRIES" -lt 50 ] && [ "$PORT" -lt 65535 ]; do
        PORT=$((PORT + 1))
        port_in_use "$PORT" || { printf '%s' "$PORT"; return 0; }
        TRIES=$((TRIES + 1))
    done
    return 1
}

# Fail fast, before anything is pulled or started, when a published host
# port is already taken by something that is not this stack. --auto moves
# a busy port to the next free one and writes it to docker/.env instead.
# Exit code 4 = port conflict (the installer contract).
# Usage: check_published_ports [--auto]
check_published_ports() {
    local AUTO=0
    if [ "${1:-}" = "--auto" ]; then AUTO=1; fi
    local PROJECT LIST SVC PORT VAR FREE CONFLICTS=""
    PROJECT="$(resolve_compose_project)"
    LIST="$(rendered_ports)"
    if [ -z "$LIST" ]; then
        echo -e "${YELLOW}Port pre-flight: could not render the compose model — skipping.${NC}"
        return 0
    fi
    while IFS=$'\t' read -r SVC PORT; do
        [ -n "$PORT" ] || continue
        port_in_use "$PORT" || continue
        port_owner_is_project "$PORT" "$PROJECT" && continue
        VAR="$(port_env_var "$PORT" || true)"
        if [ "$AUTO" = "1" ] && [ -n "$VAR" ]; then
            FREE="$(next_free_port "$PORT")" || FREE=""
            if [ -n "$FREE" ]; then
                set_env_value "$VAR" "$FREE"
                echo -e "${GREEN}Port ${PORT} was busy — ${VAR}=${FREE} written to .env (${ENV_FILE}).${NC}"
                continue
            fi
        fi
        if [ -n "$VAR" ]; then
            CONFLICTS="${CONFLICTS}  ${SVC}: host port ${PORT} is in use → set ${VAR}=<free port> in ${ENV_FILE}"$'\n'
        else
            CONFLICTS="${CONFLICTS}  ${SVC}: host port ${PORT} is in use and is a literal in ${COMPOSE_FILE} → edit it there"$'\n'
        fi
    done <<< "$LIST"
    if [ -n "$CONFLICTS" ]; then
        echo -e "${RED}"
        echo "Port conflict — the stack cannot start:"
        printf '%s' "$CONFLICTS"
        echo -e "${NC}"
        echo "  Find the holder:  ss -ltnp | grep ':<port>'   (or: lsof -i :<port>)"
        echo "  Then re-run this script — it reuses ${ENV_FILE}."
        echo "  Or let the installer pick free ports: --auto-ports"
        echo -e "${RED}Aborted before pulling or starting anything.${NC}"
        exit 4
    fi
    echo -e "${GREEN}Port pre-flight: no conflicts.${NC}"
}

# One-time database/role rename for the ADR-0022 amendment (2026-09-30):
# the family datastore prefix was spelled out — legacy `career*` and
# `neuro_career*` names become `neuronection_career*` (database
# `neuronection_career` + `_test`/`_demo` companions, bootstrap role
# `neuronection_career_owner`).
#
# Existing volumes ignore POSTGRES_DB after first boot, so postgres is
# started FIRST and the rename runs inside it, before the stack boots on
# the new names. Guarded: a legacy name is renamed only when the new name
# is absent — when BOTH exist a pre-flight check aborts with instructions
# before the first rename, and the same guard applies per role. PostgreSQL
# refuses to rename the session's own user, so the owner role is renamed
# through a throwaway `ca_db_migrator` superuser (created, renamed from
# that session, dropped as the renamed owner; `DROP ROLE IF EXISTS` cleans
# up at both ends).
#
# Complete no-op on fresh installs (the legacy names simply don't exist)
# and on re-runs (the new names already do). A connected bootstrap role is
# required, else we fail loud with the manual recipe
# (docker/README.md → "Renaming career_* / neuro_career_* → neuronection_*").
#
# Usage: migrate_legacy_db_names [SERVICE [COMPOSE_ARGS...]]
#   SERVICE       postgres service of the stack (default `db`, standalone)
#   COMPOSE_ARGS  compose invocation (default: the standalone stack args)
migrate_legacy_db_names() {
    local SERVICE="db" NEW_ROLE="neuronection_career_owner"
    local MIGRATOR="ca_db_migrator"
    local ROLE PAIR OLD NEW OLD_EXISTS NEW_EXISTS CONNECTED=""
    local -a CA=("${COMPOSE_ENV_ARGS[@]}")
    local -a DB_PAIRS=(
        "career:neuronection_career"
        "career_test:neuronection_career_test"
        "neuro_career_demo:neuronection_career_demo"
    )
    local -a ROLE_PAIRS=("career:$NEW_ROLE" "neuro_career:$NEW_ROLE")
    if [ $# -gt 0 ]; then SERVICE="$1"; shift; fi
    if [ $# -gt 0 ]; then CA=("$@"); fi

    # DOCKER_COMPOSE_CMD intentionally word-splits: "docker compose"/"docker-compose".
    # shellcheck disable=SC2086
    if ! $DOCKER_COMPOSE_CMD "${CA[@]}" up -d "$SERVICE" >/dev/null; then
        die "Could not start postgres to check legacy database names."
    fi

    # Probe the bootstrap roles: the new owner first (already-renamed and
    # fresh installs), then the legacy ones (old owner → old alternative →
    # admin).
    for _ in $(seq 1 30); do
        for ROLE in "$NEW_ROLE" career neuro_career admin; do
            # shellcheck disable=SC2086
            if $DOCKER_COMPOSE_CMD "${CA[@]}" exec -T "$SERVICE" \
                    psql -U "$ROLE" -d postgres -tAc "select 1" >/dev/null 2>&1; then
                CONNECTED="$ROLE"
                break 2
            fi
        done
        sleep 2
    done
    [ -n "$CONNECTED" ] || die "Cannot connect to postgres to check legacy database names — see docker/README.md → \"Renaming career_* / neuro_career_* → neuronection_*\"."

    _career_pg() {
        # shellcheck disable=SC2086
        $DOCKER_COMPOSE_CMD "${CA[@]}" exec -T "$SERVICE" \
            psql -U "$1" -d postgres -v ON_ERROR_STOP=1 "${@:2}"
    }

    # Pre-flight guard: refuse to start when a legacy name already coexists
    # with its replacement, or when two legacy roles claim the same
    # replacement — abort BEFORE the first rename instead of halfway through
    # it. Each name is renamed only when the new one is absent.
    local LEGACY_ROLE=""
    for PAIR in "${DB_PAIRS[@]}"; do
        OLD="${PAIR%%:*}"
        NEW="${PAIR#*:}"
        OLD_EXISTS="$(_career_pg "$CONNECTED" -tAc "select 1 from pg_database where datname='$OLD'")" || \
            die "Could not read pg_database while checking '$OLD'."
        [ "$OLD_EXISTS" = "1" ] || continue
        NEW_EXISTS="$(_career_pg "$CONNECTED" -tAc "select 1 from pg_database where datname='$NEW'")" || \
            die "Could not read pg_database while checking '$NEW'."
        if [ "$NEW_EXISTS" = "1" ]; then
            die "Both $OLD and $NEW exist — dump $OLD (scripts/backup.sh), restore it into $NEW, drop $OLD, then re-run."
        fi
    done
    for PAIR in "${ROLE_PAIRS[@]}"; do
        OLD="${PAIR%%:*}"
        NEW="${PAIR#*:}"
        OLD_EXISTS="$(_career_pg "$CONNECTED" -tAc "select 1 from pg_roles where rolname='$OLD'")" || \
            die "Could not read pg_roles while checking '$OLD'."
        [ "$OLD_EXISTS" = "1" ] || continue
        if [ -n "$LEGACY_ROLE" ]; then
            die "Both legacy roles $LEGACY_ROLE and $OLD exist and rename to the same $NEW — drop or rename one, then re-run."
        fi
        LEGACY_ROLE="$OLD"
        NEW_EXISTS="$(_career_pg "$CONNECTED" -tAc "select 1 from pg_roles where rolname='$NEW'")" || \
            die "Could not read pg_roles while checking '$NEW'."
        if [ "$NEW_EXISTS" = "1" ]; then
            die "Both roles $OLD and $NEW exist — resolve manually (drop or rename one) before re-running."
        fi
    done

    _career_pg "$CONNECTED" -c "DROP ROLE IF EXISTS $MIGRATOR;" >/dev/null 2>&1 || true

    for PAIR in "${DB_PAIRS[@]}"; do
        OLD="${PAIR%%:*}"
        NEW="${PAIR#*:}"
        OLD_EXISTS="$(_career_pg "$CONNECTED" -tAc "select 1 from pg_database where datname='$OLD'")" || \
            die "Could not read pg_database while checking '$OLD'."
        [ "$OLD_EXISTS" = "1" ] || continue
        _career_pg "$CONNECTED" -c "ALTER DATABASE \"$OLD\" RENAME TO \"$NEW\";" || \
            die "Renaming database $OLD → $NEW failed."
        echo -e "${GREEN}Renamed database $OLD → $NEW${NC}"
    done

    for PAIR in "${ROLE_PAIRS[@]}"; do
        OLD="${PAIR%%:*}"
        NEW="${PAIR#*:}"
        OLD_EXISTS="$(_career_pg "$CONNECTED" -tAc "select 1 from pg_roles where rolname='$OLD'")" || \
            die "Could not read pg_roles while checking '$OLD'."
        [ "$OLD_EXISTS" = "1" ] || continue
        # PostgreSQL refuses to rename the session's own user: go through a
        # throwaway superuser and drop it again as the renamed owner.
        _career_pg "$CONNECTED" -c "DROP ROLE IF EXISTS $MIGRATOR;" \
            && _career_pg "$CONNECTED" -c "CREATE ROLE $MIGRATOR LOGIN SUPERUSER;" \
            && _career_pg "$MIGRATOR" -c "ALTER ROLE $OLD RENAME TO $NEW;" \
            && _career_pg "$NEW" -c "DROP ROLE $MIGRATOR;" \
            || die "Renaming role $OLD → $NEW failed."
        echo -e "${GREEN}Renamed role $OLD → $NEW${NC}"
        # We may just have renamed the role we are connected as.
        if [ "$CONNECTED" = "$OLD" ]; then CONNECTED="$NEW"; fi
    done

    _career_pg "$CONNECTED" -c "DROP ROLE IF EXISTS $MIGRATOR;" >/dev/null 2>&1 || true
    unset -f _career_pg
}
