#!/bin/bash

# Career Assistant — Docker deploy script (standalone self-hosted stack).
#
# Builds the app image and brings up docker/docker-compose.standalone.yml
# (app + Postgres + nginx). This is the first-time deploy; to refresh an
# existing install use scripts/update-docker.sh.
#
# Usage:
#   ./scripts/run-docker.sh              # build + up + wait for healthy
#   ./scripts/run-docker.sh -h|--help    # print this help and exit
#
# Run from the Career Assistant project root. Requires docker/.env
# (cp docker/.env.production.example docker/.env and edit secrets).

print_help() {
  sed -n '3,14p' "$0" | sed 's/^# \{0,1\}//'
  exit 0
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib-docker.sh"

while [[ "$#" -gt 0 ]]; do
    case "$1" in
        -h|--help) print_help ;;
        *) die "Unknown parameter: $1 (try --help)" ;;
    esac
done

check_cwd
check_docker
require_env

# One-time ADR-0022 DB/role rename (career_* → neuronection_*), before the
# stack boots against the new names. No-op on fresh installs.
migrate_legacy_db_names

echo -e "${GREEN}Building and launching the Career Assistant stack...${NC}"
run_compose up --build -d

wait_for_backend_healthy || exit 1

echo -e "${GREEN}Career Assistant is up: ${HEALTH_URL}${NC}"
