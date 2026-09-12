#!/bin/bash
# Career Assistant — concurrent agent session manager (git worktrees).
#
# One agent session = one worktree = one branch = one dev-db compose
# project = one port block. Code is isolated by git; state is isolated
# by per-worktree ports + containers + volumes, so sessions never mix
# DB status, never fight over ports, and never touch each other's
# venv/node_modules/uploads.
#
# Layout per worktree (created next to the primary checkout):
#   ../career-assistant-<name>/
#     .env.wt.local      # port/DB overrides for scripts (gitignored)
#     .env               # app config: own DATABASE_URL/ports (gitignored)
#     backend/venv       # own venv
#     frontend/node_modules
#     docker compose project `career-<name>`: postgres :<db-port>,
#                        redis :<redis-port>, own volumes
#
# Usage:
#   ./scripts/worktree.sh create <name> [--from <branch>]
#   ./scripts/worktree.sh list
#   ./scripts/worktree.sh remove <name> [--keep-branch]
#   ./scripts/worktree.sh merge-back <name>   # ff-only into the primary checkout
#   ./scripts/worktree.sh -h | --help
#
# Inside a worktree, the ordinary scripts are worktree-aware:
#   ./scripts/run-dev.sh      # serves :<backend-port> / :<frontend-port>
#   ./scripts/run-tests.sh    # pytest against the worktree's career_test
#   ./scripts/reset-test-db.sh
#   ./scripts/run-e2e.sh
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_PATH="$SCRIPT_DIR/$(basename "${BASH_SOURCE[0]}")"
cd "$SCRIPT_DIR/.."
# shellcheck source=lib/dev-common.sh
source scripts/lib/dev-common.sh

PRIMARY_ROOT="$(git rev-parse --show-toplevel)"
PRIMARY_NAME="$(basename "$PRIMARY_ROOT")"
WT_DIR="$(dirname "$PRIMARY_ROOT")/$PRIMARY_NAME-<name>"

# Port ranges: worktrees use <base> + offset (offset 0 = primary).
BACKEND_BASE=8100
FRONTEND_BASE=3100
DB_BASE=5433
REDIS_BASE=6380
MAX_OFFSET=500

wt_die() { dc_die "$@"; }
wt_ok() { dc_ok "$@"; }

wt_slug() {
  echo "$1" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9-]/-/g; s/-\{2,\}/-/g; s/^-//; s/-$//'
}

wt_env_file() {
  local root="$1"
  echo "$root/.env.wt.local"
}

# wt_offset_for NAME — deterministic starting offset from the name hash.
wt_offset_for() {
  local name="$1" hash
  hash=$(printf '%s' "$name" | cksum | cut -d' ' -f1)
  echo $(( (hash % MAX_OFFSET) + 1 ))
}

# wt_offset_taken OFFSET — true if a sibling worktree already uses OFFSET.
wt_offset_taken() {
  local offset="$1" dir f
  for f in "$(dirname "$PRIMARY_ROOT")"/$PRIMARY_NAME-*/.env.wt.local; do
    [[ -f "$f" ]] || continue
    dir=$(sed -n 's/^WT_DIR=//p' "$f" 2>/dev/null || true)
    [[ "$dir" == *"-$(printf '%04d' "$offset")" || "$dir" == *"@${offset}" ]] && return 0
  done
  return 1
}

# wt_pick_offset NAME — first offset whose 4 ports are free and unused
# by another worktree. Deterministic start, collision-safe bump.
wt_pick_offset() {
  local name="$1" offset candidate
  offset=$(wt_offset_for "$name")
  for (( candidate = offset; candidate <= MAX_OFFSET; candidate++ )); do
    if wt_offset_taken "$candidate"; then continue; fi
    if dc_port_in_use "$((BACKEND_BASE + candidate))" \
      || dc_port_in_use "$((FRONTEND_BASE + candidate))" \
      || dc_port_in_use "$((DB_BASE + candidate))" \
      || dc_port_in_use "$((REDIS_BASE + candidate))"; then
      continue
    fi
    echo "$candidate"
    return 0
  done
  wt_die "no free port offset found (scanned $offset..$MAX_OFFSET)"
}

wt_env_field() {
  local file="$1" key="$2"
  sed -n "s/^${key}=//p" "$file" | head -1
}

