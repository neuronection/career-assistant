# Contributing

Thanks for your interest in improving **Career Assistant**. This document
covers the minimum you need to build, test and submit changes.

## Development setup

Prerequisites: Docker (for `--web` dev and pytest), Python 3.12+, Node 26+.

```bash
cp .env.example .env                                       # localhost defaults
./scripts/run-dev.sh                                       # desktop dev: SQLite profile, backend :8100 + frontend :3100
./scripts/run-dev.sh --web                                 # server dev: Postgres :5433 + login UI (starts the dev-db)
./scripts/seed.sh                                          # idempotent starter catalog (web mode / Postgres)
```

Desktop dev (the default) needs no Docker: `run-dev.sh`
bootstraps the local SQLite profile via `python -m careerassistant seed`
(migrations + idempotent catalog) before starting the honcho group.

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

The backend pytest env file is not tracked: the first
`./scripts/run-tests.sh` run self-bootstraps `backend/.env.test` from the
tracked `backend/.env.test.example`; on a fresh clone, a direct `pytest`
needs that one copy made first.

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

The manual lives in [`docs/`](docs/README.md) — split into a
[user guide](docs/user/README.md) and a
[developer guide](docs/dev/README.md), with navigation described by
[`docs/docs-tree.json`](docs/docs-tree.json). Update the matching page in the
same commit as your change.

- [Architecture](docs/dev/architecture.md) — modes, runtime topology, registries,
  AI pipeline. Keep it truthful when architecture changes.
- [Development workflow](docs/dev/development.md) — setup, conventions, git
  worktrees and the verification gates.
- [Deployment](docs/dev/deployment.md) — compose stacks, nginx/TLS, upgrades,
  backups. Changes under `docker/` or the ops scripts must update it.

## Repository layout

```
backend/    FastAPI app (app/), alembic/, tests/ (pytest, uses neuronection_career_test DB)
frontend/   React 18 + Vite + TypeScript SPA (src/)
docker/     compose taxonomy: dev-db, prod, standalone (nginx); Dockerfile; nginx confs
packaging/  PyInstaller spec + deb/AppImage build scripts (Windows exe via CI)
scripts/    run-dev.sh, run-docker.sh, update-docker.sh, check-changelog.sh,
            run-tests.sh, seed.sh, sync-dev-lib.sh (family dev lib: scripts/lib/)
```

## Submitting

1. Fork / branch from `main`.
2. Keep PRs focused — one feature or fix each.
3. Include tests for behavior changes (backend pytest, frontend vitest).
4. Update `CHANGELOG.md` if the change is user-visible (CI checks this).
5. Open the PR against `main` and make sure CI is green.

### Commit identity and release-cut hygiene

The `main` branch is protected by the **main protection** ruleset
(`gh api repos/neuronection/career-assistant/rules/branches/main`). Two
lessons from release cuts — keep both in mind:

- **Commit with an email tied to the GitHub account.** Use
  `50883154+constLiakos@users.noreply.github.com` (the repo's configured
  `git config user.email`) so every commit stays attributed to the PR
  author; GitHub attributes a commit when its author/committer email maps
  to the author's account. Commit attribution is what keeps
  branch-protection "unattributed changes" machinery from adding surprise
  review demands to a PR. On 2026-11-20 the ruleset's *require an
  additional approval for unattributed changes* flag (a GitHub-injected
  default, never chosen here) was set to `false` — this is a solo-maintainer
  repo and release bumps are local commits, so no extra approval can ever
  be satisfiable; if a merge is still refused while every required check is
  green and no review is requested, inspect `mergeStateStatus` and the
  required checks on the *latest* head SHA before reaching for `--admin`.
- **Bump commits stage explicit paths, never `git add -A`.** A release
  bump is `git add VERSION` (or the exact files the bump touches) plus the
  changelog paths — a blanket add once shipped local runtime uploads to
  the public repo on 2026-11-20 (that branch was deleted unmerged and the
  clean bump re-landed as PR #24).

## Security issues

Do not report vulnerabilities through public issues — see
[SECURITY.md](SECURITY.md).
