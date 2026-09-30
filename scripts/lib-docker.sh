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

# run_compose ARGS... — run docker compose with the standalone stack args.
run_compose() {
    # DOCKER_COMPOSE_CMD intentionally word-splits: "docker compose" or "docker-compose".
    # shellcheck disable=SC2086
    $DOCKER_COMPOSE_CMD "${COMPOSE_ENV_ARGS[@]}" "$@"
}

# Wait until the app reports healthy via the nginx entrypoint.
wait_for_backend_healthy() {
    echo -e "${GREEN}Waiting for the app to become healthy...${NC}"
    for _ in $(seq 1 60); do
        if curl -fsS "$HEALTH_URL" 2>/dev/null | grep -q '"status"'; then
            echo -e "${GREEN}App is healthy: ${HEALTH_URL}${NC}"
            return 0
        fi
        sleep 2
    done
    echo -e "${RED}App did not become healthy within 120s. Check: ${DOCKER_COMPOSE_CMD[*]} ${COMPOSE_ENV_ARGS[*]} logs app${NC}" >&2
    return 1
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