wt_summary() {
  local f="$1"
  printf '  %-40s backend %-6s frontend %-6s db %-6s redis %-6s\n' \
    "$(basename "$(dirname "$f")")" \
    "$(wt_env_field "$f" BACKEND_PORT)" \
    "$(wt_env_field "$f" FRONTEND_PORT)" \
    "$(wt_env_field "$f" POSTGRES_PORT)" \
    "$(wt_env_field "$f" REDIS_PORT)"
}

wt_bootstrap() {
  local root="$1"
  dc_step "bootstrapping backend venv"
  dc_ensure_venv "$root/backend/venv" "$root/backend/requirements.txt"
  dc_step "installing frontend dependencies"
  dc_ensure_node_deps "$root/frontend" npm
}

wt_start_db() {
  local root="$1"
  dc_step "starting worktree dev DB (own compose project, own ports)"
  (
    cd "$root"
    export COMPOSE_PROJECT_NAME POSTGRES_PORT POSTGRES_TEST_DB \
      POSTGRES_CONTAINER REDIS_CONTAINER
    docker compose -f docker/docker-compose.dev-db.yml up -d
  ) || wt_die "worktree dev DB failed to start"
  local i
  for i in $(seq 1 30); do
    if docker ps --filter "name=$POSTGRES_CONTAINER" --filter "health=healthy" \
      --format '{{.Names}}' | grep -q "$POSTGRES_CONTAINER"; then
      wt_ok "Worktree dev DB is healthy."
      return 0
    fi
    sleep 1
  done
  wt_die "worktree dev DB did not become healthy within 30s"
}

wt_migrate_test_db() {
  local root="$1"
  dc_step "applying migrations to the worktree test DB"
  (
    cd "$root/backend"
    export PATH="$root/backend/venv/bin:$PATH"
    DATABASE_URL="$DATABASE_URL_TEST" PYTHONPATH="$(pwd)" alembic upgrade head
  ) || wt_die "migration of worktree test DB failed"
  wt_ok "Worktree test DB is migrated."
}

wt_copy_local_config() {
  local root="$1"
  dc_step "copying local-only config (.opencode) into the worktree"
  if [[ -d "$PRIMARY_ROOT/.opencode" ]]; then
    rm -rf "$root/.opencode"
    cp -R "$PRIMARY_ROOT/.opencode" "$root/.opencode"
  fi
}

cmd_create() {
  local name="" from=""
  while [[ "$#" -gt 0 ]]; do
    case "$1" in
      --from) from="$2"; shift 2 ;;
      *) name="$1"; shift ;;
    esac
  done
  [[ -z "$name" ]] && wt_die "usage: worktree.sh create <name> [--from <branch>]"
  name=$(wt_slug "$name")
  [[ -z "$name" ]] && wt_die "name must contain [a-z0-9-] characters"
  local dir="$(dirname "$PRIMARY_ROOT")/$PRIMARY_NAME-$name"
  local branch="agent/$name"
  [[ -e "$dir" ]] && wt_die "$dir already exists"
  git show-ref --verify --quiet "refs/heads/$branch" \
    && wt_die "branch $branch already exists"

  local offset
  offset=$(wt_pick_offset "$name")
  local backend_port=$((BACKEND_BASE + offset))
  local frontend_port=$((FRONTEND_BASE + offset))
  local db_port=$((DB_BASE + offset))
  local redis_port=$((REDIS_BASE + offset))
  local project="career-$name"

  dc_step "creating worktree $dir (branch $branch)"
  git worktree add "$dir" -b "$branch" ${from:+"$from"} \
    || wt_die "git worktree add failed"

  local db_url="postgresql+asyncpg://career:career_dev_pw@127.0.0.1:${db_port}/career"
  local db_url_test="postgresql+asyncpg://career:career_dev_pw@127.0.0.1:${db_port}/career_test"

  dc_step "writing per-worktree env files"
  cat > "$dir/.env.wt.local" <<EOF
WT_NAME=$name
WT_DIR=$dir
COMPOSE_PROJECT_NAME=$project
POSTGRES_CONTAINER=$project-postgres
REDIS_CONTAINER=$project-redis
BACKEND_PORT=$backend_port
FRONTEND_PORT=$frontend_port
POSTGRES_PORT=$db_port
REDIS_PORT=$redis_port
DATABASE_URL=$db_url
DATABASE_URL_TEST=$db_url_test
EOF
  cat > "$dir/.env" <<EOF
