# AGENTS.md — Career Assistant

**Career Assistant** — part of an assistant family: Health Assistant,
Course Assistant, Career Assistant.

Career-discovery platform for students: AI-generated/curated job catalog in a
family tree + relation graph, deep structured student profiles, university
PDF intake with admission baselines, AI + human job scoring, filtered
rankings, chatbot + contextual "Ask AI" buttons.

**Dual-mode product** (both first-class, both CI-covered): web/self-host
(Postgres + JSONB, Docker, `run-dev.sh`) and desktop (pywebview shell, SQLite
local profile, tray/background scheduler, `python -m careerassistant`, PyInstaller
packaging). Keep the schema dialect-aware (Postgres + SQLite verified) and
never break one mode while working on the other.

Stack mirrors the other Neuronection assistants: FastAPI (async SQLAlchemy +
Postgres JSONB + Alembic), React 18 + Vite + TS + Tailwind + Zustand,
pytest/vitest, ruff. Follow [CONTRIBUTING.md](CONTRIBUTING.md) and
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) before a task; the repo-local
`dev/` holds only scratch notes and is gitignored.

## Repo map
```
├── backend/    # FastAPI app (app/), alembic/, tests/, venv/
├── frontend/   # React SPA (src/)
├── docker/     # dev-db compose (:5433/:6380), prod + standalone (nginx) compose, Dockerfile, nginx confs
├── scripts/    # run-dev.sh, run-docker.sh, update-docker.sh, check-changelog.sh,
│               # run-tests.sh, seed.sh, sync-brand.sh, sync-dev-lib.sh, lib-docker.sh
│               # (shared bootstrap lib: scripts/lib/dev-common.sh)
├── assets/     # canonical brand assets (icon.svg, icon-light.svg)
└── dev/        # local-only scratch notes (gitignored)
```

## Shared UI library (assistant-ui)

`@neuronection/assistant-ui` is the **first-party shared UI library** of the
Neuronection assistants (published on npm), shared with study- and
health-assistant. Core rules:

- **Check the library first for NEW UI** — no new local copies of things
  the library already ships — the app is fully adopted: `components/ui/*`
  are library re-export shims and the drift audit is clean. Never
  reintroduce a local implementation; extend the library instead.
- First-party means mutable: if the API doesn't fit, change the library
  (two-app rule: a library change must build green in at least two family
  apps — the library's `scripts/verify-in-app.mjs` checks it in-app),
  never fork or wrap it.
- Styling via `--as-*` tokens / `data-as-*` only; this app's identity
  overrides live in its `theme.css` once wired.
- **App UI conventions: read `docs/ui-conventions.md` before building or
  restyling any page** — full-bleed workspace pattern, shared
  `formPrimitives` controls, card pickers, motion system, drag feedback
  and the preview/testability contracts that keep every surface looking
  like one product (CV Studio is the reference implementation).

## Build & test
```bash
docker compose -f docker/docker-compose.dev-db.yml up -d   # once
./scripts/run-dev.sh                                       # backend :8100 + frontend :3100
cd backend && ./venv/bin/pytest tests/                     # tests (uses career_test DB)
cd backend && ./venv/bin/ruff check app tests && ./venv/bin/ruff format --check app tests
cd frontend && npm run build && npm run test -- --run
```

Migrations: alembic revision ids are plain sequential (`0001`…; file
names add a slug). `env.py` reads `settings.DATABASE_URL`, so applying
to the test DB needs an explicit override:
`DATABASE_URL="postgresql+asyncpg://career:career_dev_pw@127.0.0.1:5433/career_test" ./venv/bin/alembic upgrade head`
(an `upgrade head` on an already-migrated DB is a silent no-op — after
regenerating a baseline, drop+recreate instead).

## Conventions
- **Structured over plain text**: AI outputs are pydantic-validated into
  typed JSONB shapes; reference taxonomy by stable `key` slugs, never labels.
- **No comments unless requested**; Google-style docstrings on public APIs.
- JSONB mutations need `flag_modified(obj, "field")` before commit.
- AI calls always go through `app.ai.gateway.ainvoke_structured` (audited in
  `ai_generations`). AI config is DB-only via Settings → AI Configuration —
  never add AI_* env vars. The mock provider is dev/test-only and is
  auto-provisioned there; production starts unconfigured (503 until an admin
  configures a provider).
- **Extension points are registries**: posting sources only via the
  connector SDK (`app/connectors/`, entry-point group
  `career_assistant.connectors`, admin allowlist for plugins); periodic
  work only via the scheduler (`app/services/scheduler/`, triggers via
  `career_assistant.scheduler_triggers`) — the scheduler decides WHEN and
  only enqueues jobs; notifications always emit through
  `NotificationService.emit` (single funnel; replaces storage,
  keeps the funnel).
- `SCHEDULER_ENABLED=false` in `.env.test` — the live loop never runs in
  tests; drive `SchedulerService(db).tick()` directly.
- Optional server PDF engine: `requirements-pdf.txt` +
  `playwright install chromium` — without it, CV PDF export answers 503
  and the frontend falls back to the print view (capability detection,
  never a hard dependency).
- Update `CHANGELOG.md` under `## [Unreleased]` for user-visible changes
  (CI-enforced on PRs via `scripts/check-changelog.sh`).
- Always test before commit: backend pytest + ruff, frontend build + vitest.
- Never push to a remote unless explicitly asked.
