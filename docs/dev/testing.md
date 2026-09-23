# Testing

Career Assistant is covered by backend **pytest** (async, httpx) and frontend
**vitest** (testing-library). The suite is the gate: run it before every
commit.

## Backend

```bash
cd backend && ./venv/bin/pytest tests -q -n auto     # parallel (default)
./scripts/run-tests.sh                               # same, via the wrapper
```

`.env.test` (loaded by the test config) pins the test environment:

```
APP_ENV=test
DATABASE_URL=...career_test
RATE_LIMIT_ENABLED=false
SCHEDULER_ENABLED=false
BCRYPT_ROUNDS=4
AI_RATE_LIMIT=0
MOCK_AI=1
```

Key points:

- **The scheduler loop never runs in tests.** `SCHEDULER_ENABLED=false`; drive
  it directly with `SchedulerService(db).tick()`.
- **Mock AI is on** (`MOCK_AI=1`), so AI-dependent tests are deterministic and
  offline. The gateway self-registers mock fixtures when a mock provider
  resolves.
- **Rate limiting is off** and bcrypt rounds are reduced for speed.

### Parallel databases (pytest-xdist)

Parallel runs are the default. Each worker gets its **own** database —
`career_test_gw0`, `career_test_gw1`, … — created and migrated automatically
by `tests/xdist_routing.py` **before** the app's engines exist. This removes
cross-worker contention (single-user tests all insert the same default user)
and makes the real-Alembic migration tests safe to distribute.

- Never hand-run migrations for an `-n` run; the routing bootstrap does it.
- **SQLite workers** (the desktop profile) write isolated files under
  `backend/tests/_xdist/<worker>/` (gitignored). The CI SQLite job stays
  **serial** on one file by design.
- `PYTEST_XDIST_WORKERS=N` overrides the worker count; `PYTEST_XDIST=0` opts
  out and uses the plain `career_test` database (which needs its one-shot
  `alembic upgrade head`).

```bash
cd backend && PYTEST_XDIST=0 ./venv/bin/pytest tests -q   # serial
cd backend && PYTEST_XDIST_WORKERS=4 ./venv/bin/pytest tests -q
```

### Writing backend tests

- Use the async fixtures in `tests/conftest.py`; every test runs inside a
  transaction that is rolled back, so tests are isolated.
- There are 100+ test modules, one per area (`test_cv_*`, `test_chat_*`,
  `test_ai_*`, `test_postings.py`, `test_migrations.py`, …) — put a new test
  in the module matching its area, or add one if the area is new.
- **Migration tests must cover both dialects.** Any migration touching JSONB
  or ids needs a Postgres and a SQLite case (see
  [migrations.md](migrations.md)).

## Frontend

```bash
cd frontend && npm run test -- --run   # vitest, single run
cd frontend && npm run lint            # eslint
cd frontend && npm run build           # tsc + vite build (typecheck)
```

- Tests live in `frontend/src/tests/` (one per surface/store) plus
  co-located `*.test.ts(x)` files.
- **Patch state through the API mocks, and make the mock honour the last
  write.** A component test that patches a CV via a static mock resurrects
  stale state and looks like an app bug — make the preview mock reflect the
  last `patchCv`/`setContext` call, like the real backend.
- **jsdom has no drag images**: guard `event.dataTransfer?.setDragImage` in
  DnD handlers.
- The `assistant-ui` library is fully adopted; UI tests exercise the library
  components through this app's surfaces. See
  [ui-conventions.md](ui-conventions.md) and the `ca-assistant-ui` skill.

## E2E smoke

`./scripts/run-e2e.sh` runs the smoke suite. It sets `MOCK_AI=1` and
`AI_RATE_LIMIT=0` (the gateway's per-user AI limiter is keyed on that value,
not `RATE_LIMIT_ENABLED`).

## What to run before a PR

All of these must pass:

```bash
cd backend && ./venv/bin/pytest tests -q -n auto
cd backend && ./venv/bin/ruff check app tests && ./venv/bin/ruff format --check app tests
cd frontend && npm run build && npm run test -- --run
cd frontend && npm run lint
./scripts/check-changelog.sh
```

## Related

- [Development workflow](development.md)
- [Migrations](migrations.md)
- [UI conventions](ui-conventions.md)
