"""Migration round-trip discipline: the newest revision must downgrade
back to the previous shape and upgrade again on the suite's test DB."""

import asyncio
import contextlib
import os
import uuid
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
from alembic.config import Config

from alembic import command


@pytest.fixture(autouse=True)
def _restore_head_after_migration_test():
    """Data-migration tests run ON a pinned revision — the suite's schema
    must come back to head after each one (the identity fixtures wipe
    tables that only exist at head). The 0044 replay also drains the
    suite's COMMITTED sealed rows under a fake legacy key (the JWT_SECRET
    monkeypatch is active at the teardown upgrade) — clearing the VAPID
    pair's private key that the session warm-up provisioned — so the
    provisioning state is repaired here, committedly, before the next
    test reads it."""
    yield
    command.upgrade(_configured(), "head")

    async def _repair_vapid_provisioning():
        from app.services import webpush_service

        webpush_service._keys_cache = None
        with contextlib.suppress(Exception):
            await webpush_service.get_or_create_vapid_keys()

    asyncio.run(_repair_vapid_provisioning())


def _configured() -> Config:
    from app.core.config import settings

    os.environ["CAREER_DATABASE_URL"] = settings.database_url
    return Config("alembic.ini")


async def _ensure_fold_user(session, email: str) -> str:
    """A `users` row id for data-migration fixtures, via raw SQL.

    The ORM `User` model carries the 0042 identity columns and cannot
    map below that revision — migrations under test run on older shapes.
    """
    import uuid as _uuid
    from datetime import datetime

    from sqlalchemy import text

    row = (await session.execute(text("SELECT id FROM users LIMIT 1"))).first()
    if row is not None:
        return str(row[0])
    user_id = _uuid.uuid4()
    now = datetime.now(UTC)
    # created_at/updated_at are explicit: the baseline DDL's server
    # default is Postgres-only `now()`, which SQLite cannot evaluate at
    # INSERT time.
    await session.execute(
        text(
            "INSERT INTO users (id, email, password_hash, full_name, is_active, "
            "is_admin, failed_login_attempts, token_version, created_at, "
            "updated_at) VALUES "
            "(:id, :email, :hash, '', true, false, 0, 1, :now, :now)"
        ),
        {
            "id": str(user_id),
            "email": email,
            "hash": "$2b$12$foldmigrationplaceholder",
            "now": now,
        },
    )
    return str(user_id)


def _table_present(table: str = "cv_synth_items") -> bool:
    """A fresh engine per probe — pool connections are loop-bound.

    Probes via the SQLAlchemy inspector so the round-trips also run on the
    SQLite (desktop) CI profile — information_schema is Postgres-only.
    """

    async def probe():
        from sqlalchemy import inspect
        from sqlalchemy.ext.asyncio import create_async_engine

        from app.core.config import settings

        engine = create_async_engine(settings.database_url)
        try:
            async with engine.connect() as conn:
                return bool(
                    await conn.run_sync(lambda sync_conn: inspect(sync_conn).has_table(table))
                )
        finally:
            await engine.dispose()

    return bool(asyncio.run(probe()))


def _column_present(table: str, column: str) -> bool:
    from sqlalchemy import inspect
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.core.config import settings

    async def run():
        engine = create_async_engine(settings.database_url)
        try:
            async with engine.connect() as conn:
                columns = await conn.run_sync(
                    lambda sync_conn: [col["name"] for col in inspect(sync_conn).get_columns(table)]
                )
            return column in columns
        finally:
            await engine.dispose()

    return bool(asyncio.run(run()))


def _index_present(table: str, index: str) -> bool:
    from sqlalchemy import inspect
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.core.config import settings

    async def run():
        engine = create_async_engine(settings.database_url)
        try:
            async with engine.connect() as conn:
                names = await conn.run_sync(
                    lambda sync_conn: [
                        entry["name"] for entry in inspect(sync_conn).get_indexes(table)
                    ]
                )
            return index in names
        finally:
            await engine.dispose()

    return bool(asyncio.run(run()))


def test_0027_cv_synth_items_roundtrip():
    from alembic.script import ScriptDirectory

    config = _configured()
    assert ScriptDirectory.from_config(config).get_heads() == ["0097"], (
        "revision chain stays linear on one head"
    )

    command.upgrade(config, "head")
    assert _table_present(), "cv_synth_items exists at head"

    command.downgrade(config, "0026")
    assert not _table_present(), "downgrade 0026 drops the table"

    command.upgrade(config, "head")
    assert _table_present(), "re-upgrade restores the table"


def _spaces_0094_table():
    """The ``vector_spaces`` shape at 0094, plus the 0095 column for reads."""
    import sqlalchemy as sa

    return sa.table(
        "vector_spaces",
        sa.column("id", sa.Uuid()),
        sa.column("name", sa.String),
        sa.column("provider", sa.String),
        sa.column("model", sa.String),
        sa.column("dim", sa.Integer),
        sa.column("metric", sa.String),
        sa.column("normalize", sa.Boolean),
        sa.column("chunker_version", sa.String),
        sa.column("composer_version", sa.String),
        sa.column("query_prefix", sa.String),
        sa.column("document_prefix", sa.String),
        sa.column("status", sa.String),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
        sa.column("space_key", sa.String),
    )


def _space_specs_0094() -> list[dict]:
    """Two populated 0094 rows with distinct v1 pre-images."""
    import uuid as _uuid

    return [
        {
            "id": _uuid.uuid4(),
            "name": f"migrate-plain-{_uuid.uuid4().hex[:8]}",
            "provider": "openai",
            "model": "text-embedding-3-small",
            "dim": 1536,
            "normalize": True,
            "query_prefix": None,
            "document_prefix": None,
            "chunker_version": "1",
            "composer_version": "1",
        },
        {
            "id": _uuid.uuid4(),
            "name": f"migrate-asym-{_uuid.uuid4().hex[:8]}",
            "provider": "Ollama",
            "model": "embeddinggemma-2:440m ",
            "dim": 768,
            "normalize": False,
            "query_prefix": "query: ",
            "document_prefix": "passage: ",
            "chunker_version": "2",
            "composer_version": "3",
        },
    ]


def _insert_0094_spaces(specs: list[dict]) -> None:
    import asyncio

    from sqlalchemy.ext.asyncio import create_async_engine

    from app.core.config import settings

    spaces = _spaces_0094_table()
    now = datetime.now(UTC)

    async def run() -> None:
        engine = create_async_engine(settings.database_url)
        try:
            async with engine.begin() as conn:
                for spec in specs:
                    await conn.execute(
                        spaces.insert().values(
                            **spec,
                            metric="cosine",
                            status="active",
                            created_at=now,
                            updated_at=now,
                        )
                    )
        finally:
            await engine.dispose()

    asyncio.run(run())


def _read_0095_space_keys() -> dict[str, str]:
    import asyncio

    import sqlalchemy as sa
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.core.config import settings

    spaces = _spaces_0094_table()

    async def run() -> dict[str, str]:
        engine = create_async_engine(settings.database_url)
        try:
            async with engine.begin() as conn:
                rows = (await conn.execute(sa.select(spaces.c.id, spaces.c.space_key))).all()
            return {str(row[0]): str(row[1]) for row in rows}
        finally:
            await engine.dispose()

    return asyncio.run(run())


def _expected_v1_key(spec: dict) -> str:
    from app.storage.vector_contract import space_key

    return space_key(
        spec["provider"],
        spec["model"],
        spec["dim"],
        spec["normalize"],
        spec["query_prefix"],
        spec["document_prefix"],
        spec["chunker_version"],
        spec["composer_version"],
    )


def test_0095_vector_space_key_stamps_populated_rows_and_roundtrips():
    """Plan 52 T3a: every existing row keeps its v1 key verbatim, once."""
    config = _configured()
    command.upgrade(config, "head")
    command.downgrade(config, "0094")
    assert not _column_present("vector_spaces", "space_key"), "0094 has no stored key"

    specs = _space_specs_0094()
    _insert_0094_spaces(specs)

    command.upgrade(config, "head")
    assert _column_present("vector_spaces", "space_key")
    stored = _read_0095_space_keys()
    for spec in specs:
        assert stored[str(spec["id"])] == _expected_v1_key(spec), spec["name"]

    command.downgrade(config, "0094")
    assert not _column_present("vector_spaces", "space_key"), "downgrade drops the column"

    command.upgrade(config, "head")
    assert _column_present("vector_spaces", "space_key")


_TOKEN_COLUMNS = (
    "tokenizer_kind",
    "tokenizer_identifier",
    "tokenizer_revision",
    "tokenizer_artifact_sha256",
    "tokenizer_exact",
    "max_input_tokens",
    "chunk_max_tokens",
    "chunk_overlap_tokens",
    "chunk_max_chars",
)
_TOKEN_RECORD_COLUMNS = ("token_count", "token_start", "token_end")


def _read_0096_spaces() -> dict[str, dict]:
    import asyncio

    import sqlalchemy as sa
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.core.config import settings

    async def run() -> dict[str, dict]:
        engine = create_async_engine(settings.database_url)
        try:
            async with engine.connect() as conn:
                rows = (
                    await conn.execute(
                        sa.text(
                            "SELECT id, space_key, tokenizer_kind, tokenizer_identifier, "
                            "tokenizer_revision, tokenizer_artifact_sha256, tokenizer_exact, "
                            "max_input_tokens, chunk_max_tokens, chunk_overlap_tokens, "
                            "chunk_max_chars FROM vector_spaces"
                        )
                    )
                ).mappings()
                return {str(uuid.UUID(str(row["id"]))): dict(row) for row in rows}
        finally:
            await engine.dispose()

    return asyncio.run(run())


def test_0096_token_columns_keep_legacy_rows_null_and_roundtrip():
    """Plan 52 T3b: a populated v1 space gains NULL tokenizer/chunk columns
    and keeps its stored v1 key verbatim; downgrade removes only the columns."""
    config = _configured()
    command.upgrade(config, "head")
    command.downgrade(config, "0095")
    assert not _column_present("vector_spaces", "tokenizer_kind")
    assert not _column_present("vector_records", "token_count")

    spec = {
        "id": uuid.uuid4(),
        "name": f"token-migrate-{uuid.uuid4().hex[:8]}",
        "provider": "openai",
        "model": "text-embedding-3-small",
        "dim": 1536,
        "normalize": True,
        "query_prefix": None,
        "document_prefix": None,
        "chunker_version": "1",
        "composer_version": "1",
    }
    spec["space_key"] = _expected_v1_key(spec)
    _insert_0094_spaces([spec])

    command.upgrade(config, "head")
    for column in _TOKEN_COLUMNS:
        assert _column_present("vector_spaces", column), column
    assert _column_present("vector_spaces", "tokenizer_source")
    for column in _TOKEN_RECORD_COLUMNS:
        assert _column_present("vector_records", column), column
    row = _read_0096_spaces()[str(spec["id"])]
    assert row["space_key"] == spec["space_key"], "the stored v1 key is untouched"
    assert all(row[column] is None for column in _TOKEN_COLUMNS), row

    command.downgrade(config, "0095")
    assert not _column_present("vector_spaces", "tokenizer_kind")
    assert not _column_present("vector_records", "token_count")
    assert _read_0095_space_keys()[str(spec["id"])] == spec["space_key"]

    command.upgrade(config, "head")
    assert _column_present("vector_spaces", "tokenizer_kind")


def test_0097_tokenizer_source_is_additive_and_drops_cleanly():
    """Plan 52 T3c: the provenance column never rewrites the stored key."""
    config = _configured()
    command.upgrade(config, "head")
    assert _column_present("vector_spaces", "tokenizer_source")

    spec = {
        "id": uuid.uuid4(),
        "name": f"token-source-{uuid.uuid4().hex[:8]}",
        "provider": "openai",
        "model": "text-embedding-3-small",
        "dim": 1536,
        "normalize": True,
        "query_prefix": None,
        "document_prefix": None,
        "chunker_version": "1",
        "composer_version": "1",
    }
    spec["space_key"] = _expected_v1_key(spec)
    key = str(spec["id"])
    command.downgrade(config, "0096")
    assert not _column_present("vector_spaces", "tokenizer_source")
    _insert_0094_spaces([spec])
    command.upgrade(config, "head")
    assert _read_0095_space_keys()[key] == spec["space_key"]
    command.downgrade(config, "0096")
    assert not _column_present("vector_spaces", "tokenizer_source")
    assert _read_0095_space_keys()[key] == spec["space_key"]
    command.upgrade(config, "head")


def test_populated_sqlite_upgrades_0095_to_0096(tmp_path, monkeypatch):
    """The desktop profile adds/removes the token columns through batch mode."""
    from app.core.config import settings

    db_url = f"sqlite+aiosqlite:///{tmp_path / 'vector-spaces-0096.db'}"
    monkeypatch.setenv("CAREER_DATABASE_URL", db_url)
    monkeypatch.setattr(settings, "database_url", db_url, raising=False)
    config = _configured()

    command.upgrade(config, "head")
    command.downgrade(config, "0095")
    assert not _column_present("vector_spaces", "tokenizer_kind")

    spec = {
        "id": uuid.uuid4(),
        "name": f"sqlite-token-{uuid.uuid4().hex[:8]}",
        "provider": "openai",
        "model": "text-embedding-3-small",
        "dim": 384,
        "normalize": True,
        "query_prefix": None,
        "document_prefix": None,
        "chunker_version": "1",
        "composer_version": "1",
    }
    spec["space_key"] = _expected_v1_key(spec)
    _insert_0094_spaces([spec])

    command.upgrade(config, "0096")
    row = _read_0096_spaces()[str(spec["id"])]
    assert row["space_key"] == spec["space_key"]
    assert all(row[column] is None for column in _TOKEN_COLUMNS), row

    command.downgrade(config, "0095")
    assert not _column_present("vector_spaces", "tokenizer_kind")
    assert _read_0095_space_keys()[str(spec["id"])] == spec["space_key"]
    command.upgrade(config, "head")


def test_populated_sqlite_upgrades_0094_to_0095(tmp_path, monkeypatch):
    """The desktop profile stamps a populated SQLite file through batch mode."""
    import uuid as _uuid

    from app.core.config import settings

    db_url = f"sqlite+aiosqlite:///{tmp_path / 'vector-spaces-0095.db'}"
    monkeypatch.setenv("CAREER_DATABASE_URL", db_url)
    monkeypatch.setattr(settings, "database_url", db_url, raising=False)
    config = _configured()

    command.upgrade(config, "head")
    command.downgrade(config, "0094")
    assert not _column_present("vector_spaces", "space_key")

    spec = {
        "id": _uuid.uuid4(),
        "name": f"sqlite-stamp-{_uuid.uuid4().hex[:8]}",
        "provider": "openai",
        "model": "text-embedding-3-small",
        "dim": 384,
        "normalize": True,
        "query_prefix": "query: ",
        "document_prefix": None,
        "chunker_version": "1",
        "composer_version": "1",
    }
    _insert_0094_spaces([spec])

    command.upgrade(config, "0095")
    assert _read_0095_space_keys()[str(spec["id"])] == _expected_v1_key(spec)

    command.upgrade(config, "head")


def test_0078_search_preset_name_roundtrip():
    """Plan 165: saved searches carry a preset name; the column is nullable
    so existing remembered rows survive the upgrade unchanged."""
    config = _configured()
    command.upgrade(config, "head")
    assert _column_present("search_history", "name"), "preset names exist at head"

    command.downgrade(config, "0077")
    assert not _column_present("search_history", "name"), "downgrade drops the column"

    command.upgrade(config, "head")
    assert _column_present("search_history", "name"), "re-upgrade restores the column"


def test_0079_autopilot_run_steps_roundtrip():
    """Plan 168: the durable step-trace ledger lives on the run row; the
    NOT NULL add carries a dialect-safe server default."""
    config = _configured()
    command.upgrade(config, "head")
    assert _column_present("autopilot_runs", "run_steps"), "trace ledger exists at head"

    command.downgrade(config, "0078")
    assert not _column_present("autopilot_runs", "run_steps"), "downgrade drops the column"

    command.upgrade(config, "head")
    assert _column_present("autopilot_runs", "run_steps"), "re-upgrade restores the column"


def test_0080_source_display_title_roundtrip():
    """Plan 173: job_sources carry the manifest display name; the column is
    nullable so builtin sources (no manifest) keep NULL through the upgrade."""
    config = _configured()
    command.upgrade(config, "head")
    assert _column_present("job_sources", "title"), "display titles exist at head"

    command.downgrade(config, "0079")
    assert not _column_present("job_sources", "title"), "downgrade drops the column"

    command.upgrade(config, "head")
    assert _column_present("job_sources", "title"), "re-upgrade restores the column"


def test_0082_findings_feed_indexes_roundtrip():
    """Plan 175: the findings feed's two indexes exist at head and die on
    the downgrade (created_at ordering, posting_id dedupe/applied join)."""
    config = _configured()
    command.upgrade(config, "head")
    assert _index_present("autopilot_findings", "ix_autopilot_findings_created")
    assert _index_present("autopilot_findings", "ix_autopilot_findings_posting")

    command.downgrade(config, "0081")
    assert not _index_present("autopilot_findings", "ix_autopilot_findings_created")
    assert not _index_present("autopilot_findings", "ix_autopilot_findings_posting")

    command.upgrade(config, "head")
    assert _index_present("autopilot_findings", "ix_autopilot_findings_created")
    assert _index_present("autopilot_findings", "ix_autopilot_findings_posting")


def test_0083_smart_query_cache_roundtrip():
    """Plan 179: the cross-user NL-query cache exists at head and drops on
    the downgrade (cache data is rebuildable, never a record)."""
    config = _configured()
    command.upgrade(config, "head")
    assert _table_present("smart_query_cache"), "smart_query_cache exists at head"

    command.downgrade(config, "0082")
    assert not _table_present("smart_query_cache"), "downgrade drops the cache table"

    command.upgrade(config, "head")
    assert _table_present("smart_query_cache"), "re-upgrade restores the cache table"


