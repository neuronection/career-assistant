# Testing

Career Assistant is covered by backend **pytest** (async, httpx) and frontend
**vitest** (testing-library). The suite is the gate: run it before every
commit.

## Backend

```bash
cd backend && uv run pytest tests -q -n auto     # parallel (default)
./scripts/run-tests.sh                               # same, via the wrapper
```

`.env.test` (loaded by the test config) pins the test environment:

```
CAREER_APP_ENV=test
CAREER_DATABASE_URL=...neuronection_career_test
CAREER_RATELIMIT_ENABLED=false
CAREER_SCHEDULER_ENABLED=false
BCRYPT_ROUNDS=4
CAREER_RATELIMIT_AI=0
CAREER_MOCK_AI=1
```

Key points:

- **The scheduler loop never runs in tests.** `CAREER_SCHEDULER_ENABLED=false`; drive
  it directly with `SchedulerService(db).tick()`.
- **Mock AI is on** (`CAREER_MOCK_AI=1`), so AI-dependent tests are deterministic and
  offline. The gateway self-registers mock fixtures when a mock provider
  resolves.
- **Rate limiting is off** (`CAREER_RATELIMIT_ENABLED=false`; the auth-kit's own
  auth limits are reset per test). Passwords hash at the family bcrypt
  floor (12 rounds — the kit enforces it).
- **Auth sessions are real kit sessions**: `tests/conftest.py` mints
  cookie + CSRF + bearer headers (`auth_headers`, `register_user`,
  `session_headers`) through the installed kit; identity rows live in the
  kit's committed store and are wiped per test (`clean_identity`), while
  domain data rides the per-test transaction rollback (`clean_db`).

### Parallel databases (pytest-xdist)

Parallel runs are the default. Each worker gets its **own** database —
`neuronection_career_test_gw0`, `neuronection_career_test_gw1`, … — created and migrated automatically
by `tests/xdist_routing.py` **before** the app's engines exist. This removes
cross-worker contention and makes the real-Alembic migration tests safe to
distribute.

- Never hand-run migrations for an `-n` run; the routing bootstrap does it.
- **SQLite workers** (the desktop profile) write isolated files under
  `backend/tests/_xdist/<worker>/` (gitignored). The CI SQLite job stays
  **serial** on one file by design.
- `PYTEST_XDIST_WORKERS=N` overrides the worker count; `PYTEST_XDIST=0` opts
  out and uses the plain `neuronection_career_test` database (which needs its one-shot
  `alembic upgrade head`).

```bash
cd backend && PYTEST_XDIST=0 uv run pytest tests -q   # serial
cd backend && PYTEST_XDIST_WORKERS=4 uv run pytest tests -q
```

### Writing backend tests

- Use the async fixtures in `tests/conftest.py`; every test runs inside a
  transaction that is rolled back, so tests are isolated.
- After an API call writes through its own session, the test session's
  cached rows are stale (`expire_on_commit=False`) — re-read with
  `populate_existing=True` / `db.expire_all()` (see `_rows` in
  `tests/test_skill_relations_admin.py`).
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
- **Unmocked API calls fail fast** (`src/tests/setup.ts` installs an axios
  adapter that throws): a missing mock is a loud `unmocked API call` error
  instead of a hanging promise that stalls the whole test. Mock what the
  surface fetches (the CV Studio harness is the reference).
- **Accessibility is asserted, not assumed**: `src/tests/a11y.test.tsx` runs
  axe over the shared shells (Layout, the settings shell, the shared form
  primitives) via `expectNoA11yViolations` in `src/tests/a11y.ts`.
  `color-contrast` is skipped (jsdom has no layout engine); every
  name/role/label/aria rule runs for real. New shells and form surfaces add
  a case there.
- **Surface test files stay readable**: the old 3,000-line
  `cvStudio.test.tsx` is split by surface — `cvStudio`, `cvBuilder`,
  `cvBuilderDesign`, `cvBuilderSynth`, `cvBuilderBullets` and
  `cvTemplateEditor` — over one shared `cvStudioHarness.tsx` (mocks +
  fixtures + `resetCvStudioMocks`). Import the harness FIRST: its `vi.mock`
  calls must register before the component modules load.
- The `assistant-ui` library is fully adopted; UI tests exercise the library
  components through this app's surfaces. See
  [ui-conventions.md](ui-conventions.md) and the `ca-assistant-ui` skill.

## E2E smoke

`./scripts/run-e2e.sh` runs the smoke suite. It sets `CAREER_MOCK_AI=1` and
`CAREER_RATELIMIT_AI=0` (the gateway's per-user AI limiter is keyed on that value,
not `CAREER_RATELIMIT_ENABLED`).

The suite covers the product loops end-to-end over the mock provider: chat
(docked + bubble), CV Studio (create, generate, cover letters), synth
bullets/references, profile HITL, extensions, AI settings/first run, and —
since plan 124 — Autopilot (`test_autopilot.py`), interview practice
(`test_interviews.py`), universities intake review (`test_universities.py`),
onboarding start paths (`test_onboarding_paths.py`) and CV PDF export
(`test_cv_pdf_export.py`).

- **Posting-grounded specs** use `e2e/seed_posting.py` (`E2E00001`, seeded
  by the runner) — never hand-seed a posting per spec.
