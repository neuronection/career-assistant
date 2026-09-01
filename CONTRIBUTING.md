# Contributing

Thanks for your interest in improving **Career Assistant**. This document
covers the minimum you need to build, test and submit changes.

## Development setup

Prerequisites: Docker, Python 3.12+, Node 18+.

```bash
cp .env.example .env                                       # localhost defaults
docker compose -f docker/docker-compose.dev-db.yml up -d   # Postgres :5433 + Redis :6380
./scripts/run-dev.sh                                       # creates backend/venv, backend :8100 + frontend :3100
./scripts/seed.sh                                          # idempotent starter catalog
```

The first `run-dev.sh` run installs all backend dependencies into
`backend/venv`; frontend dependencies install with `npm ci` inside
`frontend/`.

## Before you open a PR

All of these must pass locally (CI runs the same steps):

```bash
cd backend && ./venv/bin/pytest tests/          # needs the dev DB containers up
cd backend && ./venv/bin/ruff check app tests && ./venv/bin/ruff format --check app tests
cd frontend && npm run build && npm run test -- --run
cd frontend && npm run lint
```

## Project conventions

These are enforced in review — they are what keeps the codebase coherent:

- **Structured over plain text.** AI outputs must be pydantic-validated into
  typed JSONB shapes (`app/ai/schemas.py`), never free-form strings. All AI
  calls go through `app.ai.provider.ainvoke_structured`, which writes an
  audit row to `ai_generations`.
- **Reference the taxonomy by stable `key` slugs**, never by display labels.
  Labels change; slugs don't.
- **AI configuration lives in the database** (Settings → AI Configuration).
  Never add `AI_*` environment variables.
- **JSONB mutations** need `flag_modified(obj, "field")` before commit.
- **Secrets** never go into env files, code, or logs. AI API keys belong in
  the encrypted DB column via `app/core/encryption.py`.
- **No code comments** unless they explain a non-obvious decision; public
  APIs get Google-style docstrings.
- **Migrations**: schema changes require an Alembic revision
  (`alembic revision --autogenerate`), reviewed by hand.
- **Changelog**: user-visible changes add an entry under `## [Unreleased]`
  in `CHANGELOG.md`. CI enforces this on PRs (`scripts/check-changelog.sh`).

## Docs pointers

- [Architecture](docs/ARCHITECTURE.md) — modes, runtime topology, registries,
  AI pipeline. Keep it truthful when architecture changes.
- [Deployment](docs/deploy.md) — compose stacks, nginx/TLS, upgrades,
  backups. Changes under `docker/` or the ops scripts must update it.
- Family standards (deployment, packaging, testing, security) live in the
  sibling `dev/` repo: `../dev/guidelines/`.

## Repository layout

```
backend/    FastAPI app (app/), alembic/, tests/ (pytest, uses career_test DB)
frontend/   React 18 + Vite + TypeScript SPA (src/)
docker/     compose taxonomy: dev-db, prod, standalone (nginx); Dockerfile; nginx confs
packaging/  PyInstaller spec + deb/AppImage build scripts (Windows exe via CI)
scripts/    run-dev.sh, run-docker.sh, update-docker.sh, check-changelog.sh,
            run-tests.sh, seed.sh, sync-dev-lib.sh (family dev lib: scripts/lib/)
```

Note: `dev/plans/` is local-only (gitignored) — planning material, not
public docs; link tracked docs from the README, never plan files.

## Submitting

1. Fork / branch from `main`.
2. Keep PRs focused — one feature or fix each.
3. Include tests for behavior changes (backend pytest, frontend vitest).
4. Update `CHANGELOG.md` if the change is user-visible (CI checks this).
5. Open the PR against `main` and make sure CI is green.

## Security issues

Do not report vulnerabilities through public issues — see
[SECURITY.md](SECURITY.md).