def test_0033_profile_proposals_roundtrip():
    config = _configured()

    command.upgrade(config, "head")
    assert _table_present("profile_proposals"), "profile_proposals exists at head"

    command.downgrade(config, "0032")
    assert not _table_present("profile_proposals"), "downgrade 0032 drops the table"

    command.upgrade(config, "head")
    assert _table_present("profile_proposals"), "re-upgrade restores the table"


def test_0042_identity_core_roundtrip():
    """Identity core (§5): the normative tables and `users` OIDC link
    survive the migration round-trip."""
    config = _configured()

    command.upgrade(config, "head")
    for table in ("auth_sessions", "instance_settings", "audit_events"):
        assert _table_present(table), f"{table} exists at head"
    assert _column_present("users", "oidc_issuer"), "users carries oidc_issuer (§5)"
    assert _column_present("users", "oidc_subject"), "users carries oidc_subject (§5)"

    command.downgrade(config, "0041")
    for table in ("auth_sessions", "instance_settings", "audit_events"):
        assert not _table_present(table), f"downgrade 0041 drops {table}"
    assert not _column_present("users", "oidc_issuer")

    command.upgrade(config, "head")
    assert _table_present("auth_sessions"), "re-upgrade restores the tables"


def test_0043_profiles_one_to_many_legacy_backfill():
    """`profiles` 1:N (plan 16 P3b): legacy 1:1 rows upgrade in place —
    `name` backfilled "Default", `is_default` true — and a second profile
    per user is accepted afterwards (the unique index is gone)."""
    config = _configured()
    command.downgrade(config, "0042")

    async def seed_legacy() -> list:
        import uuid
        from datetime import datetime

        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine

        from app.core.config import settings

        user_ids = [uuid.uuid4() for _ in range(2)]
        now = datetime.now(UTC)
        engine = create_async_engine(settings.database_url)
        try:
            async with engine.begin() as conn:
                for index, user_id in enumerate(user_ids):
                    # Timestamps are explicit: the server defaults are
                    # Postgres-only `now()`, unevaluable on SQLite.
                    await conn.execute(
                        text(
                            "INSERT INTO users (id, email, password_hash, "
                            "full_name, is_active, is_admin, failed_login_attempts, "
                            "token_version, created_at, updated_at) VALUES (:id, "
                            ":email, '$2b$12$foldmigrationplaceholder', '', true, "
                            "false, 0, 1, :now, :now)"
                        ),
                        {
                            "id": str(user_id),
                            "email": f"legacy{index}@example.com",
                            "now": now,
                        },
                    )
                    await conn.execute(
                        text(
                            "INSERT INTO profiles (id, user_id, basics, academics, "
                            "hobbies, likes, dislikes, aspirations, work_preferences, "
                            "preferences, constraints, created_at, updated_at) VALUES "
                            "(:id, :user_id, '{}', '{}', '[]', '[]', '[]', '[]', "
                            "'{}', '{}', '{}', :now, :now)"
                        ),
                        {
                            "id": str(uuid.uuid4()),
                            "user_id": str(user_id),
                            "now": now,
                        },
                    )
        finally:
            await engine.dispose()
        return user_ids

    user_ids = asyncio.run(seed_legacy())

    command.upgrade(config, "head")

    async def probe() -> tuple[list[tuple], int]:
        import uuid
        from datetime import datetime

        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine

        from app.core.config import settings

        now = datetime.now(UTC)
        engine = create_async_engine(settings.database_url)
        try:
            async with engine.begin() as conn:
                rows = list(
                    (
                        await conn.execute(
                            text(
                                "SELECT name, is_default FROM profiles "
                                "WHERE user_id = :uid ORDER BY created_at"
                            ),
                            {"uid": str(user_ids[0])},
                        )
                    ).all()
                )
                await conn.execute(
                    text(
                        "INSERT INTO profiles (id, user_id, basics, academics, "
                        "hobbies, likes, dislikes, aspirations, work_preferences, "
                        "preferences, constraints, created_at, updated_at) VALUES "
                        "(:id, :user_id, '{}', '{}', '[]', '[]', '[]', '[]', "
                        "'{}', '{}', '{}', :now, :now)"
                    ),
                    {
                        "id": str(uuid.uuid4()),
                        "user_id": str(user_ids[0]),
                        "now": now,
                    },
                )
                count = (
                    await conn.execute(
                        text("SELECT count(*) FROM profiles WHERE user_id = :uid"),
                        {"uid": str(user_ids[0])},
                    )
                ).scalar()
        finally:
            await engine.dispose()
        return rows, int(count)

    rows, count = asyncio.run(probe())
    assert [row[0] for row in rows] == ["Default"] and bool(rows[0][1]), (
        "legacy rows backfill name + is_default (§5)"
    )
    assert count == 2, "the unique index is gone — one user may own many profiles"


def _scope_constraint_allows_bullets() -> bool:
    """The `scope_allowed` check constraint text admits 'bullets' — probed
    dialect-aware (pg_constraint on Postgres, table DDL on SQLite)."""

    async def probe() -> bool:
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine

        from app.core.config import settings

        engine = create_async_engine(settings.database_url)
        try:
            async with engine.connect() as conn:
                if engine.dialect.name == "postgresql":
                    row = await conn.execute(
                        text(
                            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                            "WHERE conrelid = 'cv_synth_items'::regclass "
                            "AND conname LIKE '%scope_allowed'"
                        )
                    )
                    definition = row.scalar() or ""
                else:
                    row = await conn.execute(
                        text(
                            "SELECT sql FROM sqlite_master "
                            "WHERE type = 'table' AND name = 'cv_synth_items'"
                        )
                    )
                    definition = row.scalar() or ""
                return "'bullets'" in definition
        finally:
            await engine.dispose()

    return bool(asyncio.run(probe()))


def test_0039_cv_synth_bullets_scope_roundtrip():
    config = _configured()

    command.upgrade(config, "head")
    assert _scope_constraint_allows_bullets(), "head admits scope 'bullets'"

    command.downgrade(config, "0038")
    assert not _scope_constraint_allows_bullets(), (
        "downgrade 0038 restores the two-scope constraint"
    )

    command.upgrade(config, "head")
    assert _scope_constraint_allows_bullets(), "re-upgrade restores 'bullets'"


def _schedules_checks() -> dict[str, str]:
    """kind/task CHECK expressions on `schedules` (dialect-safe)."""

    async def run():
        from sqlalchemy import inspect
        from sqlalchemy.ext.asyncio import create_async_engine

        from app.core.config import settings

        engine = create_async_engine(settings.database_url)
        try:
            async with engine.connect() as conn:
                checks = await conn.run_sync(
                    lambda sync_conn: inspect(sync_conn).get_check_constraints("schedules")
                )
            # The metadata naming convention renders prefixed names
            # (ck_schedules_kind_allowed) — normalize to the short name.
            return {c["name"].replace("ck_schedules_", ""): c["sqltext"] for c in checks}
        finally:
            await engine.dispose()

    import asyncio

    return asyncio.run(run())


def test_0034_proposal_sweep_checks_roundtrip():
    config = _configured()

    command.upgrade(config, "head")
    checks = _schedules_checks()
    assert "system_proposal_sweep" in checks["kind_allowed"]
    assert "proposal_sweep" in checks["task_allowed"]

    command.downgrade(config, "0033")
    checks = _schedules_checks()
    assert "system_proposal_sweep" not in checks["kind_allowed"]
    assert "proposal_sweep" not in checks["task_allowed"]

    command.upgrade(config, "head")


def test_0026_language_code_roundtrip():
    config = _configured()

    command.upgrade(config, "head")
    assert _column_present("certifications", "language_code"), (
        "certifications.language_code exists at head"
    )

    command.downgrade(config, "0025")
    assert not _column_present("certifications", "language_code"), "downgrade 0025 drops the column"

    command.upgrade(config, "head")
    assert _column_present("certifications", "language_code"), "re-upgrade restores the column"


def test_0031_user_skill_hidden_roundtrip():
    config = _configured()

    command.upgrade(config, "head")
    assert _column_present("user_skills", "hidden"), "user_skills.hidden exists at head"

    command.downgrade(config, "0030")
    assert not _column_present("user_skills", "hidden"), "downgrade 0030 drops the column"

    command.upgrade(config, "head")
    assert _column_present("user_skills", "hidden"), "re-upgrade restores the column"


def test_0029_run_linkage_roundtrip():
    config = _configured()

    command.upgrade(config, "head")
    assert _column_present("ai_generations", "run_id"), "ai_generations.run_id exists at head"
    assert _column_present("ai_generations", "run_stage"), "ai_generations.run_stage exists at head"


def test_0030_derive_enabled_roundtrip():
    config = _configured()

    command.upgrade(config, "head")
    assert _column_present("user_skills", "derive_enabled"), (
        "user_skills.derive_enabled exists at head"
    )

    command.downgrade(config, "0029")
    assert not _column_present("user_skills", "derive_enabled"), "downgrade 0029 drops the column"

    command.upgrade(config, "head")
    assert _column_present("user_skills", "derive_enabled"), "re-upgrade restores the column"

    command.downgrade(config, "0028")
    assert not _column_present("ai_generations", "run_id"), "downgrade 0028 drops the run columns"
    assert not _column_present("ai_generations", "run_stage"), (
        "downgrade 0028 drops the run columns"
    )

    command.upgrade(config, "head")
    assert _column_present("ai_generations", "run_id"), "re-upgrade restores the run columns"
    assert _column_present("ai_generations", "run_stage"), "re-upgrade restores the run columns"


def _start_nullable() -> bool:
    from sqlalchemy import inspect
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.core.config import settings

    async def probe():
        engine = create_async_engine(settings.database_url)
        try:
            async with engine.connect() as conn:
                columns = await conn.run_sync(
                    lambda sync_conn: inspect(sync_conn).get_columns("experience_items")
                )
                start = next((c for c in columns if c["name"] == "start"), None)
                return bool(start is not None and start["nullable"])
        finally:
            await engine.dispose()

    return bool(asyncio.run(probe()))


def test_0032_experience_start_nullable_roundtrip():
    config = _configured()

    command.upgrade(config, "head")
    assert _start_nullable(), "experience_items.start is nullable at head"

    command.downgrade(config, "0031")
    assert not _start_nullable(), "downgrade restores the NOT NULL start"

    command.upgrade(config, "head")
    assert _start_nullable(), "re-upgrade re-allows undated rows"


def test_fresh_sqlite_migrates_to_head(monkeypatch):
    """The desktop mode migrates a fresh SQLite file — constraint and
    column ALTERs must go through batch mode (the packaging smoke's
    regression)."""
    import tempfile
    from pathlib import Path

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    Path(path).unlink()
    db_url = f"sqlite+aiosqlite:///{path}"
    monkeypatch.setenv("CAREER_DATABASE_URL", db_url)
    monkeypatch.setattr("app.core.config.settings.database_url", db_url, raising=False)
    try:
        command.upgrade(_configured(), "head")
    finally:
        if Path(path).exists():
            Path(path).unlink()


def _proposal_kinds_check() -> str:
    """kind CHECK expression on `profile_proposals` (dialect-safe)."""

    async def run():
        from sqlalchemy import inspect
        from sqlalchemy.ext.asyncio import create_async_engine

        from app.core.config import settings

        engine = create_async_engine(settings.database_url)
        try:
            async with engine.connect() as conn:
                checks = await conn.run_sync(
                    lambda sync_conn: inspect(sync_conn).get_check_constraints("profile_proposals")
                )
            return {c["name"].replace("ck_profile_proposals_", ""): c["sqltext"] for c in checks}[
                "kind_allowed"
            ]
        finally:
            await engine.dispose()

    import asyncio

    return asyncio.run(run())


def test_0035_chat_cv_synth_kind_roundtrip():
    config = _configured()

    command.upgrade(config, "head")
    assert "cv_synth" in _proposal_kinds_check()

    command.downgrade(config, "0034")
    assert "cv_synth" not in _proposal_kinds_check()

    command.upgrade(config, "head")
    assert "cv_synth" in _proposal_kinds_check()


def test_0036_checkpoint_prune_checks_roundtrip():
    config = _configured()

    command.upgrade(config, "head")
    checks = _schedules_checks()
    assert "system_checkpoint_prune" in checks["kind_allowed"]
    assert "checkpoint_prune" in checks["task_allowed"]

    command.downgrade(config, "0035")
    checks = _schedules_checks()
    assert "system_checkpoint_prune" not in checks["kind_allowed"]
    assert "checkpoint_prune" not in checks["task_allowed"]

    command.upgrade(config, "head")


def _proposal_status_checks() -> dict[str, str]:
    """status CHECK expression on `profile_proposals` (dialect-safe)."""

    async def run():
        from sqlalchemy import inspect
        from sqlalchemy.ext.asyncio import create_async_engine

        from app.core.config import settings

        engine = create_async_engine(settings.database_url)
        try:
            async with engine.connect() as conn:
                checks = await conn.run_sync(
                    lambda sync_conn: inspect(sync_conn).get_check_constraints("profile_proposals")
                )
            return {c["name"].replace("ck_profile_proposals_", ""): c["sqltext"] for c in checks}[
                "status_allowed"
            ]
        finally:
            await engine.dispose()

    import asyncio

    return asyncio.run(run())


def test_0037_proposal_reverted_status_roundtrip():
    config = _configured()

    command.upgrade(config, "head")
    assert "reverted" in _proposal_status_checks()

    command.downgrade(config, "0036")
    assert "reverted" not in _proposal_status_checks()

    command.upgrade(config, "head")
    assert "reverted" in _proposal_status_checks()


def test_0041_one_slot_pin_fold():
    """Plan-110 data migration: `:bullets` pins fold onto the single key
    with per-field winner semantics — two DIFFERENT pinned rows merge
    into the text winner (achievements adopted only when it had none)
    and the duplicate bullets row archives; a lone pin keeps its row."""

    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.core.config import settings
    from app.models.cv_model import CvDocument
    from app.models.cv_synth_model import CvSynthItem

    config = _configured()
    # The suite DB may sit at head from an earlier test — force the
    # pre-fold revision so this data migration actually runs below.
    command.downgrade(config, "0040")
    command.upgrade(config, "0040")

    async def seed():
        engine = create_async_engine(settings.database_url)
        maker = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with maker() as session:
                # Raw SQL: the ORM User model carries the 0042 columns
                # and cannot map below that revision (see helper).
                user_id = await _ensure_fold_user(session, "fold0041@example.com")
                item_id = user_id
                text_row = CvSynthItem(
                    user_id=user_id,
                    scope="item",
                    variant_key="default",
                    source_refs=[{"source_key": "experience", "item_id": item_id}],
                    source_state=[],
                    source_set_hash="fold0041",
                    payload={"description": "Text winner description"},
                    evidence_refs=[],
                    voice={"language": "en"},
                    status="active",
                    source="manual",
                    verified=True,
                )
                bullets_row = CvSynthItem(
                    user_id=user_id,
                    scope="bullets",
                    variant_key="default",
                    source_refs=[{"source_key": "experience", "item_id": item_id}],
                    source_state=[],
                    source_set_hash="fold0041",
                    payload={"achievements": [{"text": "from B"}]},
                    evidence_refs=[],
                    voice={"language": "en"},
                    status="active",
                    source="manual",
                    verified=True,
                )
                session.add_all([text_row, bullets_row])
                await session.flush()
                cv = CvDocument(
                    user_id=user_id,
                    title="Fold",
                    context={
                        "mode": "custom",
                        "synth_pins": {
                            f"experience:{item_id}": str(text_row.id),
                            f"experience:{item_id}:bullets": str(bullets_row.id),
                        },
                    },
                )
                session.add(cv)
                await session.commit()
                return {
                    "cv": str(cv.id),
                    "text": str(text_row.id),
                    "bullets": str(bullets_row.id),
                    "item_key": f"experience:{item_id}",
                }
        finally:
            await engine.dispose()

    seeded = asyncio.run(seed())
    command.upgrade(config, "0041")

    async def verify():
        engine = create_async_engine(settings.database_url)
        maker = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with maker() as session:
                cv = (
                    (await session.execute(select(CvDocument).where(CvDocument.id == seeded["cv"])))
                    .scalars()
                    .one()
                )
                text_row = (
                    (
                        await session.execute(
                            select(CvSynthItem).where(CvSynthItem.id == seeded["text"])
                        )
                    )
                    .scalars()
                    .one()
                )
                bullets_row = (
                    (
                        await session.execute(
                            select(CvSynthItem).where(CvSynthItem.id == seeded["bullets"])
                        )
                    )
                    .scalars()
                    .one()
                )
                return cv.context.get("synth_pins"), text_row, bullets_row
        finally:
            await engine.dispose()

    pins, text_row, bullets_row = asyncio.run(verify())
    assert pins.get(seeded["item_key"]) == seeded["text"], (
        "the single pin key keeps the text winner"
    )
    assert not any(key.endswith(":bullets") for key in pins), "legacy keys folded"
    assert text_row.payload["achievements"] == [{"text": "from B"}], (
        "the text row adopted the bullets (per-field winner merge)"
    )
    assert text_row.status == "active"
    assert bullets_row.status == "archived", "the duplicate bullets row retired"
    asyncio.run(_cleanup_fold_data(seeded))


async def _cleanup_fold_data(seeded: dict) -> None:
    from sqlalchemy import delete
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.core.config import settings
    from app.models.cv_model import CvDocument
    from app.models.cv_synth_model import CvSynthItem
    from app.models.user_model import User

    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with maker() as session:
            await session.execute(delete(CvSynthItem).where(CvSynthItem.id == seeded["text"]))
            await session.execute(delete(CvSynthItem).where(CvSynthItem.id == seeded["bullets"]))
            await session.execute(delete(CvDocument).where(CvDocument.title == "Fold"))
            await session.execute(delete(User).where(User.email == "fold0041@example.com"))
            await session.commit()
    finally:
        await engine.dispose()


