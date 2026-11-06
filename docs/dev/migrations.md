# Migrations

The ORM models are the single source of truth for the schema; Alembic
revisions bring existing databases to match. Career Assistant runs **one
linear chain on two dialects** — PostgreSQL (web) and SQLite (desktop) — so
every migration must be dialect-aware.

The shared family discipline is documented in the migration standard; this page is the
app-specific delta.

## Layout and ids

- `backend/alembic/` — `env.py` and `versions/`.
- Revision ids are **plain sequential**: `0001_baseline_schema.py` is the
  v0.17 baseline; new work chains `0002_…`, `0003_…`. File names add a slug
  (`0002_new_table.py`).
- `env.py` reads `settings.CAREER_DATABASE_URL`; `target_metadata` is
  `app.models.Base.metadata`, with a metadata `naming_convention` (use the
  **short** constraint name with `op.drop_constraint` /
  `op.create_check_constraint` — the convention renders the prefix; passing the
  rendered name double-prefixes and fails on a fresh DB).

## The rules

> **Alignment doctrine (plan 16):** pre-release databases are dev
> artifacts to recreate — destructive migrations are fine (document
> them), downgrades may be irreversible in spirit but must stay runnable
> for the round-trip tests, and no backwards-compatibility shims are
> written.

1. **Model first.** Edit the SQLAlchemy model exactly as the schema should
   look, then write the revision to match.
2. **One head, never two.** `down_revision` is the current head's id string.
   Two heads break `alembic upgrade head`.
3. **Never edit an applied revision** — add a new one.
4. **Downgrade is required.** A no-op `downgrade()` is a bug; add a
   round-trip test when the migration rewrites data.
5. **Empty-DB safe.** `upgrade head` runs on every app start and in CI, so a
   migration that fails on a fresh database fails everything. Verify against a
   fresh DB, not just an upgraded one.
6. **Data migrations** run inside `upgrade()` via `op.get_bind().execute(...)`.
7. **Mirrored enums need their CHECKs widened in the same commit.** Enum
   values mirrored in a DB CHECK (`ScheduleKind` / `BackgroundJobType`
   columns) require the constraint updated with the new member, or inserting
   the new kind 500s.

### Baseline squash (v0.17)

v0.16.0 → v0.17 is a declared **breaking release with no production users**.
The plan-113 `0001` plus the `0002`–`0100` chain were replaced by one
model-generated `0001_baseline_schema.py` (2026-11-06). The sanctioned
destructive-baseline exception applies (declared in the revision header):
`downgrade()` restores an **empty schema** by design, and the header says so.
Recreate dev/test databases (`alembic upgrade head` + seed) instead of
downgrading.

The baseline carries the only DATA the old chain wrote outside table
defaults — the company quality denylist (18 rows, formerly revision `0070`).
`tests/conftest.py` loads that list from the baseline by path so the seed and
its per-SQLite-test provisioning cannot drift.

## Dialect-aware migrations (the hard part)

`env.py` does **not** enable SQLite batch mode globally, and the two dialects
behave differently:

- Use `StructuredJSON` (`JSONB().with_variant(JSON(), "sqlite")`) for JSON
  columns — never a bare Postgres `JSONB` in a migration.
- SQLite has limited `ALTER TABLE`. Where Postgres accepts an `ALTER`, the
  migration must handle SQLite explicitly (batch/rebuild) and the reverse.
- **Match ids by normalized value, not by rendered text.** UUIDs render as
  dashed text on Postgres but are stored as hex on SQLite — a data migration
  that matches on `str(uuid)` silently misses SQLite rows.
- **Write per-dialect JSON.** A Postgres-only `CAST(... AS jsonb)` stores the
  wrong value on SQLite. Branch on `op.get_bind().dialect.name`.

The pre-baseline `0041` was the cautionary example: it fixed exactly these
three mistakes (Postgres-only JSON cast, dashed-UUID matching, and a
dangling-pin case) and was covered by four fold states on both dialects. Its
result is now folded into the baseline; the lesson stays.

## Migration notes (newest first)

- **`0001_baseline_schema`** (v0.17 no-BC squash): one model-generated
  baseline replaces the plan-113 `0001` and the whole `0002`–`0100` chain.
  The baseline seeds the company quality denylist (the old `0070`'s row set)
  and keeps the old chain's final CHECKs/indexes/server defaults as the
  models declare them. `downgrade()` is the sanctioned empty-schema restore;
  recreate dev/test databases. Verified by
  `tests/test_migrations.py::test_baseline_roundtrips_on_a_fresh_sqlite_database`
  and `test_baseline_matches_the_models` (both dialects in CI).

## Running migrations

Dev/test Postgres is on port 5433 (`docker/docker-compose.dev-db.yml`). The
test database needs an explicit URL override because `env.py` reads
`settings.CAREER_DATABASE_URL`:

```bash
cd backend
CAREER_DATABASE_URL="postgresql+asyncpg://neuronection_career_owner:career_dev_pw@127.0.0.1:5433/neuronection_career_test" \
  uv run alembic upgrade head
```

An `upgrade head` on an already-migrated database is a silent no-op — after
regenerating a baseline, **drop and recreate** instead.

- **Parallel test runs:** never hand-run migrations. Each xdist worker gets
  its own database (`neuronection_career_test_gw0`…) created and migrated automatically by
  `tests/xdist_routing.py` before the app engines exist.
- **Serial runs** use `neuronection_career_test` and need the one-shot `alembic upgrade
  head` above.
- The container runs `alembic upgrade head` on start (see
  [deployment.md](deployment.md)).

## Tests in the same commit

- New table/column behavior: API- or service-level tests.
- Data migration: a **legacy-data test** — seed the old shape on a lower
  revision, upgrade to head, assert the transform (both dialects).
- Downgrade round-trip when data is rewritten.
- **Bump the head-assertion test.** `backend/tests/test_migrations.py` asserts
  `get_heads() == ["0001"]`; every new revision must update that literal
  (and `test_autopilot.py`'s linear-chain check).

## Worktrees

Parallel branches both claim the next revision id. The second branch to finish
rebases onto the new head and **renumbers its revision** before committing
(see [development.md](development.md) and the repo development workflow).

## Docs in the same commit

Update [data-model.md](data-model.md) with the new table/column and add a
newest-first migration note. User-visible changes also update
`CHANGELOG.md`.

## Related

- [Data model](data-model.md)
- [Testing](testing.md)
- [Development workflow](development.md)
