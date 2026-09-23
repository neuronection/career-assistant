# Development workflow

Local setup, the day-to-day loop, conventions and the verification gates.
The tracked [`AGENTS.md`](https://github.com/neuronection/career-assistant/blob/main/AGENTS.md) is the authoritative rule list —
this page is the working guide.

## Bootstrap

Prerequisites: Docker, Python 3.12+, Node 18+.

```bash
cp .env.example .env                                       # localhost defaults
docker compose -f docker/docker-compose.dev-db.yml up -d   # Postgres :5433 + Redis :6380
./scripts/run-dev.sh                                       # backend :8100 + frontend :3100
./scripts/seed.sh                                          # idempotent starter catalog
```

The first `run-dev.sh` run installs all backend dependencies into
`backend/venv`; frontend dependencies install with `npm ci` inside
`frontend/`. Open <http://localhost:3100>; interactive API docs are at
<http://localhost:8100/docs>.

Useful flags:

```bash
./scripts/run-dev.sh --mock-ai   # built-in mock AI provider (offline dev)
./scripts/run-dev.sh -h          # all flags
```

## The loop

| Task | Command |
|---|---|
| Backend tests | `./scripts/run-tests.sh` (or `cd backend && ./venv/bin/pytest tests -q -n auto`) |
| Backend lint | `cd backend && ./venv/bin/ruff check app tests && ./venv/bin/ruff format --check app tests` |
| Frontend build | `cd frontend && npm run build` |
| Frontend tests | `cd frontend && npm run test -- --run` |
| Frontend lint | `cd frontend && npm run lint` |
| E2E smoke | `./scripts/run-e2e.sh` |
| Seed catalog | `./scripts/seed.sh` |
| Changelog gate | `./scripts/check-changelog.sh` |

Everything above must pass locally before a PR — CI runs the same steps.
Never commit untested code.

## Conventions that matter

- **Structured over plain text.** AI outputs must be pydantic-validated into
  typed JSONB shapes (`app/ai/schemas.py`), never free-form strings.
- **Reference the taxonomy by stable `key` slugs**, never display labels.
- **AI configuration lives in the database** (Settings → AI Configuration).
  Never add `AI_*` environment variables.
- **JSONB mutations** need `flag_modified(obj, "field")` before commit.
- **Secrets** never go into env files, code or logs. AI keys belong in the
  encrypted DB column via `app/core/encryption.py`.
- **No code comments** unless they explain a non-obvious decision; public APIs
  get Google-style docstrings.
- **Migrations**: schema changes require an Alembic revision, reviewed by hand
  (see [migrations.md](migrations.md)).
- **Changelog**: user-visible changes add an entry under `## [Unreleased]` in
  `CHANGELOG.md` (CI-enforced).

## Concurrent sessions with git worktrees

The repo ships a worktree manager so several agent sessions can run at once
without fighting over ports, databases or `node_modules`:

```bash
./scripts/worktree.sh create <name> [--from <branch>]
./scripts/worktree.sh list
./scripts/worktree.sh remove <name> [--keep-branch]
./scripts/worktree.sh merge-back <name>   # ff-only into the primary checkout
```

One worktree = one branch = one dev-db compose project = one port block. The
ordinary scripts (`run-dev.sh`, `run-tests.sh`, `reset-test-db.sh`,
`run-e2e.sh`) are worktree-aware and use the worktree's own ports and
database. Merges are fast-forward only, so rebase/merge `main` before
`merge-back`.

## AI and scheduler in dev

- **Mock AI** is opt-in (`MOCK_AI=1`, or `./scripts/run-dev.sh --mock-ai`).
  With it off, dev AI stays unconfigured and AI endpoints answer `503`.
- **`.env.test` sets `SCHEDULER_ENABLED=false`** — the live loop never runs in
  tests. Drive it directly with `SchedulerService(db).tick()`.
- The gateway self-registers deterministic mock fixtures whenever a mock
  provider resolves (`ensure_mock_registry` in `app/ai/gateway.py`).

## Repo layout

```
backend/    FastAPI app (app/), alembic/, tests/ (pytest), venv/
frontend/   React 18 + Vite + TypeScript SPA (src/)
docker/     compose taxonomy: dev-db, prod, standalone (nginx); Dockerfile; nginx confs
packaging/  PyInstaller spec + deb/AppImage build scripts (Windows exe via CI)
scripts/    run-dev.sh, run-tests.sh, run-docker.sh, update-docker.sh, seed.sh,
            worktree.sh, check-changelog.sh, check-ai-alignment.sh, lib/
assets/     canonical brand assets
docs/       this manual (user/ + dev/)
```

## Related

- [Testing](testing.md)
- [Architecture](architecture.md)
- [Adding features](adding-features.md)