def test_0041_fold_states_and_cross_cv_guard():
    """The other three fold states (bullets-only, same row, both gone) plus
    the cross-CV guard: a folded bullets row that another CV still pins on
    the PLAIN key must NOT be archived."""

    import uuid as _uuid

    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.core.config import settings
    from app.models.cv_model import CvDocument
    from app.models.cv_synth_model import CvSynthItem
    from app.models.user_model import User

    config = _configured()
    command.downgrade(config, "0040")
    command.upgrade(config, "0040")

    async def seed():
        engine = create_async_engine(settings.database_url)
        maker = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with maker() as session:
                # Raw SQL: the ORM User model carries the 0042 columns
                # and cannot map below that revision (see helper).
                user_id = await _ensure_fold_user(session, "fold0041b@example.com")

                def row(scope: str, payload: dict) -> CvSynthItem:
                    return CvSynthItem(
                        user_id=user_id,
                        scope=scope,
                        variant_key="default",
                        source_refs=[{"source_key": "experience", "item_id": user_id}],
                        source_state=[],
                        source_set_hash="fold0041b",
                        payload=payload,
                        evidence_refs=[],
                        voice={"language": "en"},
                        status="active",
                        source="manual",
                        verified=True,
                    )

                t_merge = row("item", {"description": "text winner"})
                b_merge = row("bullets", {"achievements": [{"text": "from bullets"}]})
                b_only = row("bullets", {"achievements": [{"text": "only bullets"}]})
                t_same = row("item", {"description": "same row"})
                session.add_all([t_merge, b_merge, b_only, t_same])
                await session.flush()

                ref_merge = f"experience:{_uuid.uuid4()}"
                ref_only = f"experience:{_uuid.uuid4()}"
                ref_same = f"experience:{_uuid.uuid4()}"
                ref_gone = f"experience:{_uuid.uuid4()}"
                gone_a, gone_b = str(_uuid.uuid4()), str(_uuid.uuid4())

                cv_a = CvDocument(
                    user_id=user_id,
                    title="FoldA",
                    context={
                        "mode": "custom",
                        "synth_pins": {
                            ref_merge: str(t_merge.id),
                            f"{ref_merge}:bullets": str(b_merge.id),
                            f"{ref_only}:bullets": str(b_only.id),
                            ref_same: str(t_same.id),
                            f"{ref_same}:bullets": str(t_same.id),
                            ref_gone: gone_a,
                            f"{ref_gone}:bullets": gone_b,
                        },
                    },
                )
                cv_b = CvDocument(
                    user_id=user_id,
                    title="FoldB",
                    context={
                        "mode": "custom",
                        "synth_pins": {ref_merge: str(b_merge.id)},
                    },
                )
                session.add_all([cv_a, cv_b])
                await session.commit()
                return {
                    "user": user_id,
                    "cv_a": str(cv_a.id),
                    "cv_b": str(cv_b.id),
                    "t_merge": str(t_merge.id),
                    "b_merge": str(b_merge.id),
                    "b_only": str(b_only.id),
                    "t_same": str(t_same.id),
                    "ref_merge": ref_merge,
                    "ref_only": ref_only,
                    "ref_same": ref_same,
                    "ref_gone": ref_gone,
                }
        finally:
            await engine.dispose()

    seeded = asyncio.run(seed())
    command.upgrade(config, "0041")

    async def verify():
        engine = create_async_engine(settings.database_url)
        maker = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with maker() as session:
                cv_a = (
                    (
                        await session.execute(
                            select(CvDocument).where(CvDocument.id == seeded["cv_a"])
                        )
                    )
                    .scalars()
                    .one()
                )
                cv_b = (
                    (
                        await session.execute(
                            select(CvDocument).where(CvDocument.id == seeded["cv_b"])
                        )
                    )
                    .scalars()
                    .one()
                )
                items = {
                    str(r.id): r
                    for r in (
                        await session.execute(
                            select(CvSynthItem).where(
                                CvSynthItem.id.in_(
                                    [
                                        seeded[k]
                                        for k in (
                                            "t_merge",
                                            "b_merge",
                                            "b_only",
                                            "t_same",
                                        )
                                    ]
                                )
                            )
                        )
                    )
                    .scalars()
                    .all()
                }
                return (
                    cv_a.context.get("synth_pins"),
                    cv_b.context.get("synth_pins"),
                    items,
                )
        finally:
            await engine.dispose()

    pins_a, pins_b, items = asyncio.run(verify())
    assert not any(key.endswith(":bullets") for key in pins_a), "legacy keys folded"
    assert pins_a.get(seeded["ref_merge"]) == seeded["t_merge"]
    assert pins_a.get(seeded["ref_only"]) == seeded["b_only"], (
        "a bullets-only star keeps its row on the single key"
    )
    assert pins_a.get(seeded["ref_same"]) == seeded["t_same"], (
        "both keys on the same row collapse to one"
    )
    assert seeded["ref_gone"] not in pins_a, "a pin to two deleted rows never dangles"
    assert items[seeded["t_merge"]].payload["achievements"] == [{"text": "from bullets"}]
    assert items[seeded["b_only"]].status == "active"
    assert items[seeded["t_same"]].status == "active"
    assert items[seeded["b_merge"]].status == "active", (
        "a bullets row another CV still pins on the plain key must not be archived"
    )
    assert pins_b.get(seeded["ref_merge"]) == seeded["b_merge"], (
        "the other CV's plain pin is untouched"
    )

    async def cleanup():
        from sqlalchemy import delete

        engine = create_async_engine(settings.database_url)
        maker = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with maker() as session:
                for value in (
                    seeded["t_merge"],
                    seeded["b_merge"],
                    seeded["b_only"],
                    seeded["t_same"],
                ):
                    await session.execute(delete(CvSynthItem).where(CvSynthItem.id == value))
                await session.execute(
                    delete(CvDocument).where(CvDocument.title.in_(["FoldA", "FoldB"]))
                )
                await session.execute(delete(User).where(User.email == "fold0041b@example.com"))
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(cleanup())