APP_NAME=Career Assistant
APP_ENV=development
DEBUG=true
API_HOST=0.0.0.0
API_PORT=$backend_port
CORS_ORIGINS=http://localhost:$frontend_port,http://127.0.0.1:$frontend_port
DATABASE_URL=$db_url
REDIS_URL=redis://127.0.0.1:$redis_port/0
JWT_SECRET=dev-only-change-me-$name-0123456789abcdef
UPLOAD_DIR=uploads
RATE_LIMIT_ENABLED=true
EOF

  wt_copy_local_config "$dir"
  wt_bootstrap "$dir"
  POSTGRES_PORT="$db_port" POSTGRES_TEST_DB=career_test \
    POSTGRES_CONTAINER="$project-postgres" REDIS_CONTAINER="$project-redis" \
    COMPOSE_PROJECT_NAME="$project" wt_start_db "$dir"
  DATABASE_URL_TEST="$db_url_test" wt_migrate_test_db "$dir"

  wt_ok "Worktree ready:"
  wt_summary "$(wt_env_file "$dir")"
  dc_info "Start it:"
  dc_info "  cd $dir && ./scripts/run-dev.sh"
  dc_info "Run tests inside it (isolated career_test on :$db_port):"
  dc_info "  cd $dir && ./scripts/run-tests.sh"
  dc_info "Open a separate agent session:"
  dc_info "  cd $dir && opencode"
}

cmd_list() {
  local f
  for f in "$(dirname "$PRIMARY_ROOT")"/$PRIMARY_NAME-*/.env.wt.local; do
    [[ -f "$f" ]] || continue
    wt_summary "$f"
  done
  if ! compgen -G "$(dirname "$PRIMARY_ROOT")/$PRIMARY_NAME-*/.env.wt.local" >/dev/null; then
    dc_info "No agent worktrees."
  fi
}

cmd_remove() {
  local name="" keep_branch=0
  while [[ "$#" -gt 0 ]]; do
    case "$1" in
      --keep-branch) keep_branch=1; shift ;;
      *) name="$1"; shift ;;
    esac
  done
  [[ -z "$name" ]] && wt_die "usage: worktree.sh remove <name> [--keep-branch]"
  name=$(wt_slug "$name")
  local dir="$(dirname "$PRIMARY_ROOT")/$PRIMARY_NAME-$name"
  local project="career-$name"
  [[ -d "$dir" ]] || wt_die "no worktree at $dir"
  dc_step "stopping worktree dev DB ($project, removing volumes)"
  (
    cd "$dir"
    export COMPOSE_PROJECT_NAME="$project" \
      POSTGRES_CONTAINER="$project-postgres" REDIS_CONTAINER="$project-redis"
    docker compose -f docker/docker-compose.dev-db.yml down -v
  ) || dc_warn "compose down failed; continuing"
  dc_step "removing worktree"
  git worktree remove --force "$dir" || git worktree remove "$dir"
  if [[ "$keep_branch" -eq 0 ]]; then
    dc_step "deleting branch agent/$name"
    git branch -D "agent/$name" || dc_warn "branch agent/$name not found"
  fi
  wt_ok "Worktree $name removed."
}

cmd_merge_back() {
  local name
  name=$(wt_slug "${1:-}")
  [[ -z "$name" ]] && wt_die "usage: worktree.sh merge-back <name>"
  local branch="agent/$name"
  [[ -n "$(git status --porcelain)" ]] \
    && wt_die "primary checkout is dirty — commit or stash first"
  local head_branch
  head_branch="$(git branch --show-current)"
  dc_step "fast-forwarding $head_branch to $branch"
  git merge --ff-only "$branch" \
    || wt_die "not fast-forwardable — merge main INTO the worktree, re-run the gate, then retry"
  wt_ok "Merged. Clean up with: ./scripts/worktree.sh remove $name"
}

case "${1:-}" in
  create) shift; cmd_create "$@" ;;
  list) shift; cmd_list "$@" ;;
  remove) shift; cmd_remove "$@" ;;
  merge-back) shift; cmd_merge_back "$@" ;;
  -h|--help) dc_help "$SCRIPT_PATH" ;;
  *) dc_help "$SCRIPT_PATH" ;;
esac
