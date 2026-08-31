# AGENTS.md — Career Assistant

**Career Assistant** — part of an assistant family: Health Assistant,
Course Assistant, Career Assistant.

Career-discovery platform for students: AI-generated/curated job catalog in a
family tree + relation graph, deep structured student profiles, university
PDF intake with admission baselines, AI + human job scoring, filtered
rankings, chatbot + contextual "Ask AI" buttons.

Stack mirrors Health-Assistant/core: FastAPI (async SQLAlchemy + Postgres
JSONB + Alembic), React 18 + Vite + TS + Tailwind + Zustand, pytest/vitest,
ruff. Plans live in `dev/plans/` (local-only: `dev/` is gitignored — read
the matching phase plan before a task, and never let branch switches rely
on tracked plan files).

## Repo map
```
├── backend/    # FastAPI app (app/), alembic/, tests/, venv/
├── frontend/   # React SPA (src/)
├── docker/     # dev-db compose (postgres :5433 + redis :6380)
├── scripts/    # run-dev.sh, run-tests.sh, seed.sh, sync-brand.sh
├── assets/     # canonical brand assets (icon.svg, icon-light.svg)
└── dev/plans/  # phase plans (local-only, gitignored)
```

## Shared UI library (assistant-ui)

`@neuronection/assistant-ui` is **our first-party family library** (repo +
local sibling `../assistant-ui`), shared with study- and health-assistant
— see the `ca-assistant-ui` skill before creating UI components. Core
rules:

- **Check the library first for NEW UI** — no new local copies of things
  the family already ships — the app is fully adopted: `components/ui/*`
  are library re-export shims and the drift audit is clean. Never
  reintroduce a local implementation; extend the library instead.
- First-party means mutable: if the API doesn't fit, change the library
  (two-app rule + `scripts/verify-in-app.mjs` — details in the skill),
  never fork or wrap it.
- Styling via `--as-*` tokens / `data-as-*` only; this app's identity
  overrides live in its `theme.css` once wired.

## Build & test
```bash
docker compose -f docker/docker-compose.dev-db.yml up -d   # once
./scripts/run-dev.sh                                       # backend :8100 + frontend :3100
cd backend && ./venv/bin/pytest tests/                     # tests (uses career_test DB)
cd backend && ./venv/bin/ruff check app tests && ./venv/bin/ruff format --check app tests
cd frontend && npm run build && npm run test -- --run
```

## Conventions
- **Structured over plain text**: AI outputs are pydantic-validated into
  typed JSONB shapes; reference taxonomy by stable `key` slugs, never labels.
- **No comments unless requested**; Google-style docstrings on public APIs.
- JSONB mutations need `flag_modified(obj, "field")` before commit.
- AI calls always go through `app.ai.provider.ainvoke_structured` (audited in
  `ai_generations`). AI config is DB-only via Settings → AI Configuration —
  never add AI_* env vars. The mock provider is dev/test-only and is
  auto-provisioned there; production starts unconfigured (503 until an admin
  configures a provider).
- **Extension points are registries**: posting sources only via the
  connector SDK (`app/connectors/`, entry-point group
  `career_assistant.connectors`, admin allowlist for plugins); periodic
  work only via the scheduler (`app/services/scheduler/`, triggers via
  `career_assistant.scheduler_triggers`) — the scheduler decides WHEN and
  only enqueues plan-12 jobs; notifications always emit through
  `EngagementService.emit` (single funnel; plan 36 replaces storage,
  keeps the funnel).
- `SCHEDULER_ENABLED=false` in `.env.test` — the live loop never runs in
  tests; drive `SchedulerService(db).tick()` directly.
- Update `CHANGELOG.md` under `## [Unreleased]` for user-visible changes.
- Always test before commit: backend pytest + ruff, frontend build + vitest.
- Never push to a remote unless explicitly asked.