- **Mock AI carrier** comes from `e2e/seed_ai.py`; a spec that needs the
  unconfigured state goes through `test_ai_first_run.py::_unconfigure`.
- **Optional engines skip, never fail**: `test_cv_pdf_export.py` probes
  `GET /cv/{id}/preview.png` and skips on `503` (no server PDF engine). The
  capability is detected, not assumed.
- **Start-path order independence**: `test_onboarding_paths.py` resets the
  stored path through `PUT /me/onboarding-path` before asserting the picker
  (a stored `target` path redirects straight to the express intake).
- The scratch workspace reset covers CVs, synth variants, chat sessions,
  experience rows, pending proposals, autopilot goals and documents — a new
  spec that creates a deletable artifact should add its collection to
  `_COLLECTIONS` in `e2e/conftest.py`.

## Quality gates (CI)

Every gate blocks, and every ratchet only tightens (plan 124). A gate that
can fail silently — `continue-on-error`, cron-only, "advisory" — is not a
gate. The numbers live next to the gate: coverage floors in `ci.yml` +
`frontend/vitest.config.ts`, type pegs in `backend/pyproject.toml`
(`[tool.career-mypy-ratchet]`), dependency exceptions in
`security/dependency-audit-allowlist.json`, intentional skips in
`backend/tests/skip_allowlist.json`.

| Gate | Command | Wall |
|---|---|---|
| Backend (Postgres) | `uv run pytest tests -n auto --cov=app --cov-fail-under=79` | coverage 79% |
| Backend (SQLite profile) | same, with `CAREER_DATABASE_URL=sqlite+aiosqlite:///./neuronection_career_test.db` (serial) | coverage 79% |
| Contract (both dialects) | `uv run pytest -m contract` | identity-auth §18 |
| Types | `uv run mypy` | `[tool.mypy] files` — clean packages only |
| Type ratchet | `uv run python ../scripts/check-mypy-ratchet.py` | `[tool.career-mypy-ratchet]` pegs |
| Frontend | `npm run test -- --run --coverage` | thresholds in `vitest.config.ts` |
| assistant-ui drift | `node scripts/audit-assistant-ui-usage.mjs ./frontend/src` | zero local copies of library components |
| Dependency audit | `python scripts/check-dependency-audit.py` | reviewed exceptions only |
| Skip list | enforced by `tests/conftest.py` at session end | `tests/skip_allowlist.json` |
| i18n catalogs | `python3 scripts/translations/check_translations.py` | `de`/`el` complete; reverse lint + key audit in vitest |

**Up-only.** A coverage floor rises to the measured value; a type peg falls
to the measured value. When your change improves a number, move the pin in
the same commit: the ratchet gate fails on a stale pin too (an
out-of-date pin silently tolerates new debt).

**Drift audit.** `scripts/audit-assistant-ui-usage.mjs` is a byte-identical
vendored copy of the assistant-ui canonical (`audit-usage.mjs`). The
`quality-gates` CI job runs it on every PR; the weekly
`drift-audit.yml` workflow additionally compares the vendored copy with
upstream and opens a `tech-debt` issue when the library's script changed.
Never edit the vendored copy — re-vendor it.

### Dependency-audit exceptions

`pip-audit` (backend) and `npm audit --audit-level=high` (frontend) block the
build. Accepting a finding is an explicit, time-boxed review:

1. Confirm the current dependency range has no fixed release (`npm audit
   --json`, `pip-audit --format json`) — fix and lock instead of waiving.
2. Add an entry to `security/dependency-audit-allowlist.json`:
   - `pip` / `npm`: `id` (CVE or GHSA), `package`, `reason` (why it is not
     reachable / what blocks the fix), `reviewed` (today), `expires`
     (≤ 90 days out).
   - `pipUnresolved`: packages auditors cannot resolve (workspace roots,
     git-sourced family kits) — `package` + `reason` only.
3. The review rides the same PR as the dependency state that needs it; a
   second reviewer checks the reachability claim.
4. Re-run `python scripts/check-dependency-audit.py --self-test` (policy
   cases) and the ecosystem command.

Expired exceptions and exceptions that no longer match a reported advisory
both fail the gate, so the file cannot rot into a permanent waiver list.

### Intentional skips

The suite must not shrink silently. Every skip carries a reason string, and
`tests/conftest.py` compares the observed skips with
`tests/skip_allowlist.json` at the end of the session:

- an **unlisted** skip fails the suite, in any run;
- an allowlisted `when: always` skip that did **not** fire fails a
  full-suite run (delete the entry or fix the condition);
- entries are dialect-scoped (the Postgres and SQLite lanes prove different
  contracts).

## What to run before a PR

All of these must pass:

```bash
cd backend && uv run pytest tests -q -n auto --cov=app --cov-fail-under=79
cd backend && uv run ruff check . && uv run ruff format --check .
cd backend && uv run mypy
cd backend && uv run python ../scripts/check-mypy-ratchet.py
cd frontend && npm run build && npm run test -- --run --coverage
cd frontend && npm run lint
node scripts/audit-assistant-ui-usage.mjs ./frontend/src
python scripts/check-dependency-audit.py
./scripts/check-changelog.sh
```

## Related

- [Development workflow](development.md)
- [Migrations](migrations.md)
- [UI conventions](ui-conventions.md)