def test_0044_data_key_family_wipe_and_drain(monkeypatch):
    """Plan 16 P3d (C7): stored AI provider keys are wiped outright; the
    remaining Fernet-sealed values are re-encrypted under the DATA_KEY
    family where the legacy JWT-derived source still decrypts them and
    cleared otherwise — never left as JWT-derived ciphertext."""
    import base64
    import hashlib
    import uuid
    from datetime import datetime

    from cryptography.fernet import Fernet, InvalidToken
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.core.config import settings
    from app.core.encryption import decrypt_secret

    legacy_secret = "legacy-jwt-secret-0123456789abcdef"
    legacy = Fernet(base64.urlsafe_b64encode(hashlib.sha256(legacy_secret.encode()).digest()))

    def sealed(plaintext: str) -> str:
        return "enc::" + legacy.encrypt(plaintext.encode()).decode()

    config = _configured()
    command.downgrade(config, "0043")

    import sqlalchemy as sa
    from sqlalchemy.dialects.postgresql import JSONB

    json_col = JSONB().with_variant(sa.JSON(), "sqlite")
    providers = sa.table(
        "ai_providers",
        sa.column("id", sa.Uuid()),
        sa.column("name", sa.String),
        sa.column("scope", sa.String),
        sa.column("user_id", sa.Uuid()),
        sa.column("provider_type", sa.String),
        sa.column("api_base", sa.String),
        sa.column("api_key_encrypted", sa.String),
        sa.column("is_active", sa.Boolean),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    app_settings = sa.table(
        "app_settings",
        sa.column("id", sa.Uuid()),
        sa.column("key", sa.String),
        sa.column("value", json_col),
        sa.column("description", sa.String),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    mcp_servers = sa.table(
        "ai_mcp_servers",
        sa.column("id", sa.Uuid()),
        sa.column("name", sa.String),
        sa.column("transport", sa.String),
        sa.column("url", sa.String),
        sa.column("command", sa.String),
        sa.column("token", sa.String),
        sa.column("enabled", sa.Boolean),
        sa.column("discovered_tools", json_col),
        sa.column("enabled_tools", json_col),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )

    now = datetime.now(UTC)
    names = {
        "settings": ["t.p3d.github", "t.p3d.vapid", "t.p3d.bogus"],
        "mcp": ["t-p3d-bridge", "t-p3d-bridge-bogus"],
        "providers": ["t-p3d-provider-sealed", "t-p3d-provider-plain"],
    }

    async def seed():
        engine = create_async_engine(settings.database_url)
        try:
            async with engine.begin() as conn:
                for name, key in zip(
                    names["providers"], (sealed("sk-secret-123"), "sk-plain-legacy"), strict=False
                ):
                    await conn.execute(
                        providers.insert().values(
                            id=uuid.uuid4(),
                            name=name,
                            scope="system",
                            user_id=None,
                            provider_type="openai_compatible",
                            api_base="https://api.openai.com/v1",
                            api_key_encrypted=key,
                            is_active=True,
                            created_at=now,
                            updated_at=now,
                        )
                    )
                await conn.execute(
                    app_settings.insert().values(
                        id=uuid.uuid4(),
                        key="t.p3d.github",
                        value={"token": sealed("ghp_legacy")},
                        created_at=now,
                        updated_at=now,
                    )
                )
                await conn.execute(
                    app_settings.insert().values(
                        id=uuid.uuid4(),
                        key="t.p3d.vapid",
                        value={
                            "public_key": "P",
                            "private_key_enc": sealed("vapid_private"),
                            "subject": "",
                        },
                        created_at=now,
                        updated_at=now,
                    )
                )
                await conn.execute(
                    app_settings.insert().values(
                        id=uuid.uuid4(),
                        key="t.p3d.bogus",
                        value={"token": "enc::not-actually-ciphertext"},
                        created_at=now,
                        updated_at=now,
                    )
                )
                await conn.execute(
                    mcp_servers.insert().values(
                        id=uuid.uuid4(),
                        name="t-p3d-bridge",
                        transport="http",
                        url="https://mcp.example/sse",
                        command="",
                        token=sealed("bridge-token"),
                        enabled=True,
                        discovered_tools=[],
                        enabled_tools=[],
                        created_at=now,
                        updated_at=now,
                    )
                )
                await conn.execute(
                    mcp_servers.insert().values(
                        id=uuid.uuid4(),
                        name="t-p3d-bridge-bogus",
                        transport="http",
                        url="https://mcp.example/sse",
                        command="",
                        token="enc::not-actually-ciphertext",
                        enabled=True,
                        discovered_tools=[],
                        enabled_tools=[],
                        created_at=now,
                        updated_at=now,
                    )
                )
        finally:
            await engine.dispose()

    asyncio.run(seed())

    monkeypatch.setenv("JWT_SECRET", legacy_secret)
    try:
        command.upgrade(config, "head")

        async def probe():
            engine = create_async_engine(settings.database_url)
            try:
                async with engine.connect() as conn:
                    provider_rows = (
                        await conn.execute(
                            sa.select(providers.c.name, providers.c.api_key_encrypted).where(
                                providers.c.name.in_(names["providers"])
                            )
                        )
                    ).fetchall()
                    setting_rows = {
                        row[0]: row[1]
                        for row in (
                            await conn.execute(
                                sa.select(app_settings.c.key, app_settings.c.value).where(
                                    app_settings.c.key.in_(names["settings"])
                                )
                            )
                        ).fetchall()
                    }
                    mcp_rows = {
                        row[0]: row[1]
                        for row in (
                            await conn.execute(
                                sa.select(mcp_servers.c.name, mcp_servers.c.token).where(
                                    mcp_servers.c.name.in_(names["mcp"])
                                )
                            )
                        ).fetchall()
                    }
                    return provider_rows, setting_rows, mcp_rows
            finally:
                await engine.dispose()

        provider_rows, setting_rows, mcp_rows = asyncio.run(probe())

        # 1. Provider keys are wiped (sealed AND legacy-plaintext alike).
        assert dict(provider_rows) == {
            "t-p3d-provider-sealed": None,
            "t-p3d-provider-plain": None,
        }

        # 2. Decryptable sealed values ride over under the DATA_KEY.
        github_token = setting_rows["t.p3d.github"]["token"]
        assert github_token.startswith("enc::")
        assert decrypt_secret(github_token) == "ghp_legacy"
        with pytest.raises(InvalidToken):
            legacy.decrypt(github_token[len("enc::") :].encode())
        vapid = setting_rows["t.p3d.vapid"]["private_key_enc"]
        assert decrypt_secret(vapid) == "vapid_private"

        # 3. Undecryptable leftovers are cleared — never JWT-derived.
        assert setting_rows["t.p3d.bogus"]["token"] == ""
        assert decrypt_secret(mcp_rows["t-p3d-bridge"]) == "bridge-token"
        assert mcp_rows["t-p3d-bridge-bogus"] is None
    finally:

        async def cleanup():
            from sqlalchemy import delete

            engine = create_async_engine(settings.database_url)
            try:
                async with engine.begin() as conn:
                    await conn.execute(
                        delete(providers).where(providers.c.name.in_(names["providers"]))
                    )
                    await conn.execute(
                        delete(app_settings).where(app_settings.c.key.in_(names["settings"]))
                    )
                    await conn.execute(
                        delete(mcp_servers).where(mcp_servers.c.name.in_(names["mcp"]))
                    )
            finally:
                await engine.dispose()

        asyncio.run(cleanup())


def test_0045_byok_uniform_realignment_roundtrip():
    """Plan 26 Phase 4 / plan 100 batch A: preset_key + decision_transport
    columns, audio→stt caps remap, default→text slot remap — all one-shot,
    reversible to the pre-wave shape."""
    import json as _json
    import uuid as _uuid

    import sqlalchemy as sa
    from sqlalchemy import text
    from sqlalchemy.dialects.postgresql import JSONB
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.core.config import settings

    _json_type = JSONB().with_variant(sa.JSON(), "sqlite")
    _uuid_type = sa.Uuid()

    def _by_id(sql: str, value):
        return text(sql).bindparams(sa.bindparam("id", value=value, type_=_uuid_type))

    _models = sa.table(
        "ai_models",
        sa.column("id", _uuid_type),
        sa.column("provider_id", _uuid_type),
        sa.column("name", sa.String),
        sa.column("model_name", sa.String),
        sa.column("is_active", sa.Boolean),
        sa.column("caps", _json_type),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    _assignments = sa.table(
        "ai_task_assignments",
        sa.column("id", _uuid_type),
        sa.column("task_type", sa.String),
        sa.column("scope", sa.String),
        sa.column("provider_id", _uuid_type),
        sa.column("is_active", sa.Boolean),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    _providers = sa.table(
        "ai_providers",
        sa.column("id", _uuid_type),
        sa.column("name", sa.String),
        sa.column("scope", sa.String),
        sa.column("provider_type", sa.String),
        sa.column("api_base", sa.String),
        sa.column("is_active", sa.Boolean),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )

    async def run(statements):
        engine = create_async_engine(settings.database_url)
        try:
            async with engine.begin() as conn:
                for statement in statements:
                    await conn.execute(statement)
        finally:
            await engine.dispose()

    async def scalar(query):
        engine = create_async_engine(settings.database_url)
        try:
            async with engine.begin() as conn:
                return (await conn.execute(query)).scalar_one()
        finally:
            await engine.dispose()

    async def read_caps():
        engine = create_async_engine(settings.database_url)
        try:
            async with engine.begin() as conn:
                raw = (
                    await conn.execute(
                        _by_id("SELECT caps FROM ai_models WHERE id = :id", model_id)
                    )
                ).scalar_one()
                return _json.loads(raw) if isinstance(raw, str) else raw
        finally:
            await engine.dispose()

    config = _configured()
    provider_id = _uuid.UUID("5eed0a45-0000-4000-8000-000000000001")
    model_id = _uuid.UUID("5eed0a45-0000-4000-8000-000000000002")
    assignment_id = _uuid.UUID("5eed0a45-0000-4000-8000-000000000003")
    try:
        command.downgrade(config, "0044")
        now = datetime.now(UTC)
        asyncio.run(
            run(
                [
                    _providers.insert().values(
                        id=provider_id,
                        name="t-0045",
                        scope="system",
                        provider_type="openai_compatible",
                        api_base="https://api.openai.com/v1",
                        is_active=True,
                        created_at=now,
                        updated_at=now,
                    ),
                    _models.insert().values(
                        id=model_id,
                        provider_id=provider_id,
                        name="whisper-x",
                        model_name="whisper-x",
                        is_active=True,
                        caps=["audio"],
                        created_at=now,
                        updated_at=now,
                    ),
                    _assignments.insert().values(
                        id=assignment_id,
                        task_type="default",
                        scope="system",
                        provider_id=provider_id,
                        is_active=True,
                        created_at=now,
                        updated_at=now,
                    ),
                ]
            )
        )

        command.upgrade(config, "0045")
        assert _column_present("ai_providers", "preset_key"), "preset_key exists at 0045"
        assert _column_present("ai_models", "decision_transport"), (
            "decision_transport exists at 0045"
        )
        assert asyncio.run(read_caps()) == ["stt"], "audio remapped to stt"
        assert (
            asyncio.run(
                scalar(
                    _by_id(
                        "SELECT task_type FROM ai_task_assignments WHERE id = :id",
                        assignment_id,
                    )
                )
            )
            == "text"
        ), "default remapped to the text slot"

        command.downgrade(config, "0044")
        assert asyncio.run(read_caps()) == ["audio"], "stt remapped back to audio"
        assert (
            asyncio.run(
                scalar(
                    text(
                        "SELECT count(*) FROM ai_task_assignments "
                        "WHERE task_type IN ('text','vision','stt','tts')"
                    )
                )
            )
            == 0
        ), "slot-vocabulary rows dropped on downgrade"
        assert not _column_present("ai_providers", "preset_key"), "downgrade drops preset_key"
        assert not _column_present("ai_models", "decision_transport"), (
            "downgrade drops decision_transport"
        )
    finally:
        command.upgrade(config, "head")
        asyncio.run(
            run(
                [
                    _by_id("DELETE FROM ai_models WHERE id = :id", model_id),
                    _by_id("DELETE FROM ai_providers WHERE id = :id", provider_id),
                ]
            )
        )


def test_0052_application_fold_and_downgrade_roundtrip():
    """Plan 113: legacy `posting_interactions` application fields fold into
    `applications`; downgrading to 0051 restores the four columns and folds
    the values back. Engagement-only rows never gain an application."""
    import uuid as _uuid

    import sqlalchemy as sa
    from sqlalchemy.dialects.postgresql import JSONB
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.core.config import settings

    _json = JSONB().with_variant(sa.JSON(), "sqlite")
    users = sa.table(
        "users",
        sa.column("id", sa.Uuid()),
        sa.column("email", sa.String),
        sa.column("password_hash", sa.String),
        sa.column("full_name", sa.String),
        sa.column("is_active", sa.Boolean),
        sa.column("is_admin", sa.Boolean),
        sa.column("failed_login_attempts", sa.Integer),
        sa.column("token_version", sa.Integer),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    sources = sa.table(
        "job_sources",
        sa.column("id", sa.Uuid()),
        sa.column("key", sa.String),
        sa.column("connector_key", sa.String),
        sa.column("config", _json),
        sa.column("sync_state", _json),
        sa.column("error", sa.String),
        sa.column("enabled", sa.Boolean),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    postings = sa.table(
        "job_postings",
        sa.column("id", sa.Uuid()),
        sa.column("source_id", sa.Uuid()),
        sa.column("external_id", sa.String),
        sa.column("ref", sa.String),
        sa.column("title", sa.String),
        sa.column("org", sa.String),
        sa.column("location", _json),
        sa.column("url", sa.String),
        sa.column("content_hash", sa.String),
        sa.column("raw", _json),
        sa.column("needs_review", sa.Boolean),
        sa.column("posting_facts", _json),
        sa.column("status", sa.String),
        sa.column("mapping_reason", sa.String),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    interactions = sa.table(
        "posting_interactions",
        sa.column("id", sa.Uuid()),
        sa.column("user_id", sa.Uuid()),
        sa.column("posting_id", sa.Uuid()),
        sa.column("seen_at", sa.DateTime(timezone=True)),
        sa.column("saved_at", sa.DateTime(timezone=True)),
        sa.column("hidden_at", sa.DateTime(timezone=True)),
        sa.column("applied_at", sa.DateTime(timezone=True)),
        sa.column("applied_via_url", sa.String),
        sa.column("stage", sa.String),
        sa.column("notes", sa.Text),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    applications = sa.table(
        "applications",
        sa.column("user_id", sa.Uuid()),
        sa.column("posting_id", sa.Uuid()),
        sa.column("stage", sa.String),
        sa.column("applied_at", sa.DateTime(timezone=True)),
        sa.column("applied_via", sa.String),
        sa.column("applied_via_url", sa.String),
        sa.column("notes", sa.Text),
    )

    config = _configured()
    command.downgrade(config, "0050")

    run_id = _uuid.uuid4().hex[:8]
    user_id = _uuid.uuid4()
    source_id = _uuid.uuid4()
    applied_posting = _uuid.uuid4()
    seen_posting = _uuid.uuid4()
    applied_interaction = _uuid.uuid4()
    seen_interaction = _uuid.uuid4()
    now = datetime.now(UTC)
    email = f"fold0052-{run_id}@example.com"
    source_key = f"fold-0052-{run_id}"

    async def run(statements):
        engine = create_async_engine(settings.database_url)
        try:
            async with engine.begin() as conn:
                for statement in statements:
                    await conn.execute(statement)
        finally:
            await engine.dispose()

    async def read_applications():
        engine = create_async_engine(settings.database_url)
        try:
            async with engine.begin() as conn:
                rows = await conn.execute(
                    sa.select(
                        applications.c.posting_id,
                        applications.c.stage,
                        applications.c.applied_at,
                        applications.c.applied_via,
                        applications.c.applied_via_url,
                        applications.c.notes,
                    ).where(applications.c.user_id == user_id)
                )
                return {row.posting_id: row for row in rows.all()}
        finally:
            await engine.dispose()

    async def read_interactions():
        engine = create_async_engine(settings.database_url)
        try:
            async with engine.begin() as conn:
                rows = await conn.execute(
                    sa.select(
                        interactions.c.posting_id,
                        interactions.c.stage,
                        interactions.c.applied_at,
                        interactions.c.applied_via_url,
                        interactions.c.notes,
                    ).where(interactions.c.user_id == user_id)
                )
                return {row.posting_id: row for row in rows.all()}
        finally:
            await engine.dispose()

    try:
        asyncio.run(
            run(
                [
                    users.insert().values(
                        id=user_id,
                        email=email,
                        password_hash="$2b$12$foldmigrationplaceholder",
                        full_name="",
                        is_active=True,
                        is_admin=False,
                        failed_login_attempts=0,
                        token_version=1,
                        created_at=now,
                        updated_at=now,
                    ),
                    sources.insert().values(
                        id=source_id,
                        key=source_key,
                        connector_key="ats_api",
                        config={},
                        sync_state={},
                        error="",
                        enabled=True,
                        created_at=now,
                        updated_at=now,
                    ),
                    *[
                        postings.insert().values(
                            id=posting_id,
                            source_id=source_id,
                            external_id=f"{source_key}-{index}",
                            ref=f"F{index}{run_id}"[:8],
                            title="Fold posting",
                            org="Fold Co",
                            location={},
                            url="",
                            content_hash=f"fold-hash-{run_id}-{index}",
                            raw={},
                            needs_review=False,
                            posting_facts={},
                            status="new",
                            mapping_reason="",
                            created_at=now,
                            updated_at=now,
                        )
                        for index, posting_id in enumerate((applied_posting, seen_posting))
                    ],
                    interactions.insert().values(
                        id=applied_interaction,
                        user_id=user_id,
                        posting_id=applied_posting,
                        seen_at=now,
                        saved_at=now,
                        hidden_at=None,
                        applied_at=now,
                        applied_via_url="https://jobs.example/fold",
                        stage="interview",
                        notes="legacy note",
                        created_at=now,
                        updated_at=now,
                    ),
                    interactions.insert().values(
                        id=seen_interaction,
                        user_id=user_id,
                        posting_id=seen_posting,
                        seen_at=now,
                        saved_at=None,
                        hidden_at=None,
                        applied_at=None,
                        applied_via_url="",
                        stage=None,
                        notes="",
                        created_at=now,
                        updated_at=now,
                    ),
                ]
            )
        )

        command.upgrade(config, "head")

        folded = asyncio.run(read_applications())
        assert set(folded) == {applied_posting}, "only application rows are folded"
        row = folded[applied_posting]
        assert row.stage == "interview"
        assert row.applied_via == "url"
        assert row.applied_via_url == "https://jobs.example/fold"
        assert row.notes == "legacy note"
        assert row.applied_at is not None

        command.downgrade(config, "0051")
        restored = asyncio.run(read_interactions())
        assert restored[applied_posting].stage == "interview"
        assert restored[applied_posting].applied_via_url == "https://jobs.example/fold"
        assert restored[applied_posting].notes == "legacy note"
        assert restored[applied_posting].applied_at is not None
        assert restored[seen_posting].stage is None
        assert restored[seen_posting].applied_via_url == ""
        assert asyncio.run(read_applications()), "0052 downgrade keeps the 0051 shape"
    finally:
        command.upgrade(config, "head")
        asyncio.run(
            run(
                [
                    sa.text(
                        "DELETE FROM applications WHERE user_id IN "
                        "(SELECT id FROM users WHERE email = :email)"
                    ).bindparams(email=email),
                    sa.text(
                        "DELETE FROM posting_interactions WHERE user_id IN "
                        "(SELECT id FROM users WHERE email = :email)"
                    ).bindparams(email=email),
                    sa.text(
                        "DELETE FROM job_postings WHERE source_id IN "
                        "(SELECT id FROM job_sources WHERE key = :key)"
                    ).bindparams(key=source_key),
                    sa.text("DELETE FROM job_sources WHERE key = :key").bindparams(key=source_key),
                    sa.text("DELETE FROM users WHERE email = :email").bindparams(email=email),
                ]
            )
        )


def test_0047_job_source_secrets_roundtrip():
    """Plan 32 Phase 1 / ADR-0040 D19: the secrets column lands and the one
    legacy plaintext credential (ats ``config.api_token``) is MOVED — sealed
    into the slot, stripped from config."""
    import uuid as _uuid

    import sqlalchemy as sa
    from sqlalchemy import text
    from sqlalchemy.dialects.postgresql import JSONB
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.core.config import settings
    from app.core.encryption import ENCRYPTED_PREFIX, decrypt_secret

    _json_type = JSONB().with_variant(sa.JSON(), "sqlite")
    _uuid_type = sa.Uuid()
    _sources = sa.table(
        "job_sources",
        sa.column("id", _uuid_type),
        sa.column("key", sa.String),
        sa.column("connector_key", sa.String),
        sa.column("config", _json_type),
        sa.column("sync_state", _json_type),
        sa.column("error", sa.String),
        sa.column("enabled", sa.Boolean),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )

    source_id = _uuid.UUID("5eed0a45-0000-4000-8000-000000000047")

    def _by_id(sql: str):
        return text(sql).bindparams(sa.bindparam("id", value=source_id, type_=_uuid_type))

    async def run(statements):
        engine = create_async_engine(settings.database_url)
        try:
            async with engine.begin() as conn:
                for statement in statements:
                    await conn.execute(statement)
        finally:
            await engine.dispose()

    async def read_row():
        engine = create_async_engine(settings.database_url)
        try:
            async with engine.begin() as conn:
                row = (
                    await conn.execute(
                        _by_id("SELECT config, secrets FROM job_sources WHERE id = :id")
                    )
                ).first()
                import json as _json

                def _load(value):
                    return _json.loads(value) if isinstance(value, str) else value

                return (_load(row[0]), _load(row[1])) if row else (None, None)
        finally:
            await engine.dispose()

    config = _configured()
    try:
        command.downgrade(config, "0046")
        now = datetime.now(UTC)
        asyncio.run(
            run(
                [
                    _sources.insert().values(
                        id=source_id,
                        key="t-0047",
                        connector_key="ats_api",
                        config={
                            "provider": "greenhouse",
                            "org": "acme",
                            "api_token": "ghp-plaintext-token-1234",
                        },
                        sync_state={},
                        error="",
                        enabled=True,
                        created_at=now,
                        updated_at=now,
                    ),
                ]
            )
        )

        command.upgrade(config, "0047")
        assert _column_present("job_sources", "secrets"), "secrets column exists at 0047"
        stored_config, secrets = asyncio.run(read_row())
        assert "api_token" not in stored_config, "plaintext token stripped from config"
        sealed = secrets.get("api_token", "")
        assert sealed.startswith(ENCRYPTED_PREFIX), "token sealed at rest"
        assert decrypt_secret(sealed) == "ghp-plaintext-token-1234", "sealed value round-trips"

        command.downgrade(config, "0046")
        assert not _column_present("job_sources", "secrets"), "downgrade drops secrets"
    finally:
        command.upgrade(config, "head")
        asyncio.run(run([_by_id("DELETE FROM job_sources WHERE id = :id")]))


def test_populated_sqlite_upgrades_0050_to_head(tmp_path, monkeypatch):
    """Plan 122 commit-zero: a POPULATED SQLite (desktop) database must
    upgrade 0050 → head.

    0051 adds NOT NULL columns to pre-existing tables via batch rebuilds;
    SQLite copies every row into `_alembic_tmp_*` before swapping, so a
    NOT NULL column without a server default that survives the rebuild
    fails the copy (`career_path_steps.edge_label`,
    `profile_proposals.origin`). Fresh databases and CI never populate the
    table first, which is why the defect escaped plan 113.
    """
    import uuid as _uuid

    import sqlalchemy as sa
    from sqlalchemy.dialects.postgresql import JSONB
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.core.config import settings

    db_url = f"sqlite+aiosqlite:///{tmp_path / 'populated.db'}"
    monkeypatch.setenv("CAREER_DATABASE_URL", db_url)
    monkeypatch.setattr(settings, "database_url", db_url, raising=False)

    _json = JSONB().with_variant(sa.JSON(), "sqlite")
    _uuid_type = sa.Uuid()
    users = sa.table(
        "users",
        sa.column("id", _uuid_type),
        sa.column("email", sa.String),
        sa.column("password_hash", sa.String),
        sa.column("full_name", sa.String),
        sa.column("is_active", sa.Boolean),
        sa.column("is_admin", sa.Boolean),
        sa.column("failed_login_attempts", sa.Integer),
        sa.column("token_version", sa.Integer),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    sources = sa.table(
        "job_sources",
        sa.column("id", _uuid_type),
        sa.column("key", sa.String),
        sa.column("connector_key", sa.String),
        sa.column("kind", sa.String),
        sa.column("last_status", sa.String),
        sa.column("config", _json),
        sa.column("sync_state", _json),
        sa.column("error", sa.String),
        sa.column("enabled", sa.Boolean),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    steps = sa.table(
        "career_path_steps",
        sa.column("id", _uuid_type),
        sa.column("path_id", _uuid_type),
        sa.column("position", sa.Integer),
        sa.column("kind", sa.String),
        sa.column("label", sa.String),
        sa.column("edge_label", sa.String),
        sa.column("optional", sa.Boolean),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    proposals = sa.table(
        "profile_proposals",
        sa.column("id", _uuid_type),
        sa.column("user_id", _uuid_type),
        sa.column("kind", sa.String),
        sa.column("action", sa.String),
        sa.column("entity_label", sa.String),
        sa.column("payload_json", _json),
        sa.column("diff_json", _json),
        sa.column("status", sa.String),
        sa.column("source", sa.String),
        sa.column("origin", _json),
        sa.column("resolve_error", sa.String),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    fits = sa.table(
        "posting_fits",
        sa.column("id", _uuid_type),
        sa.column("user_id", _uuid_type),
        sa.column("posting_id", _uuid_type),
        sa.column("score", sa.Numeric(4, 2)),
        sa.column("breakdown", _json),
        sa.column("inputs_hash", sa.String),
        sa.column("computed_at", sa.DateTime(timezone=True)),
        sa.column("fit_version", sa.Integer),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    interactions = sa.table(
        "posting_interactions",
        sa.column("id", _uuid_type),
        sa.column("user_id", _uuid_type),
        sa.column("posting_id", _uuid_type),
        sa.column("applied_at", sa.DateTime(timezone=True)),
        sa.column("applied_via_url", sa.String),
        sa.column("stage", sa.String),
        sa.column("notes", sa.Text),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    applications = sa.table(
        "applications",
        sa.column("user_id", _uuid_type),
        sa.column("posting_id", _uuid_type),
        sa.column("stage", sa.String),
        sa.column("notes", sa.Text),
    )

    user_id = _uuid.uuid4()
    source_id = _uuid.uuid4()
    step_id = _uuid.uuid4()
    proposal_id = _uuid.uuid4()
    posting_id = _uuid.uuid4()

    async def run(statements):
        engine = create_async_engine(db_url)
        try:
            async with engine.begin() as conn:
                for statement in statements:
                    await conn.execute(statement)
        finally:
            await engine.dispose()

    async def read(statement):
        engine = create_async_engine(db_url)
        try:
            async with engine.begin() as conn:
                return (await conn.execute(statement)).all()
        finally:
            await engine.dispose()

    config = _configured()
    command.upgrade(config, "0050")
    now = datetime.now(UTC)
    asyncio.run(
        run(
            [
                users.insert().values(
                    id=user_id,
                    email="populated-0051@example.com",
                    password_hash="$2b$12$populatedmigrationplaceholder",
                    full_name="",
                    is_active=True,
                    is_admin=False,
                    failed_login_attempts=0,
                    token_version=1,
                    created_at=now,
                    updated_at=now,
                ),
                sources.insert().values(
                    id=source_id,
                    key="populated-0051",
                    connector_key="rss",
                    config={"url": "https://example.org/feed.xml"},
                    sync_state={"watermark": "2026-01-01T00:00:00+00:00"},
                    error="",
                    enabled=True,
                    created_at=now,
                    updated_at=now,
                ),
                steps.insert().values(
                    id=step_id,
                    path_id=_uuid.uuid4(),
                    position=0,
                    kind="skill",
                    label="Keep me",
                    optional=False,
                    created_at=now,
                    updated_at=now,
                ),
                proposals.insert().values(
                    id=proposal_id,
                    user_id=user_id,
                    kind="experience_item",
                    action="create",
                    entity_label="Populated proposal",
                    payload_json={"title": "Engineer"},
                    diff_json=[],
                    status="pending",
                    source="chat",
                    resolve_error="",
                    created_at=now,
                    updated_at=now,
                ),
                fits.insert().values(
                    id=_uuid.uuid4(),
                    user_id=user_id,
                    posting_id=posting_id,
                    score=7.5,
                    breakdown={},
                    inputs_hash="populated",
                    created_at=now,
                    updated_at=now,
                ),
                interactions.insert().values(
                    id=_uuid.uuid4(),
                    user_id=user_id,
                    posting_id=posting_id,
                    applied_at=now,
                    applied_via_url="https://example.org/apply",
                    stage="interview",
                    notes="populated note",
                    created_at=now,
                    updated_at=now,
                ),
            ]
        )
    )

    command.upgrade(config, "head")

    step_rows = asyncio.run(
        read(sa.select(steps.c.label, steps.c.edge_label).where(steps.c.id == step_id))
    )
    assert step_rows == [("Keep me", "")], "the populated step survives with an empty edge label"

    proposal_rows = asyncio.run(
        read(sa.select(proposals.c.source, proposals.c.origin).where(proposals.c.id == proposal_id))
    )
    assert proposal_rows[0][0] == "chat"
    assert proposal_rows[0][1] == {}, "the populated proposal keeps an empty origin object"

    source_rows = asyncio.run(
        read(sa.select(sources.c.kind, sources.c.last_status).where(sources.c.id == source_id))
    )
    assert source_rows == [("posting", "ok")], "source kind/health defaults fill the populated row"

    fit_rows = asyncio.run(
        read(sa.select(fits.c.computed_at, fits.c.fit_version).where(fits.c.user_id == user_id))
    )
    assert fit_rows[0][0] is not None, "computed_at is backfilled from updated_at"
    assert fit_rows[0][1] == 5, "fit_version is backfilled"

    folded = asyncio.run(
        read(
            sa.select(applications.c.stage, applications.c.notes).where(
                applications.c.user_id == user_id
            )
        )
    )
    assert folded == [("interview", "populated note")], "0052 folds the application fields"


def test_0053_demand_import_task_check_roundtrip():
    """Plan 122 phase 3: the dormant demand-import schedule kind gains its
    task value; downgrade restores the previous CHECK."""
    config = _configured()
    command.upgrade(config, "head")
    assert "demand_import" in _schedules_checks()["task_allowed"]

    command.downgrade(config, "0052")
    assert "demand_import" not in _schedules_checks()["task_allowed"]

    command.upgrade(config, "head")
    assert "demand_import" in _schedules_checks()["task_allowed"]


_ECON_TABLES = [
    "geo_regions",
    "geo_region_aliases",
    "econ_packs",
    "econ_series",
    "econ_observations",
    "code_crosswalks",
    "exposure_scores",
    "scenarios",
    "scenario_points",
    "claims",
    "claim_events",
    "econ_watchlist",
]


def test_0054_econ_context_tables_roundtrip():
    """Plan 127 §3.0: the economic-context tables land at head and
    downgrade removes exactly what the revision added."""
    config = _configured()
    command.upgrade(config, "head")
    for table in _ECON_TABLES:
        assert _table_present(table), f"{table} exists at head"

    command.downgrade(config, "0053")
    for table in _ECON_TABLES:
        assert not _table_present(table), f"{table} dropped on downgrade"

    command.upgrade(config, "head")
    for table in _ECON_TABLES:
        assert _table_present(table), f"{table} exists after re-upgrade"


def test_0055_company_profiles_roundtrip():
    """Plan 129 phase 1: the reviewed company-profiles layer lands at
    head and downgrade removes it (family-migration §3)."""
    config = _configured()
    command.upgrade(config, "head")
    assert _table_present("company_profiles"), "company_profiles exists at head"

    command.downgrade(config, "0054")
    assert not _table_present("company_profiles"), "company_profiles dropped on downgrade"

    command.upgrade(config, "head")
    assert _table_present("company_profiles"), "company_profiles exists after re-upgrade"


def test_0056_salary_normalization_backfill():
    """Plan 129 phase 2: rows with a known period annualize on (re)upgrade;
    the basis stays NULL for existing rows — the source's wording is gone
    and unknown is never guessed."""
    import asyncio

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.core.config import settings
    from app.models.posting_model import JobPosting, JobSource

    config = _configured()
    command.upgrade(config, "head")

    async def seed():
        engine = create_async_engine(settings.database_url)
        maker = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with maker() as session:
                # Idempotent: a previous run's rows persist in the worker DB.
                await session.execute(
                    text("DELETE FROM job_postings WHERE external_id = 'sal-norm-1'")
                )
                await session.execute(text("DELETE FROM job_sources WHERE key = 'sal-norm'"))
                source = JobSource(key="sal-norm", connector_key="csv")
                session.add(source)
                await session.flush()
                session.add(
                    JobPosting(
                        source_id=source.id,
                        external_id="sal-norm-1",
                        title="Analyst",
                        content_hash="sal-norm-1",
                        salary_currency="EUR",
                        salary_min=3000,
                        salary_max=4500,
                        salary_period="month",
                    )
                )
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(seed())

    async def cleanup():
        engine = create_async_engine(settings.database_url)
        try:
            async with engine.begin() as conn:
                # Worker DBs persist across runs and the app-test world
                # rolls back its own writes but sees committed ones —
                # this test's rows must never outlive it, even on failure.
                await conn.execute(
                    text("DELETE FROM job_postings WHERE external_id = 'sal-norm-1'")
                )
                await conn.execute(text("DELETE FROM job_sources WHERE key = 'sal-norm'"))
        finally:
            await engine.dispose()

    try:

        async def reset_normalized():
            engine = create_async_engine(settings.database_url)
            try:
                async with engine.begin() as conn:
                    await conn.execute(
                        text(
                            "UPDATE job_postings SET salary_normalized_min = NULL, "
                            "salary_normalized_max = NULL"
                        )
                    )
            finally:
                await engine.dispose()

        asyncio.run(reset_normalized())

        command.downgrade(config, "0055")
        command.upgrade(config, "head")

        async def assert_backfilled():
            engine = create_async_engine(settings.database_url)
            try:
                async with engine.connect() as conn:
                    row = (
                        await conn.execute(
                            text(
                                "SELECT salary_normalized_min, salary_normalized_max, salary_basis "
                                "FROM job_postings WHERE external_id = 'sal-norm-1'"
                            )
                        )
                    ).one()
            finally:
                await engine.dispose()
            assert (float(row[0]), float(row[1]), row[2]) == (36000.0, 54000.0, None)

        asyncio.run(assert_backfilled())
    finally:
        asyncio.run(cleanup())


def test_0057_job_radars_roundtrip():
    """Plan 129 phase 4a: the job radar lands at head and downgrade
    removes it."""
    config = _configured()
    command.upgrade(config, "head")
    assert _table_present("job_radars"), "job_radars exists at head"

    command.downgrade(config, "0056")
    assert not _table_present("job_radars"), "job_radars dropped on downgrade"

    command.upgrade(config, "head")
    assert _table_present("job_radars"), "job_radars exists after re-upgrade"


def test_0058_radar_digest_check_roundtrip():
    """Plan 129 phase 4b: the radar-digest schedule kind + task widen
    both CHECKs; downgrade restores the previous text and deletes the
    un-representable rows (the 0053 recipe, both constraints)."""
    config = _configured()
    command.upgrade(config, "head")
    checks = _schedules_checks()
    assert "user_radar_digest" in checks["kind_allowed"]
    assert "radar_digest" in checks["task_allowed"]

    command.downgrade(config, "0057")
    checks = _schedules_checks()
    assert "user_radar_digest" not in checks["kind_allowed"]
    assert "radar_digest" not in checks["task_allowed"]

    command.upgrade(config, "head")
    checks = _schedules_checks()
    assert "user_radar_digest" in checks["kind_allowed"]
    assert "radar_digest" in checks["task_allowed"]


def test_0084_smart_digest_schedule_roundtrip():
    """Plan 179: the smart-digest schedule kind + task widen both CHECKs
    (the 0058 recipe); the downgrade restores the previous text."""
    config = _configured()
    command.upgrade(config, "head")
    checks = _schedules_checks()
    assert "user_smart_digest" in checks["kind_allowed"]
    assert "smart_digest" in checks["task_allowed"]

    command.downgrade(config, "0083")
    checks = _schedules_checks()
    assert "user_smart_digest" not in checks["kind_allowed"]
    assert "smart_digest" not in checks["task_allowed"]

    command.upgrade(config, "head")
    checks = _schedules_checks()
    assert "user_smart_digest" in checks["kind_allowed"]
    assert "smart_digest" in checks["task_allowed"]


def test_0085_job_requeue_of_roundtrip():
    """Plan 184: the requeue marker column + its index exist at head and
    die on the downgrade (marker data is auxiliary audit data — its loss
    is documented in the migration)."""
    config = _configured()
    command.upgrade(config, "head")
    assert _column_present("background_jobs", "requeue_of"), "requeue marker exists at head"
    assert _index_present("background_jobs", "ix_background_jobs_requeue_of")

    command.downgrade(config, "0084")
    assert not _column_present("background_jobs", "requeue_of"), "downgrade drops the marker"
    assert not _index_present("background_jobs", "ix_background_jobs_requeue_of")

    command.upgrade(config, "head")
    assert _column_present("background_jobs", "requeue_of"), "re-upgrade restores the marker"
    assert _index_present("background_jobs", "ix_background_jobs_requeue_of")


def _job_sources_shape() -> tuple[set[str], dict[str, str]]:
    """(column names, short-name CHECK texts) of `job_sources` (dialect-safe)."""

    async def run():
        from sqlalchemy import inspect
        from sqlalchemy.ext.asyncio import create_async_engine

        from app.core.config import settings

        engine = create_async_engine(settings.database_url)
        try:
            async with engine.connect() as conn:

                def read(sync_conn):
                    insp = inspect(sync_conn)
                    columns = {c["name"] for c in insp.get_columns("job_sources")}
                    checks = {
                        c["name"].replace("ck_job_sources_", ""): c["sqltext"]
                        for c in insp.get_check_constraints("job_sources")
                    }
                    return columns, checks

                return await conn.run_sync(read)
        finally:
            await engine.dispose()

    import asyncio

    return asyncio.run(run())


def test_0059_query_mode_roundtrip():
    """Plan 130: job_sources gains query_mode (+ its CHECK) and the
    query_cache JSONB; downgrade drops the constraint and both columns."""
    config = _configured()
    command.upgrade(config, "head")
    columns, checks = _job_sources_shape()
    assert "query_mode" in columns and "query_cache" in columns
    assert "'static'" in checks["query_mode_allowed"] and "'radar'" in checks["query_mode_allowed"]

    command.downgrade(config, "0058")
    columns, checks = _job_sources_shape()
    assert "query_mode" not in columns and "query_cache" not in columns
    assert "query_mode_allowed" not in checks

    command.upgrade(config, "head")
    columns, checks = _job_sources_shape()
    assert "query_mode" in columns and "query_cache" in columns
    assert "query_mode_allowed" in checks


def _seed_cleanup(like: str) -> None:
    """Migration data seeds run on a SEPARATE engine — real commits the
    suite's per-test rollback never sees. They must clean up after
    themselves or they leak into other tests on the same worker."""

    async def _run():
        from sqlalchemy import delete
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from app.core.config import settings
        from app.models.posting_model import JobSource

        engine = create_async_engine(settings.database_url)
        try:
            session = async_sessionmaker(engine, expire_on_commit=False)()
            async with session:
                await session.execute(delete(JobSource).where(JobSource.key.like(like)))
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(_run())


def _fold_seed() -> None:
    """Three sources at the 0061 shape: bool on, bool off, no key."""

    async def _run():
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from app.core.config import settings
        from app.models.posting_model import JobSource

        engine = create_async_engine(settings.database_url)
        try:
            session = async_sessionmaker(engine, expire_on_commit=False)()
            async with session:
                from sqlalchemy import delete

                await session.execute(delete(JobSource).where(JobSource.key.like("fold-%")))
                await _seed_legacy_source(
                    session, engine, "fold-sample", {"keywords": "x", "fetch_details": True}
                )
                await _seed_legacy_source(
                    session, engine, "fold-off", {"keywords": "x", "fetch_details": False}
                )
                await _seed_legacy_source(session, engine, "fold-plain", {"keywords": "x"})
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(_run())


async def _seed_legacy_source(
    session, engine, key: str, config: dict, connector_key: str = "synthetic"
) -> str:
    """One job_sources row at its pre-0080 shape — raw SQL with an explicit
    legacy column list: the ORM flush renders the model's full column set
    (plan 173's `title` included) and the downgraded table predates it.
    Returns the seeded row's id."""
    import json
    import uuid as _uuid

    from sqlalchemy import text

    is_postgres = engine.dialect.name == "postgresql"
    cast = (
        (lambda param: f"CAST(:{param} AS jsonb)") if is_postgres else (lambda param: f":{param}")
    )
    row_id = str(_uuid.uuid4())
    await session.execute(
        text(
            "INSERT INTO job_sources "
            "(id, key, connector_key, kind, config, secrets, sync_state, error, enabled) "
            "VALUES (:id, :key, :connector_key, 'posting', "
            f"{cast('config')}, {cast('secrets')}, {cast('sync_state')}, '', true)"
        ),
        {
            "id": row_id,
            "key": key,
            "connector_key": connector_key,
            "config": json.dumps(config),
            "secrets": "{}",
            "sync_state": "{}",
        },
    )
    return row_id


def _fold_read() -> dict[str, dict]:
    import json

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    async def _run():
        from app.core.config import settings

        engine = create_async_engine(settings.database_url)
        try:
            async with engine.connect() as conn:
                rows = (
                    await conn.execute(
                        text("SELECT key, config FROM job_sources WHERE key LIKE 'fold-%'")
                    )
                ).fetchall()
        finally:
            await engine.dispose()
        out = {}
        for key, config in rows:
            if isinstance(config, str):
                config = json.loads(config)
            out[key] = dict(config or {})
        return out

    return asyncio.run(_run())


def test_0062_detail_enrichment_fold():
    config = _configured()

    try:
        command.upgrade(config, "head")
        assert _column_present("job_postings", "detail_fetched_at"), "detail state at head"
        assert _column_present("job_postings", "detail_attempts"), "detail attempts at head"

        command.downgrade(config, "0061")
        assert not _column_present("job_postings", "detail_fetched_at"), "downgrade drops it"
        _fold_seed()

        command.upgrade(config, "head")
        configs = _fold_read()
        assert configs["fold-sample"] == {"keywords": "x", "detail_mode": "sample"}
        assert configs["fold-off"] == {"keywords": "x", "detail_mode": "off"}
        assert configs["fold-plain"] == {"keywords": "x"}
    finally:
        _seed_cleanup("fold-%")


def _timeout_seed() -> None:
    """Minted default (30), a deliberate value (60), and a non-mcp row."""

    async def _run():
        from sqlalchemy import delete
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from app.core.config import settings
        from app.models.posting_model import JobSource

        engine = create_async_engine(settings.database_url)
        try:
            session = async_sessionmaker(engine, expire_on_commit=False)()
            async with session:
                await session.execute(delete(JobSource).where(JobSource.key.like("timeout-%")))
                await _seed_legacy_source(
                    session,
                    engine,
                    "timeout-mint",
                    {"tool": "fetch_postings", "timeout_seconds": 30},
                    connector_key="mcp",
                )
                await _seed_legacy_source(
                    session,
                    engine,
                    "timeout-kept",
                    {"timeout_seconds": 60},
                    connector_key="mcp",
                )
                await _seed_legacy_source(
                    session,
                    engine,
                    "timeout-other",
                    {"timeout_seconds": 30},
                )
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(_run())


def _timeout_read() -> dict[str, int]:
    import json

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    async def _run():
        from app.core.config import settings

        engine = create_async_engine(settings.database_url)
        try:
            async with engine.connect() as conn:
                rows = (
                    await conn.execute(
                        text("SELECT key, config FROM job_sources WHERE key LIKE 'timeout-%'")
                    )
                ).fetchall()
        finally:
            await engine.dispose()
        out = {}
        for key, config in rows:
            if isinstance(config, str):
                config = json.loads(config)
            out[key] = dict(config or {}).get("timeout_seconds")
        return out

    return asyncio.run(_run())


def test_0063_timeout_fold():
    config = _configured()

    try:
        command.upgrade(config, "head")
        command.downgrade(config, "0062")
        _timeout_seed()

        command.upgrade(config, "head")
        timeouts = _timeout_read()
        assert timeouts["timeout-mint"] == 120, "the minted default moves to 120"
        assert timeouts["timeout-kept"] == 60, "a deliberate value stays"
        assert timeouts["timeout-other"] == 30, "non-mcp rows are untouched"
    finally:
        _seed_cleanup("timeout-%")


def _status_probe_source() -> str:
    """A throwaway source row (runs need a source to attach to)."""

    async def _run():
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from app.core.config import settings
        from app.models.posting_model import JobSource

        engine = create_async_engine(settings.database_url)
        try:
            session = async_sessionmaker(engine, expire_on_commit=False)()
            async with session:
                row = JobSource(
                    key="status-probe", connector_key="synthetic", kind="posting", config={}
                )
                session.add(row)
                await session.commit()
                return str(row.id)
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def _run_status_accepted(status: str, source_id: str) -> bool:
    import uuid

    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.ext.asyncio import create_async_engine

    async def _run():
        from app.core.config import settings

        engine = create_async_engine(settings.database_url)
        try:
            try:
                async with engine.begin() as conn:
                    await conn.execute(
                        text(
                            "INSERT INTO source_runs (id, source_id, trigger, status,"
                            " duration_ms, items_synced, error, created_at, updated_at)"
                            " VALUES (:id, :src, 'manual', :status, 0, 0, '',"
                            " CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                        ),
                        {"id": str(uuid.uuid4()), "src": source_id, "status": status},
                    )
                    await conn.execute(
                        text("DELETE FROM source_runs WHERE status = :status"),
                        {"status": status},
                    )
                return True
            except IntegrityError:
                return False
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def test_0064_running_status_roundtrip():
    config = _configured()

    try:
        command.upgrade(config, "head")
        source_id = _status_probe_source()
        assert _run_status_accepted("running", source_id), "head accepts a running row"

        command.downgrade(config, "0063")
        assert not _run_status_accepted("running", source_id), "downgrade drops the vocabulary"

        command.upgrade(config, "head")
        assert _run_status_accepted("running", source_id), "re-upgrade restores it"
    finally:
        _seed_cleanup("status-probe%")


def _org135_seed() -> None:
    """Two organizations at the pre-0070 shape (aliases JSONB, no match keys)."""

    async def _run():
        import json
        import uuid as _uuid
        from datetime import datetime

        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from app.core.config import settings

        engine = create_async_engine(settings.database_url)
        try:
            session = async_sessionmaker(engine, expire_on_commit=False)()
            async with session:
                await session.execute(text("DELETE FROM organizations WHERE key LIKE 'fold135-%'"))
                aliases_sql = (
                    "CAST(:aliases AS jsonb)" if engine.dialect.name == "postgresql" else ":aliases"
                )
                for key, name, aliases in [
                    ("fold135-pg", "P&G", ["Procter & Gamble", "P&G GmbH"]),
                    ("fold135-plain", "Acme Cloud GmbH", []),
                ]:
                    await session.execute(
                        text(
                            "INSERT INTO organizations "
                            "(id, key, name, aliases, status, provenance, created_at, updated_at) "
                            f"VALUES (:id, :key, :name, {aliases_sql},"
                            " 'active', '{}', :now, :now)"
                        ),
                        {
                            "id": str(_uuid.uuid4()),
                            "key": key,
                            "name": name,
                            "aliases": json.dumps(aliases),
                            "now": datetime.now(UTC),
                        },
                    )
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(_run())


def _org135_cleanup() -> None:
    """Fold rows are real commits — children first, then the orgs."""

    async def _run():
        from contextlib import suppress

        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from app.core.config import settings

        engine = create_async_engine(settings.database_url)
        try:
            session = async_sessionmaker(engine, expire_on_commit=False)()
            async with session:
                child_deletes = [
                    "DELETE FROM organization_aliases WHERE org_id IN "
                    "(SELECT id FROM organizations WHERE key LIKE 'fold135-%')",
                    "DELETE FROM organization_match_exclusions WHERE org_id IN "
                    "(SELECT id FROM organizations WHERE key LIKE 'fold135-%')",
                    "DELETE FROM organization_match_pairs WHERE org_id IN "
                    "(SELECT id FROM organizations WHERE key LIKE 'fold135-%')",
                    "DELETE FROM organization_merge_suggestions WHERE org_a IN "
                    "(SELECT id FROM organizations WHERE key LIKE 'fold135-%') "
                    "OR org_b IN (SELECT id FROM organizations WHERE key LIKE 'fold135-%')",
                ]
                for stmt in child_deletes:
                    try:
                        await session.execute(text(stmt))
                    except Exception:
                        await session.rollback()
                with suppress(Exception):
                    await session.execute(
                        text("DELETE FROM organizations WHERE key LIKE 'fold135-%'")
                    )
                    await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(_run())


def _org135_read() -> dict[str, dict]:

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.core.config import settings

    async def _run():
        engine = create_async_engine(settings.database_url)
        try:
            async with engine.connect() as conn:
                orgs = (
                    await conn.execute(
                        text(
                            "SELECT key, name_key, initials_key FROM organizations "
                            "WHERE key LIKE 'fold135-%'"
                        )
                    )
                ).fetchall()
                aliases = (
                    await conn.execute(
                        text(
                            "SELECT o.key, a.alias, a.alias_key, a.source, a.state "
                            "FROM organization_aliases a "
                            "JOIN organizations o ON o.id = a.org_id "
                            "WHERE o.key LIKE 'fold135-%' ORDER BY a.created_at"
                        )
                    )
                ).fetchall()
        finally:
            await engine.dispose()
        out: dict[str, dict] = {}
        for key, name_key, initials_key in orgs:
            out[key] = {"name_key": name_key, "initials_key": initials_key, "aliases": []}
        for key, alias, alias_key, source, state in aliases:
            out[key]["aliases"].append(
                {"alias": alias, "alias_key": alias_key, "source": source, "state": state}
            )
        return out

    return asyncio.run(_run())


def test_0070_company_entity_resolution_fold():
    config = _configured()

    try:
        command.upgrade(config, "head")
        command.downgrade(config, "0069")
        assert not _column_present("job_postings", "org_match"), "downgrade drops org_match"
        _org135_seed()

        command.upgrade(config, "head")
        assert not _column_present("organizations", "aliases"), "aliases JSONB folded away"
        assert _column_present("job_postings", "org_match"), "org_match provenance at head"
        rows = _org135_read()
        pg = rows["fold135-pg"]
        assert pg["name_key"] == "p g", "P&G canonicalizes to its tokens"
        assert pg["initials_key"] == "pg", "P&G initials"
        aliases = {a["alias"]: a for a in pg["aliases"]}
        assert set(aliases) == {"Procter & Gamble", "P&G GmbH"}, "both aliases folded"
        assert all(a["source"] == "legacy" for a in aliases.values())
        assert aliases["Procter & Gamble"]["alias_key"] == "procter gamble"
        plain = rows["fold135-plain"]
        assert plain["aliases"] == []
        assert plain["name_key"] == "acme cloud", "legal suffix stripped from the key"
    finally:
        _org135_cleanup()


def test_0070_denylist_seeds_as_rows():
    config = _configured()

    async def _count():
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine

        from app.core.config import settings

        engine = create_async_engine(settings.database_url)
        try:
            async with engine.connect() as conn:
                row = (
                    await conn.execute(
                        text(
                            "SELECT count(*) FROM organization_match_exclusions "
                            "WHERE source = 'seed' AND label_key = 'confidential'"
                        )
                    )
                ).scalar_one()
        finally:
            await engine.dispose()
        return int(row)

    command.upgrade(config, "head")
    assert asyncio.run(_count()) == 1, "the quality denylist seeds as editable rows"


def _om_state_seed() -> None:
    """One posting at the 0070 shape (org_match JSONB, no state column)."""

    async def _run():
        import json
        import uuid as _uuid
        from datetime import datetime

        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from app.core.config import settings

        engine = create_async_engine(settings.database_url)
        try:
            session = async_sessionmaker(engine, expire_on_commit=False)()
            async with session:
                await session.execute(
                    text("DELETE FROM job_postings WHERE external_id LIKE 'omstate-%'")
                )
                await session.execute(text("DELETE FROM job_sources WHERE key = 'omstate-source'"))
                sid = await _seed_legacy_source(session, engine, "omstate-source", {})
                # SQLite has no jsonb: CAST(x AS jsonb) numeric-casts the JSON
                # text to 0 there, so the dialect picks its own binding.
                if engine.dialect.name == "postgresql":
                    cast = lambda param: f"CAST(:{param} AS jsonb)"  # noqa: E731
                else:
                    cast = lambda param: f":{param}"  # noqa: E731
                await session.execute(
                    text(
                        "INSERT INTO job_postings "
                        "(id, ref, source_id, external_id, content_hash, title, org, "
                        "status, location, url, raw, posting_facts, needs_review, "
                        "mapping_reason, org_match, created_at, updated_at) "
                        "VALUES (:id, :ref, :sid, 'omstate-1', :ch, 'Role', "
                        "'OmState Works', 'mapped', "
                        f"{cast('loc')}, '', {cast('raw')}, {cast('facts')}, "
                        f"false, '', {cast('om')}, :now, :now)"
                    ),
                    {
                        "id": str(_uuid.uuid4()),
                        "ref": _uuid.uuid4().hex[:8].upper(),
                        "sid": sid,
                        "ch": _uuid.uuid4().hex,
                        "loc": "{}",
                        "raw": "{}",
                        "facts": "{}",
                        "om": json.dumps(
                            {
                                "layer": "rejected",
                                "score": 0.0,
                                "matched_on": "quality",
                                "state": "rejected",
                            }
                        ),
                        "now": datetime.now(UTC),
                    },
                )
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(_run())


def _om_state_read() -> str | None:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.core.config import settings

    async def _run():
        engine = create_async_engine(settings.database_url)
        try:
            async with engine.connect() as conn:
                row = (
                    await conn.execute(
                        text(
                            "SELECT org_match_state FROM job_postings "
                            "WHERE external_id = 'omstate-1'"
                        )
                    )
                ).first()
        finally:
            await engine.dispose()
        return row[0] if row else None

    return asyncio.run(_run())


def test_0071_org_match_state_backfill():
    config = _configured()

    try:
        command.upgrade(config, "head")
        command.downgrade(config, "0070")
        assert not _column_present("job_postings", "org_match_state"), (
            "downgrade drops the projection"
        )
        _om_state_seed()

        command.upgrade(config, "head")
        assert _om_state_read() == "rejected", "the JSONB state backfills the column"
    finally:
        _om_state_cleanup()


def _om_state_cleanup() -> None:
    async def _run():
        from sqlalchemy import delete
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from app.core.config import settings
        from app.models.posting_model import JobSource

        engine = create_async_engine(settings.database_url)
        try:
            session = async_sessionmaker(engine, expire_on_commit=False)()
            async with session:
                await session.execute(delete(JobSource).where(JobSource.key.like("omstate-source")))
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(_run())


def _relation_checks() -> dict[str, str]:
    """CHECK expressions on `skill_relations` (dialect-safe)."""

    async def run():
        from sqlalchemy import inspect
        from sqlalchemy.ext.asyncio import create_async_engine

        from app.core.config import settings

        engine = create_async_engine(settings.database_url)
        try:
            async with engine.connect() as conn:
                checks = await conn.run_sync(
                    lambda sync_conn: inspect(sync_conn).get_check_constraints("skill_relations")
                )
            return {c["name"].replace("ck_skill_relations_", ""): str(c["sqltext"]) for c in checks}
        finally:
            await engine.dispose()

    return asyncio.run(run())


def _relation_indexes() -> list[str]:
    async def run():
        from sqlalchemy import inspect
        from sqlalchemy.ext.asyncio import create_async_engine

        from app.core.config import settings

        engine = create_async_engine(settings.database_url)
        try:
            async with engine.connect() as conn:
                indexes = await conn.run_sync(
                    lambda sync_conn: inspect(sync_conn).get_indexes("skill_relations")
                )
            return sorted(str(i["name"]) for i in indexes)
        finally:
            await engine.dispose()

    return asyncio.run(run())


def test_0067_skill_relations_roundtrip():
    config = _configured()

    command.upgrade(config, "head")
    assert _table_present("skill_relations"), "skill_relations exists at head"
    assert {
        "no_self_loop",
        "relation_allowed",
        "status_allowed",
        "source_allowed",
        "confidence_range",
        "symmetric_pair_ordered",
    } <= set(_relation_checks())
    assert {
        "ix_skill_relations_from",
        "ix_skill_relations_relation_status",
        "ix_skill_relations_to",
    } <= set(_relation_indexes()), "edge indexes exist at head under the short names"
    assert "system_skill_relation_learn" in _schedules_checks()["kind_allowed"]

    command.downgrade(config, "0066")
    assert not _table_present("skill_relations"), "downgrade 0066 drops skill_relations"
    assert "system_skill_relation_learn" not in _schedules_checks()["kind_allowed"]

    command.upgrade(config, "head")
    assert _table_present("skill_relations"), "re-upgrade restores skill_relations"
    assert "system_skill_relation_learn" in _schedules_checks()["kind_allowed"]


def test_0068_skill_relation_learn_task_roundtrip():
    config = _configured()

    command.upgrade(config, "head")
    assert "skill_relation_learn" in _schedules_checks()["task_allowed"]

    command.downgrade(config, "0067")
    assert "skill_relation_learn" not in _schedules_checks()["task_allowed"]

    command.upgrade(config, "head")
    assert "skill_relation_learn" in _schedules_checks()["task_allowed"], "re-upgrade restores it"


def _skills_checks() -> dict[str, str]:
    """CHECK expressions on `skills` (dialect-safe)."""

    async def run():
        from sqlalchemy import inspect
        from sqlalchemy.ext.asyncio import create_async_engine

        from app.core.config import settings

        engine = create_async_engine(settings.database_url)
        try:
            async with engine.connect() as conn:
                checks = await conn.run_sync(
                    lambda sync_conn: inspect(sync_conn).get_check_constraints("skills")
                )
            return {c["name"].replace("ck_skills_", ""): str(c["sqltext"] or "") for c in checks}
        finally:
            await engine.dispose()

    return asyncio.run(run())


def _parent_source_probe(value: str | None, *, violation: str | None = None) -> bool:
    """Insert one throwaway skill row carrying `parent_source`; False = the
    schema rejected it (the CHECK — NULL passes, out-of-vocabulary does not)."""

    async def _run():
        from sqlalchemy.exc import IntegrityError
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from app.core.config import settings
        from app.models.taxonomy_model import Skill

        engine = create_async_engine(settings.database_url)
        try:
            session = async_sessionmaker(engine, expire_on_commit=False)()
            async with session:
                try:
                    session.add(
                        Skill(
                            key=f"parent-probe-{value or 'null'}",
                            label="Parent probe",
                            category="test",
                            parent_source=value,
                        )
                    )
                    await session.commit()
                    return True
                except IntegrityError as exc:
                    await session.rollback()
                    if violation is not None:
                        assert violation in str(exc.orig), f"expected {violation}, got: {exc.orig}"
                    return False
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def _parent_source_probe_cleanup() -> None:
    """Migration-test seeds commit real rows on a separate engine — they
    must self-clean (the _seed_cleanup gotcha)."""

    async def _run():
        from sqlalchemy import delete
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from app.core.config import settings
        from app.models.taxonomy_model import Skill

        engine = create_async_engine(settings.database_url)
        try:
            session = async_sessionmaker(engine, expire_on_commit=False)()
            async with session:
                await session.execute(delete(Skill).where(Skill.key.like("parent-probe-%")))
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(_run())


def test_0069_skill_parent_source_roundtrip():
    config = _configured()

    command.upgrade(config, "head")
    assert _column_present("skills", "parent_source"), "skills.parent_source exists at head"
    checks = _skills_checks()
    assert "parent_source_allowed" in checks, "the provenance CHECK exists at head"
    assert "'curated'" in checks["parent_source_allowed"]
    assert "'learned'" in checks["parent_source_allowed"]

    command.downgrade(config, "0068")
    assert not _column_present("skills", "parent_source"), "downgrade drops column + CHECK"

    command.upgrade(config, "head")
    assert _column_present("skills", "parent_source"), "re-upgrade restores it"
    assert "parent_source_allowed" in _skills_checks()


def test_0069_parent_source_check_admits_the_vocabulary_and_null():
    """CHECK admission: curated/learned/NULL land, anything else is rejected
    (NULL passes a SQL CHECK by three-valued logic — the untouched state)."""
    config = _configured()
    command.upgrade(config, "head")
    try:
        assert _parent_source_probe("curated"), "curated lands"
        assert _parent_source_probe("learned"), "learned lands"
        assert _parent_source_probe(None), "NULL lands (untouched)"
        assert _parent_source_probe("machine", violation="parent_source_allowed") is False, (
            "out-of-vocabulary provenance is rejected"
        )
    finally:
        _parent_source_probe_cleanup()


def _relation_skills() -> tuple[str, str]:
    """Two throwaway skill rows on a separate engine; ids returned in
    canonical order (lower UUID first — the symmetric-pair rule)."""

    async def _run():
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from app.core.config import settings
        from app.models.taxonomy_model import Skill

        engine = create_async_engine(settings.database_url)
        try:
            session = async_sessionmaker(engine, expire_on_commit=False)()
            async with session:
                rows = [
                    Skill(key=f"rel-probe-{n}", label=f"Rel probe {n}", category="test")
                    for n in ("a", "b")
                ]
                session.add_all(rows)
                await session.commit()
                return tuple(sorted(str(row.id) for row in rows))
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def _relation_insert(
    from_id: str,
    to_id: str,
    relation: str,
    status: str = "approved",
    *,
    violation: str | tuple[str, ...] | None = None,
) -> bool:
    """Insert one edge row on a separate engine; False = the schema
    rejected it (CHECK or unique).

    ``violation`` pins which constraint should have fired, for diagnostic
    quality: a stray FK error must not read as "the CHECK worked". Postgres
    names unique constraints in the message; SQLite names only CHECK
    constraints, so unique violations accept the SQLite marker too.
    """

    async def _run():
        from sqlalchemy.exc import IntegrityError
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from app.core.config import settings
        from app.models.taxonomy_model import SkillRelation

        engine = create_async_engine(settings.database_url)
        try:
            session = async_sessionmaker(engine, expire_on_commit=False)()
            async with session:
                try:
                    session.add(
                        SkillRelation(
                            from_skill_id=from_id,
                            to_skill_id=to_id,
                            relation=relation,
                            status=status,
                            source="manual",
                        )
                    )
                    await session.commit()
                    return True
                except IntegrityError as exc:
                    await session.rollback()
                    if violation is not None:
                        markers = (violation,) if isinstance(violation, str) else violation
                        assert any(marker in str(exc.orig) for marker in markers), (
                            f"expected {markers}, got: {exc.orig}"
                        )
                    return False
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def _relation_probe_cleanup() -> None:
    """Migration-test seeds commit real rows on a separate engine —
    they must self-clean (the _seed_cleanup gotcha)."""

    async def _run():
        from sqlalchemy import delete, or_, select
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from app.core.config import settings
        from app.models.taxonomy_model import Skill, SkillRelation

        engine = create_async_engine(settings.database_url)
        try:
            session = async_sessionmaker(engine, expire_on_commit=False)()
            async with session:
                probe_ids = select(Skill.id).where(Skill.key.like("rel-probe-%"))
                await session.execute(
                    delete(SkillRelation).where(
                        or_(
                            SkillRelation.from_skill_id.in_(probe_ids),
                            SkillRelation.to_skill_id.in_(probe_ids),
                        )
                    )
                )
                await session.execute(delete(Skill).where(Skill.key.like("rel-probe-%")))
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(_run())


def test_0067_skill_relation_edge_guards():
    """The schema rejects self-loops, reverse-symmetric pairs, duplicate
    (pair, relation) edges and out-of-vocabulary values; both directions
    stay legal for the directed kinds."""
    config = _configured()
    command.upgrade(config, "head")
    low, high = _relation_skills()
    duplicate = ("uq_skill_relation_edge", "UNIQUE constraint failed")
    try:
        assert _relation_insert(low, low, "related_to", violation="no_self_loop") is False, (
            "no_self_loop CHECK"
        )
        assert _relation_insert(low, high, "synonym") is True, "canonical synonym edge lands"
        assert (
            _relation_insert(high, low, "synonym", violation="symmetric_pair_ordered") is False
        ), "symmetric_pair_ordered CHECK"
        assert _relation_insert(low, high, "synonym", violation=duplicate) is False, (
            "uq_skill_relation_edge dedup"
        )
        assert _relation_insert(low, high, "is_a") is True, "directed edge lands"
        assert _relation_insert(high, low, "is_a") is True, "directed reverse is its own edge"
        assert _relation_insert(low, high, "is_a", violation=duplicate) is False, (
            "(pair, relation) dedup"
        )
        assert _relation_insert(low, high, "brother_of", violation="relation_allowed") is False, (
            "relation_allowed CHECK"
        )
        assert (
            _relation_insert(low, high, "related_to", status="maybe", violation="status_allowed")
            is False
        ), "status_allowed CHECK"
    finally:
        _relation_probe_cleanup()


def test_0072_posting_changes_roundtrip():
    """The journal table exists at head, drops on downgrade (CHECKs and
    index with it) and comes back on re-upgrade — on an empty DB too, so
    the fresh-DB boot upgrade path stays green on both dialects."""

    async def _columns() -> list[str]:
        from sqlalchemy import inspect
        from sqlalchemy.ext.asyncio import create_async_engine

        from app.core.config import settings

        engine = create_async_engine(settings.database_url)
        try:
            async with engine.connect() as conn:
                cols = await conn.run_sync(
                    lambda sync_conn: [
                        c["name"] for c in inspect(sync_conn).get_columns("posting_changes")
                    ]
                )
        finally:
            await engine.dispose()
        return cols

    config = _configured()
    command.upgrade(config, "head")
    columns = asyncio.run(_columns())
    assert columns == [
        "id",
        "posting_id",
        "occurred_at",
        "actor_kind",
        "actor_ref",
        "operation",
        "duration_ms",
        "diff",
        "outcome",
    ], "plan 142 D1 column set, order pinned by the model"

    command.downgrade(config, "0071")
    assert not _table_present("posting_changes"), "downgrade drops the journal"

    command.upgrade(config, "head")
    assert asyncio.run(_columns()) == columns, "re-upgrade restores the same shape"


def test_0073_skill_changes_roundtrip():
    """The skill journal table exists at head, drops on downgrade (CHECKs
    and both indexes with it) and comes back on re-upgrade — on an empty
    DB too, so the fresh-DB boot upgrade path stays green on both
    dialects."""

    async def _shape() -> tuple[list[str], list[str]]:
        from sqlalchemy import inspect
        from sqlalchemy.ext.asyncio import create_async_engine

        from app.core.config import settings

        engine = create_async_engine(settings.database_url)
        try:
            async with engine.connect() as conn:

                def _read(sync_conn):
                    inspector = inspect(sync_conn)
                    cols = [c["name"] for c in inspector.get_columns("skill_changes")]
                    checks = " ".join(
                        f"{c.get('name', '')} {c.get('sqltext', '')}"
                        for c in inspector.get_check_constraints("skill_changes")
                    )
                    return cols, checks

                shape = await conn.run_sync(_read)
        finally:
            await engine.dispose()
        return shape

    config = _configured()
    command.upgrade(config, "head")
    columns, checks = asyncio.run(_shape())
    assert columns == [
        "id",
        "skill_id",
        "skill_key",
        "skill_label",
        "occurred_at",
        "event",
        "actor_kind",
        "actor_ref",
        "detail",
    ], "plan 148 column set, order pinned by the model"
    assert "event_allowed" in checks and "actor_kind_allowed" in checks, (
        "both vocabulary CHECKs rode the table in"
    )

    command.downgrade(config, "0072")
    assert not _table_present("skill_changes"), "downgrade drops the journal"

    command.upgrade(config, "head")
    assert asyncio.run(_shape())[0] == columns, "re-upgrade restores the same shape"


def test_0075_extension_source_subpath_uniqueness():
    """Origin+subpath uniqueness (the multi-bundle repo): the column
    backfills from the descriptor JSONB, the origin-only unique becomes
    (origin, subpath), and the downgrade folds the column back."""
    config = _configured()

    async def seed(row_id: str, origin: str, descriptor: dict):
        import json

        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine

        from app.core.config import settings

        engine = create_async_engine(settings.database_url)
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO extension_sources (id, origin, kind, "
                        "descriptor, candidates, secrets, status, error, "
                        "consecutive_failures, created_at, updated_at) "
                        "VALUES (CAST(:id AS uuid), :origin, 'git', CAST(:descriptor AS jsonb), "
                        "'[]'::jsonb, '{}'::jsonb, 'ok', '', 0, now(), now())"
                    ).bindparams(
                        id=row_id,
                        origin=origin,
                        descriptor=json.dumps(descriptor),
                    )
                )
        finally:
            await engine.dispose()

    async def read_subpath(origin: str):
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine

        from app.core.config import settings

        engine = create_async_engine(settings.database_url)
        try:
            async with engine.connect() as conn:
                return (
                    await conn.execute(
                        text("SELECT subpath FROM extension_sources WHERE origin = :o"),
                        {"o": origin},
                    )
                ).scalar()
        finally:
            await engine.dispose()

    async def insert_same_origin_other_subpath():
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine

        from app.core.config import settings

        engine = create_async_engine(settings.database_url)
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO extension_sources (id, origin, subpath, kind, "
                        "descriptor, candidates, secrets, status, error, "
                        "consecutive_failures, created_at, updated_at) "
                        "VALUES ('11111111-1111-4111-8111-111111111111', "
                        "'https://git.example.com/multi', 'a/src', 'git', '{}'::jsonb, "
                        "'[]'::jsonb, '{}'::jsonb, 'ok', '', 0, now(), now())"
                    )
                )
        finally:
            await engine.dispose()

    async def read_origin_rows():
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine

        from app.core.config import settings

        engine = create_async_engine(settings.database_url)
        try:
            async with engine.connect() as conn:
                return (
                    await conn.execute(
                        text(
                            "SELECT origin, descriptor FROM extension_sources "
                            "WHERE origin LIKE 'https://git.example.com/multi%'"
                        )
                    )
                ).all()
        finally:
            await engine.dispose()

    try:
        # Normalize: a crashed earlier run can leave the DB at 0075 —
        # alembic `upgrade` never descends, so descend explicitly first
        # (no-op when already at 0074), then clear this test's rows.
        command.downgrade(config, "0074")
        _es_cleanup()
        assert not _column_present("extension_sources", "subpath")
        asyncio.run(
            seed(
                "22222222-2222-4222-8222-222222222222",
                "https://git.example.com/multi",
                {"url": "https://git.example.com/multi"},
            )
        )
        asyncio.run(
            seed(
                "33333333-3333-4333-8333-333333333333",
                "https://git.example.com/multi-b",
                {"url": "https://git.example.com/multi-b", "subpath": "b/src"},
            )
        )

        command.upgrade(config, "head")
        assert _column_present("extension_sources", "subpath")
        assert asyncio.run(read_subpath("https://git.example.com/multi")) == ""
        assert asyncio.run(read_subpath("https://git.example.com/multi-b")) == "b/src"

        # The composite unique admits the same origin at a different
        # subpath and refuses the same origin+subpath.
        asyncio.run(insert_same_origin_other_subpath())

        command.downgrade(config, "0074")
        assert not _column_present("extension_sources", "subpath")
        # ...then restore the chain head for the tests that follow this one.
        command.upgrade(config, "head")
        assert _column_present("extension_sources", "subpath")
        # The downgrade folds each survivor's subpath into its descriptor.
        # These two rows carry DIFFERENT origins, so both survive — the
        # dedupe keeps one row per origin only.
        remaining = asyncio.run(read_origin_rows())

        assert len(remaining) == 2, remaining
        folded = {origin: (descriptor or {}).get("subpath") for origin, descriptor in remaining}
        assert folded["https://git.example.com/multi"] is None, (
            "the '' subpath row folds nothing (absent key)"
        )
        assert folded["https://git.example.com/multi-b"] == "b/src"
    finally:
        _es_cleanup()


def _es_cleanup() -> None:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.core.config import settings

    async def _run():
        engine = create_async_engine(settings.database_url)
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "DELETE FROM extension_sources "
                        "WHERE origin LIKE 'https://git.example.com/multi%'"
                    )
                )
        finally:
            await engine.dispose()

    asyncio.run(_run())


def test_0076_alert_manage_urls_roundtrip():
    """Plan 156: the three scheduler-era kinds follow the Automations move
    on upgrade; the downgrade restores the legacy links so the fold is
    reversible. The kinds are boot-seeded, not migration-seeded, so the
    test inserts the legacy rows itself on the downlevel schema."""

    async def _seed_legacy() -> None:
        from sqlalchemy.ext.asyncio import create_async_engine

        from app.core.config import settings

        engine = create_async_engine(settings.database_url)
        try:
            async with engine.begin() as conn:
                for index, key in enumerate(("digest_ready", "background_failed", "checkin_due")):
                    await conn.execute(
                        sa.text("DELETE FROM notification_kinds WHERE key = :key"),
                        {"key": key},
                    )
                    await conn.execute(
                        sa.text(
                            "INSERT INTO notification_kinds "
                            '(id, key, label, "group", severity, default_enabled, '
                            "default_channels, mutable, manage_url, created_at, updated_at) "
                            "VALUES "
                            f"('{index + 1:0>32}', :key, :key, 'career', 'info', TRUE, "
                            "'[\"in_app\"]', TRUE, '/settings/scheduler', "
                            "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                        ),
                        {"key": key},
                    )
        finally:
            await engine.dispose()

    async def _urls() -> dict[str, str | None]:
        from sqlalchemy.ext.asyncio import create_async_engine

        from app.core.config import settings

        engine = create_async_engine(settings.database_url)
        try:
            async with engine.connect() as conn:
                rows = (
                    await conn.execute(
                        sa.text(
                            "SELECT key, manage_url FROM notification_kinds "
                            "WHERE key IN ('digest_ready', 'background_failed', 'checkin_due')"
                        )
                    )
                ).all()
        finally:
            await engine.dispose()
        return dict(rows)

    config = _configured()
    command.downgrade(config, "0075")
    asyncio.run(_seed_legacy())

    command.upgrade(config, "head")
    urls = asyncio.run(_urls())
    assert len(urls) == 3, urls
    assert all(url == "/settings/automations" for url in urls.values()), urls

    command.downgrade(config, "0075")
    restored = asyncio.run(_urls())
    assert all(url == "/settings/scheduler" for url in restored.values()), restored

    command.upgrade(config, "head")
    assert all(url == "/settings/automations" for url in asyncio.run(_urls()).values()), (
        "re-upgrade re-applies the Automations links"
    )

    async def _cleanup() -> None:
        from sqlalchemy.ext.asyncio import create_async_engine

        from app.core.config import settings

        engine = create_async_engine(settings.database_url)
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    sa.text(
                        "DELETE FROM notification_kinds "
                        "WHERE id IN ('00000000000000000000000000000001', "
                        "'00000000000000000000000000000002', "
                        "'00000000000000000000000000000003')"
                    )
                )
        finally:
            await engine.dispose()

    asyncio.run(_cleanup())


def test_0091_retrieval_alert_sweep_roundtrip():
    """The alert sweep schedule widens the mirrored CHECKs and folds back."""
    config = _configured()

    command.upgrade(config, "head")
    checks = _schedules_checks()
    assert "system_retrieval_alerts" in checks["kind_allowed"]
    assert "retrieval_alert_sweep" in checks["task_allowed"]

    command.downgrade(config, "0090")
    checks = _schedules_checks()
    assert "system_retrieval_alerts" not in checks["kind_allowed"]
    assert "retrieval_alert_sweep" not in checks["task_allowed"]

    command.upgrade(config, "head")
    checks = _schedules_checks()
    assert "system_retrieval_alerts" in checks["kind_allowed"]
    assert "retrieval_alert_sweep" in checks["task_allowed"]


def test_0086_embeddings_reconcile_task_roundtrip():
    """Both `schedules` CHECKs admit the reconcile job at 0086 and narrow
    back on downgrade — the mirrored-vocabulary discipline of 0067/0068.

    0088 retires that vocabulary for the store-wide vector reconcile, so this
    test pins the *0086 revision* by downgrading exactly to it."""
    config = _configured()

    command.upgrade(config, "head")
    command.downgrade(config, "0086")
    checks = _schedules_checks()
    assert "system_embeddings_reconcile" in checks["kind_allowed"]
    assert "embeddings_reconcile" in checks["task_allowed"]

    command.downgrade(config, "0085")
    checks = _schedules_checks()
    assert "system_embeddings_reconcile" not in checks["kind_allowed"]
    assert "embeddings_reconcile" not in checks["task_allowed"]

    command.upgrade(config, "0086")
    checks = _schedules_checks()
    assert "system_embeddings_reconcile" in checks["kind_allowed"], "re-upgrade restores it"
    assert "embeddings_reconcile" in checks["task_allowed"], "re-upgrade restores it"
    command.upgrade(config, "head")


_VECTOR_TABLES = (
    "vector_spaces",
    "vector_documents",
    "vector_records",
    "retrieval_query_rollups",
    "retrieval_coverage_snapshots",
)


def _vector_shape() -> tuple[
    set[str], set[str], dict[str, list[str]], dict[str, set[str]], dict[str, set[str]]
]:
    """Tables, their columns, CHECKs and indexes at the current revision."""

    async def run():
        from sqlalchemy import inspect
        from sqlalchemy.ext.asyncio import create_async_engine

        from app.core.config import settings

        engine = create_async_engine(settings.database_url)
        try:
            async with engine.connect() as conn:

                def read(sync_conn):
                    inspector = inspect(sync_conn)
                    all_tables = set(inspector.get_table_names())
                    present = {table for table in _VECTOR_TABLES if inspector.has_table(table)}
                    columns = {
                        table: [column["name"] for column in inspector.get_columns(table)]
                        for table in present
                    }
                    checks = {
                        table: {row["name"] for row in inspector.get_check_constraints(table)}
                        for table in present
                    }
                    indexes = {
                        table: {row["name"] for row in inspector.get_indexes(table)}
                        for table in present
                    }
                    return all_tables, present, columns, checks, indexes

                return await conn.run_sync(read)
        finally:
            await engine.dispose()

    return asyncio.run(run())


def test_0087_vector_retrieval_roundtrip():
    """Plan 50 P1a: the five portable tables exist, drop on downgrade and
    return on re-upgrade. No physical `vec_*` table is created."""
    config = _configured()
    command.upgrade(config, "head")

    all_tables, present, columns, checks, indexes = _vector_shape()
    assert present == set(_VECTOR_TABLES), "all five tables exist at head"
    assert not {table for table in all_tables if table.startswith("vec_")}, (
        "no dynamic ANN table is provisioned by the migration"
    )

    assert {
        "id",
        "space_id",
        "kind",
        "source_id",
        "scope_type",
        "scope_id",
        "profile_id",
        "source_hash",
        "schema_version",
    } <= set(columns["vector_documents"])
    assert {
        "document_id",
        "space_id",
        "view",
        "chunk_index",
        "content_hash",
        "text_ref",
        "text_ref_schema_version",
        "embedding",
    } <= set(columns["vector_records"])
    assert {
        "name",
        "provider",
        "model",
        "dim",
        "metric",
        "normalize",
        "query_prefix",
        "document_prefix",
        "index_table",
        "status",
        "backfill_done",
        "backfill_total",
    } <= set(columns["vector_spaces"])
    assert {
        "space_id",
        "kind",
        "bucket_start",
        "bucket_width",
        "count",
        "zero_results",
        "candidates_sum",
        "latency_buckets",
    } <= set(columns["retrieval_query_rollups"])
    assert {
        "space_id",
        "kind",
        "as_of",
        "total",
        "missing",
        "stale",
        "failed",
        "embedded",
        "ann_recall",
        "ann_recall_k",
        "probe_size",
    } <= set(columns["retrieval_coverage_snapshots"])

    assert "ck_vector_spaces_status_allowed" in checks["vector_spaces"]
    assert "ck_vector_spaces_metric_allowed" in checks["vector_spaces"]
    assert "ck_vector_spaces_index_table_shape" in checks["vector_spaces"]
    assert "ck_vector_documents_scope_type_allowed" in checks["vector_documents"]
    assert "ck_vector_records_view_allowed" in checks["vector_records"]
    assert "ck_retrieval_query_rollups_degraded_reason_allowed" in checks["retrieval_query_rollups"]
    assert (
        "ck_retrieval_coverage_snapshots_ann_recall_range" in checks["retrieval_coverage_snapshots"]
    )
    assert "uq_vector_spaces_name_active" in indexes["vector_spaces"]

    command.downgrade(config, "0086")
    assert _vector_shape()[1] == set(), "downgrade drops every table"

    command.upgrade(config, "head")
    assert _vector_shape()[1] == set(_VECTOR_TABLES), "re-upgrade restores the store"


def _schema_probe(tables: tuple[str, ...]) -> dict[str, bool]:
    """Table presence at the current revision (dialect-safe)."""

    async def run() -> dict[str, bool]:
        from sqlalchemy import inspect
        from sqlalchemy.ext.asyncio import create_async_engine

        from app.core.config import settings

        engine = create_async_engine(settings.database_url)
        try:
            async with engine.connect() as conn:
                names = await conn.run_sync(
                    lambda sync_conn: set(inspect(sync_conn).get_table_names())
                )
            return {table: table in names for table in tables}
        finally:
            await engine.dispose()

    import asyncio

    return asyncio.run(run())


def test_0088_drop_ai_embeddings_roundtrip():
    """Plan 50 P1d: the legacy store is dropped, the schedule vocabulary
    swaps to the store-wide reconcile, and both revert on downgrade."""
    config = _configured()

    command.upgrade(config, "head")
    command.downgrade(config, "0087")
    assert _schema_probe(("ai_embeddings",))["ai_embeddings"], "the legacy store exists at 0087"
    assert "system_embeddings_reconcile" in _schedules_checks()["kind_allowed"]

    command.upgrade(config, "head")
    assert not _schema_probe(("ai_embeddings",))["ai_embeddings"], (
        "0088 drops the legacy embeddings store"
    )
    checks = _schedules_checks()
    assert "system_embeddings_reconcile" not in checks["kind_allowed"]
    assert "system_vector_reconcile" in checks["kind_allowed"]
    assert "embeddings_reconcile" not in checks["task_allowed"]
    assert "vector_reconcile" in checks["task_allowed"]

    command.downgrade(config, "0087")
    assert _schema_probe(("ai_embeddings",))["ai_embeddings"], "downgrade recreates the table"
    checks = _schedules_checks()
    assert "system_embeddings_reconcile" in checks["kind_allowed"]
    assert "system_vector_reconcile" not in checks["kind_allowed"]
    assert "embeddings_reconcile" in checks["task_allowed"]

    command.upgrade(config, "head")
    assert not _schema_probe(("ai_embeddings",))["ai_embeddings"], "re-upgrade drops it again"


def test_0089_mapping_provenance_roundtrip():
    """Plan 50 P2b: the mapping provenance columns and their two indexes
    exist at head, disappear on downgrade and return on re-upgrade."""
    config = _configured()
    command.upgrade(config, "head")
    assert _column_present("job_postings", "mapping_version"), "version stamp at head"
    assert _column_present("job_postings", "mapping_features"), "provenance payload at head"
    assert _index_present("job_postings", "ix_postings_mapping_version")
    assert _index_present("job_postings", "ix_postings_mapping_method")

    command.downgrade(config, "0088")
    assert not _column_present("job_postings", "mapping_version")
    assert not _column_present("job_postings", "mapping_features")
    assert not _index_present("job_postings", "ix_postings_mapping_version")
    assert not _index_present("job_postings", "ix_postings_mapping_method")

    command.upgrade(config, "head")
    assert _column_present("job_postings", "mapping_version")
    assert _column_present("job_postings", "mapping_features")


def _vector_constraint_probe(name: str) -> dict[str, bool]:
    """Behavioral constraints on vector_spaces/retrieval_query_rollups."""

    async def run() -> dict[str, bool]:
        import uuid as _uuid

        from sqlalchemy import text
        from sqlalchemy.exc import IntegrityError
        from sqlalchemy.ext.asyncio import create_async_engine

        from app.core.config import settings

        engine = create_async_engine(settings.database_url)
        is_postgres = engine.dialect.name == "postgresql"

        def uuid_param(param: str) -> str:
            return f"CAST(:{param} AS uuid)" if is_postgres else f":{param}"

        async def attempt(statement: str, params: dict) -> bool:
            try:
                async with engine.begin() as conn:
                    await conn.execute(text(statement), params)
                return True
            except IntegrityError:
                return False

        space_id = _uuid.uuid4()
        other_id = _uuid.uuid4()
        retired_id = _uuid.uuid4()
        now = datetime.now(UTC)
        space_columns = (
            "INSERT INTO vector_spaces "
            "(id, name, provider, model, dim, metric, normalize, chunker_version, "
            "composer_version, space_key, index_table, status, created_at, updated_at) "
            f"VALUES ({uuid_param('id')}, :name, 'openai', 'text-embedding-3-small', "
            "4, 'cosine', true, '1', '1', "
            f"'{'a' * 64}', :index_table, :status, :now, :now)"
        )
        rollup_columns = (
            "INSERT INTO retrieval_query_rollups "
            f"(id, space_id, kind, view, degraded_reason, bucket_start, bucket_width, "
            '"count", zero_results, candidates_sum, created_at, updated_at) '
            f"VALUES ({uuid_param('id')}, {uuid_param('space_id')}, :kind, NULL, NULL, "
            ":bucket_start, 60, 0, 0, 0, :now, :now)"
        )
        results: dict[str, bool] = {}
        try:
            results["active"] = await attempt(
                space_columns,
                {
                    "id": str(space_id),
                    "name": name,
                    "index_table": None,
                    "status": "active",
                    "now": now,
                },
            )
            results["second_active"] = await attempt(
                space_columns,
                {
                    "id": str(other_id),
                    "name": name,
                    "index_table": None,
                    "status": "active",
                    "now": now,
                },
            )
            results["retired_same_name"] = await attempt(
                space_columns,
                {
                    "id": str(retired_id),
                    "name": name,
                    "index_table": None,
                    "status": "retired",
                    "now": now,
                },
            )
            results["index_table"] = await attempt(
                space_columns,
                {
                    "id": str(_uuid.uuid4()),
                    "name": name,
                    "index_table": "vec_aaaaaaaa",
                    "status": "retired",
                    "now": now,
                },
            )
            results["duplicate_index_table"] = await attempt(
                space_columns,
                {
                    "id": str(_uuid.uuid4()),
                    "name": name,
                    "index_table": "vec_aaaaaaaa",
                    "status": "retired",
                    "now": now,
                },
            )
            results["null_index_table"] = await attempt(
                space_columns,
                {
                    "id": str(_uuid.uuid4()),
                    "name": name,
                    "index_table": None,
                    "status": "retired",
                    "now": now,
                },
            )
            results["rollup"] = await attempt(
                rollup_columns,
                {
                    "id": str(_uuid.uuid4()),
                    "space_id": str(space_id),
                    "kind": "posting",
                    "bucket_start": now,
                    "now": now,
                },
            )
            results["duplicate_rollup"] = await attempt(
                rollup_columns,
                {
                    "id": str(_uuid.uuid4()),
                    "space_id": str(space_id),
                    "kind": "posting",
                    "bucket_start": now,
                    "now": now,
                },
            )
        finally:
            async with engine.begin() as conn:
                await conn.execute(
                    text("DELETE FROM vector_spaces WHERE name = :name"), {"name": name}
                )
            await engine.dispose()
        return results

    return asyncio.run(run())


def test_0087_vector_space_and_rollup_constraints():
    """One active space per name (partial index); retired siblings allowed;
    the rollup dimension key coalesces NULL view/reason so a duplicate
    aggregate is rejected on both dialects."""
    config = _configured()
    command.upgrade(config, "head")
    results = _vector_constraint_probe("vector-constraint-probe")
    assert results["active"] is True
    assert results["second_active"] is False, "one active space per name"
    assert results["retired_same_name"] is True, "a retired sibling is allowed"
    assert results["index_table"] is True
    assert results["duplicate_index_table"] is False, "a physical index table is unique"
    assert results["null_index_table"] is True, "NULL index tables coexist (linear spaces)"
    assert results["rollup"] is True
    assert results["duplicate_rollup"] is False, "the COALESCE dimension index dedupes"


def test_0090_retrieval_ops_roundtrip():
    """Plan 51 Q1a: the retrieval tag columns and the two job partial-unique
    indexes exist at head, disappear on downgrade and return on re-upgrade."""
    config = _configured()
    command.upgrade(config, "head")
    assert _column_present("ai_generations", "metadata"), "retrieval tags at head"
    assert _column_present("ai_generations", "metadata_schema_version")
    assert _column_present("background_jobs", "idempotency_key")
    assert _column_present("background_jobs", "lock_key")
    assert _index_present("background_jobs", "uq_background_jobs_idempotency_active")
    assert _index_present("background_jobs", "uq_background_jobs_lock_key_active")

    command.downgrade(config, "0089")
    assert not _column_present("ai_generations", "metadata")
    assert not _column_present("ai_generations", "metadata_schema_version")
    assert not _column_present("background_jobs", "idempotency_key")
    assert not _column_present("background_jobs", "lock_key")
    assert not _index_present("background_jobs", "uq_background_jobs_idempotency_active")
    assert not _index_present("background_jobs", "uq_background_jobs_lock_key_active")

    command.upgrade(config, "head")
    assert _column_present("ai_generations", "metadata")
    assert _column_present("background_jobs", "lock_key")


def _retrieval_ops_seam_probe() -> dict[str, bool]:
    """Behavioral checks for the 0090 seams: tag defaults and the two
    active-status partial unique indexes on both dialects."""
    import json as _json
    import uuid as _uuid

    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.core.config import settings

    async def run() -> dict[str, bool]:
        engine = create_async_engine(settings.database_url)
        is_postgres = engine.dialect.name == "postgresql"

        def uuid_param(param: str) -> str:
            return f"CAST(:{param} AS uuid)" if is_postgres else f":{param}"

        now = datetime.now(UTC)
        generation_id = _uuid.uuid4()
        job_ids = [_uuid.uuid4() for _ in range(10)]
        results: dict[str, bool] = {}

        job_insert = (
            "INSERT INTO background_jobs "
            f"(id, job_type, status, progress, payload, attempts, max_attempts, "
            "cancel_requested, idempotency_key, lock_key, created_at, updated_at) "
            f"VALUES ({uuid_param('id')}, :job_type, :status, 0, '{{}}', 0, 2, "
            "false, :idempotency_key, :lock_key, :now, :now)"
        )
        generation_insert = (
            "INSERT INTO ai_generations "
            f"(id, task_type, provider, model, prompt, status, error, "
            "created_at, updated_at) "
            f"VALUES ({uuid_param('id')}, 'embed', 'openai', 'text-embedding-3-small', "
            "'embed 1 text(s)', 'ok', '', :now, :now)"
        )

        async def attempt(statement: str, params: dict) -> bool:
            try:
                async with engine.begin() as conn:
                    await conn.execute(text(statement), params)
                return True
            except IntegrityError:
                return False

        def job(index: int, **overrides) -> dict:
            values = {
                "id": str(job_ids[index]),
                "job_type": "vector_reconcile",
                "status": "queued",
                "idempotency_key": None,
                "lock_key": None,
                "now": now,
            }
            values.update(overrides)
            return values

        try:
            results["generation"] = await attempt(
                generation_insert, {"id": str(generation_id), "now": now}
            )
            async with engine.connect() as conn:
                row = (
                    await conn.execute(
                        text(
                            "SELECT metadata, metadata_schema_version "
                            "FROM ai_generations WHERE id = :id"
                        ),
                        {"id": str(generation_id)},
                    )
                ).one()
            raw_metadata = row[0] if isinstance(row[0], dict) else _json.loads(str(row[0]))
            results["metadata_default"] = raw_metadata == {}
            results["metadata_version"] = int(row[1]) == 1

            tag_sql = (
                "UPDATE ai_generations SET metadata = CAST(:payload AS jsonb) WHERE id = :id"
                if is_postgres
                else "UPDATE ai_generations SET metadata = :payload WHERE id = :id"
            )
            async with engine.begin() as conn:
                await conn.execute(
                    text(tag_sql),
                    {
                        "payload": '{"space_id": "space-content", "kind": "posting"}',
                        "id": str(generation_id),
                    },
                )
                tagged = (
                    await conn.execute(
                        text("SELECT metadata FROM ai_generations WHERE id = :id"),
                        {"id": str(generation_id)},
                    )
                ).scalar()
            tagged_metadata = tagged if isinstance(tagged, dict) else _json.loads(str(tagged))
            results["metadata_tagged"] = tagged_metadata == {
                "space_id": "space-content",
                "kind": "posting",
            }

            results["first_key"] = await attempt(job_insert, job(0, idempotency_key="req-abc12345"))
            results["same_key_active"] = await attempt(
                job_insert, job(1, idempotency_key="req-abc12345")
            )
            results["same_key_other_type"] = await attempt(
                job_insert,
                job(2, job_type="vector_index", idempotency_key="req-abc12345"),
            )
            results["same_key_terminal"] = await attempt(
                job_insert, job(3, status="succeeded", idempotency_key="req-abc12345")
            )
            results["lock_first"] = await attempt(
                job_insert, job(4, lock_key="vector_space:space-content")
            )
            results["lock_same_active"] = await attempt(
                job_insert, job(5, lock_key="vector_space:space-content")
            )
            results["lock_terminal"] = await attempt(
                job_insert,
                job(6, status="cancelled", lock_key="vector_space:space-content"),
            )
            results["lock_running"] = await attempt(
                job_insert,
                job(7, status="running", lock_key="vector_space:space-content"),
            )
        finally:
            async with engine.begin() as conn:
                await conn.execute(
                    text("DELETE FROM ai_generations WHERE id = :id"),
                    {"id": str(generation_id)},
                )
                for job_id in job_ids:
                    await conn.execute(
                        text(f"DELETE FROM background_jobs WHERE id = {uuid_param('id')}"),
                        {"id": str(job_id)},
                    )
            await engine.dispose()
        return results

    return asyncio.run(run())


def test_0090_retrieval_ops_seams_behavior():
    """Tag defaults/tagging and the active-status partial unique indexes."""
    config = _configured()
    command.upgrade(config, "head")
    results = _retrieval_ops_seam_probe()
    assert results["generation"] is True
    assert results["metadata_default"] is True, "an untagged row defaults to {}"
    assert results["metadata_version"] is True, "the schema-version sibling defaults to 1"
    assert results["metadata_tagged"] is True
    assert results["first_key"] is True
    assert results["same_key_active"] is False, "an active replay key is unique per job type"
    assert results["same_key_other_type"] is True, "the key scope includes the job type"
    assert results["same_key_terminal"] is True, "a terminal row releases the replay slot"
    assert results["lock_first"] is True
    assert results["lock_same_active"] is False, "one active run per lock_key"
    assert results["lock_terminal"] is True, "a terminal row releases the lock"
    assert results["lock_running"] is False, "a queued and a running row cannot share a lock"


def test_0092_profile_link_urls_roundtrip():
    """Plan 193: bare profile link URLs fold to https at head, an existing
    scheme is untouched, the downgrade is a documented no-op and a re-run is
    idempotent."""
    import asyncio
    import json
    import uuid
    from datetime import datetime

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.core.config import settings

    config = _configured()
    command.downgrade(config, "0091")

    profile_id = uuid.uuid4()
    user_id = uuid.uuid4()
    basics = {
        "links": [
            {"kind": "github", "url": f"github.com/fold-{profile_id}", "label": ""},
            {"kind": "portfolio", "url": "https://neuronection.com", "label": ""},
        ]
    }

    async def run(sql: str, params: dict, fetch: bool = False):
        engine = create_async_engine(settings.database_url)
        try:
            async with engine.begin() as conn:
                result = await conn.execute(text(sql), params)
                return result.scalar_one() if fetch else None
        finally:
            await engine.dispose()

    async def seed() -> None:
        engine = create_async_engine(settings.database_url)
        is_postgres = engine.dialect.name == "postgresql"
        cast = (
            (lambda param: f"CAST(:{param} AS jsonb)")
            if is_postgres
            else (lambda param: f":{param}")
        )
        now = datetime.now(UTC)
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO users (id, email, password_hash, full_name, is_active, "
                        "is_admin, failed_login_attempts, token_version, created_at, "
                        "updated_at) VALUES "
                        "(:id, :email, :hash, '', true, false, 0, 1, :now, :now)"
                    ),
                    {
                        "id": str(user_id),
                        "email": f"fold0092-{user_id}@example.com",
                        "hash": "$2b$12$foldmigrationplaceholder",
                        "now": now,
                    },
                )
                await conn.execute(
                    text(
                        "INSERT INTO profiles (id, user_id, name, is_default, basics, "
                        "academics, hobbies, likes, dislikes, aspirations, "
                        "work_preferences, preferences, constraints, created_at, "
                        "updated_at) VALUES "
                        f"(:id, :user_id, 'Default', true, {cast('basics')}, "
                        f"{cast('academics')}, {cast('hobbies')}, {cast('likes')}, "
                        f"{cast('dislikes')}, {cast('aspirations')}, {cast('wp')}, "
                        f"{cast('prefs')}, {cast('cons')}, :now, :now)"
                    ),
                    {
                        "id": str(profile_id),
                        "user_id": str(user_id),
                        "basics": json.dumps(basics),
                        "academics": "{}",
                        "hobbies": "[]",
                        "likes": "[]",
                        "dislikes": "[]",
                        "aspirations": "[]",
                        "wp": "{}",
                        "prefs": "{}",
                        "cons": "{}",
                        "now": now,
                    },
                )
        finally:
            await engine.dispose()

    async def links() -> list[str]:
        raw = await run(
            "SELECT basics FROM profiles WHERE id = :id", {"id": str(profile_id)}, fetch=True
        )
        data = json.loads(raw) if isinstance(raw, str) else raw
        return [link["url"] for link in data.get("links", [])]

    asyncio.run(seed())
    try:
        command.upgrade(config, "head")
        urls = asyncio.run(links())
        assert urls[0] == f"https://github.com/fold-{profile_id}"
        assert urls[1] == "https://neuronection.com", "an existing scheme is untouched"

        command.downgrade(config, "0091")
        assert asyncio.run(links())[0] == urls[0], "the downgrade is a documented no-op"
        command.upgrade(config, "head")
        assert asyncio.run(links()) == urls, "the fold is idempotent"
    finally:
        asyncio.run(run("DELETE FROM profiles WHERE id = :id", {"id": str(profile_id)}))
        asyncio.run(run("DELETE FROM users WHERE id = :id", {"id": str(user_id)}))


def test_0093_job_progress_detail_roundtrip():
    """Plan 52 T4: the nullable bounded progress detail exists at head,
    disappears on downgrade and returns on re-upgrade (both dialects)."""
    config = _configured()
    command.upgrade(config, "head")
    assert _column_present("background_jobs", "progress_detail"), "live detail at head"

    command.downgrade(config, "0092")
    assert not _column_present("background_jobs", "progress_detail")

    command.upgrade(config, "head")
    assert _column_present("background_jobs", "progress_detail")


def test_0094_embedding_model_profiles_roundtrip():
    """Plan 52 T2a: the admin profile registry exists at head, disappears on
    downgrade and returns on re-upgrade (both dialects)."""
    config = _configured()
    command.upgrade(config, "head")
    assert _table_present("embedding_model_profiles"), "profile registry at head"
    for column in (
        "provider_class",
        "model_name",
        "tokenizer_kind",
        "max_input_tokens",
        "batch_max_items",
        "batch_max_tokens",
        "chunk_max_tokens",
        "chunk_overlap_tokens",
        "chunk_max_chars",
        "source",
        "updated_by",
    ):
        assert _column_present("embedding_model_profiles", column), column

    command.downgrade(config, "0093")
    assert not _table_present("embedding_model_profiles")

    command.upgrade(config, "head")
    assert _table_present("embedding_model_profiles")
