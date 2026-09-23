# Migrations

The ORM models are the single source of truth for the schema; Alembic
revisions bring existing databases to match. Career Assistant runs **one
linear chain on two dialects** — PostgreSQL (web) and SQLite (desktop) — so
every migration must be dialect-aware.

The shared family discipline is the `family-migration` skill; this page is the
app-specific delta.

## Layout and ids

- `backend/alembic/` — `env.py` and `versions/`.
- Revision ids are **plain sequential**: `0001_…`, `0002_…`, up to the current
  head. File names add a slug (`0041_one_slot_synth_pins.py`).
- `env.py` reads `settings.DATABASE_URL`; `target_metadata` is
  `app.models.Base.metadata`, with a metadata `naming_convention` (use the
  **short** constraint name with `op.drop_constraint` /
  `op.create_check_constraint` — the convention renders the prefix; passing the
  rendered name double-prefixes and fails on a fresh DB).

## The rules

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

Migration `0041` is the cautionary example: it fixed exactly these three
mistakes (Postgres-only JSON cast, dashed-UUID matching, and a dangling-pin
case) and is covered by four fold states on both dialects.

## Running migrations

Dev/test Postgres is on port 5433 (`docker/docker-compose.dev-db.yml`). The
test database needs an explicit URL override because `env.py` reads
`settings.DATABASE_URL`:

```bash
cd backend
DATABASE_URL="postgresql+asyncpg://career:career_dev_pw@127.0.0.1:5433/career_test" \
  ./venv/bin/alembic upgrade head
```

An `upgrade head` on an already-migrated database is a silent no-op — after
regenerating a baseline, **drop and recreate** instead.

- **Parallel test runs:** never hand-run migrations. Each xdist worker gets
  its own database (`career_test_gw0`…) created and migrated automatically by
  `tests/xdist_routing.py` before the app engines exist.
- **Serial runs** use `career_test` and need the one-shot `alembic upgrade
  head` above.
- The container runs `alembic upgrade head` on start (see
  [deployment.md](deployment.md)).

## Tests in the same commit

- New table/column behavior: API- or service-level tests.
- Data migration: a **legacy-data test** — seed the old shape on a lower
  revision, upgrade to head, assert the transform (both dialects).
- Downgrade round-trip when data is rewritten.
- **Bump the head-assertion test.** `backend/tests/test_migrations.py` asserts
  `get_heads() == ["0041"]`; every new revision must update that literal.

## Worktrees

Parallel branches both claim the next revision id. The second branch to finish
rebases onto the new head and **renumbers its revision** before committing
(see [development.md](development.md) and the `family-dev` skill).

## Docs in the same commit

Update [data-model.md](data-model.md) with the new table/column and add a
newest-first migration note. User-visible changes also update
`CHANGELOG.md`.

## Related

- [Data model](data-model.md)
- [Testing](testing.md)
- [Development workflow](development.md)
