"""The v0.17 baseline is the whole schema: one head, one round-trip, no drift.

The 0045-0100 chain was replaced by the sanctioned destructive baseline
(owner-approved, no production users): v0.16.0 → v0.17 is a declared
breaking release, so dev/test databases are recreated instead of
downgraded. What must stay true: the baseline upgrades from empty on both
dialects, downgrades to an empty schema, seeds the company quality
denylist, and never drifts from the models.
"""

from __future__ import annotations

import asyncio
import os

from alembic.config import Config

from alembic import command

BASELINE = "0017"


def _configured() -> Config:
    from app.core.config import settings

    os.environ["CAREER_DATABASE_URL"] = settings.database_url
    return Config("alembic.ini")


def _heads() -> list[str]:
    from alembic.script import ScriptDirectory

    return ScriptDirectory.from_config(_configured()).get_heads()


def _model_drift_ops() -> list:
    """Alembic's model comparison against the suite's live database.

    Kit-owned tables (``auth_sessions``, ``audit_events``,
    ``instance_settings``) and LangGraph's runtime checkpoints are not ORM
    models, so their presence is expected and filtered; vector tables are
    hidden by the shared ``include_object`` hook. Everything else must
    match the baseline exactly.
    """
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.core.config import settings
    from app.models import Base
    from app.storage.vector_schema import include_object

    async def run() -> list:
        engine = create_async_engine(settings.database_url)
        try:
            async with engine.connect() as conn:
                return await conn.run_sync(
                    lambda sync_conn: compare_metadata(
                        MigrationContext.configure(
                            sync_conn,
                            opts={"include_object": include_object, "compare_type": True},
                        ),
                        Base.metadata,
                    )
                )
        finally:
            await engine.dispose()

    model_tables = set(Base.metadata.tables)

    def _table_name(operation) -> str | None:
        payload = operation[1]
        if operation[0] == "remove_table":
            return payload.name
        table = getattr(payload, "table", None)
        return getattr(table, "name", None)

    relevant = []
    for operation in asyncio.run(run()):
        if operation[0].startswith("remove_") and _table_name(operation) not in model_tables:
            continue
        relevant.append(operation)
    return relevant


def test_migration_chain_has_exactly_one_head():
    assert _heads() == [BASELINE]


def test_baseline_roundtrips_on_a_fresh_sqlite_database(tmp_path, monkeypatch):
    import sqlite3

    from app.core.config import settings

    db_url = f"sqlite+aiosqlite:///{tmp_path / 'baseline.db'}"
    monkeypatch.setenv("CAREER_DATABASE_URL", db_url)
    monkeypatch.setattr(settings, "database_url", db_url, raising=False)
    config = _configured()

    command.upgrade(config, "head")

    con = sqlite3.connect(tmp_path / "baseline.db")
    try:
        tables = {
            row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert {"job_postings", "users", "organization_match_exclusions"} <= tables
        assert con.execute("SELECT count(*) FROM organization_match_exclusions").fetchone()[0] == 18
    finally:
        con.close()

    command.downgrade(config, "base")

    con = sqlite3.connect(tmp_path / "baseline.db")
    try:
        remaining = {
            row[0]
            for row in con.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' "
                "AND name NOT LIKE 'sqlite_%' AND name != 'alembic_version'"
            )
        }
        assert remaining == set()
    finally:
        con.close()

    command.upgrade(config, "head")
    assert _heads() == [BASELINE]


async def test_quality_denylist_seeds_as_editable_rows(db):
    from sqlalchemy import func, select

    from app.models.experience_model import OrganizationMatchExclusion

    total = (
        await db.execute(select(func.count()).select_from(OrganizationMatchExclusion))
    ).scalar_one()
    labels = (
        (
            await db.execute(
                select(OrganizationMatchExclusion.label)
                .where(OrganizationMatchExclusion.reason == "quality")
                .order_by(OrganizationMatchExclusion.label)
            )
        )
        .scalars()
        .all()
    )
    assert total == 18
    assert "confidential" in labels
    assert "staffing agency" in labels


def test_baseline_matches_the_models():
    assert _model_drift_ops() == []


def _sqlite_indexes(path) -> set[str]:
    import sqlite3

    con = sqlite3.connect(path)
    try:
        return {
            row[0]
            for row in con.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'job_postings'"
            )
        }
    finally:
        con.close()


def test_0002_mapping_truth_roundtrips_and_backfills_on_a_fresh_sqlite_database(
    tmp_path, monkeypatch
):
    import sqlite3

    from app.core.config import settings

    db_url = f"sqlite+aiosqlite:///{tmp_path / 'mapping-truth.db'}"
    monkeypatch.setenv("CAREER_DATABASE_URL", db_url)
    monkeypatch.setattr(settings, "database_url", db_url, raising=False)
    config = _configured()

    command.upgrade(config, "0001")
    _seed_legacy_0002(tmp_path / "mapping-truth.db", dialect="sqlite")
    command.upgrade(config, "head")

    con = sqlite3.connect(tmp_path / "mapping-truth.db")
    try:
        columns = {row[1] for row in con.execute("PRAGMA table_info('job_postings')").fetchall()}
        assert {"mapping_margin", "extract_status", "proposal_proposed_at"} <= columns
    finally:
        con.close()
    assert {
        "ix_postings_mapping_margin",
        "ix_postings_proposal_proposed_at",
        "ix_postings_status_extract",
    } <= _sqlite_indexes(tmp_path / "mapping-truth.db")
    _assert_mapping_truth_backfill(tmp_path / "mapping-truth.db", dialect="sqlite")

    command.downgrade(config, "0001")
    con = sqlite3.connect(tmp_path / "mapping-truth.db")
    try:
        columns = {row[1] for row in con.execute("PRAGMA table_info('job_postings')").fetchall()}
        assert {"mapping_margin", "extract_status", "proposal_proposed_at"}.isdisjoint(columns)
    finally:
        con.close()
    assert {
        "ix_postings_mapping_margin",
        "ix_postings_proposal_proposed_at",
        "ix_postings_status_extract",
    }.isdisjoint(_sqlite_indexes(tmp_path / "mapping-truth.db"))

    command.upgrade(config, "head")
    _assert_mapping_truth_backfill(tmp_path / "mapping-truth.db", dialect="sqlite")


def test_0002_mapping_truth_backfills_on_postgres(tmp_path, monkeypatch):
    import asyncio

    from sqlalchemy.engine import make_url

    from app.core.config import settings

    base = make_url(settings.database_url)
    if base.get_backend_name() != "postgresql":
        import pytest

        pytest.skip("postgres lane only")
    name = f"career_mig0002_{uuid_seed()}"
    admin = base.set(database="postgres").render_as_string(hide_password=False)
    temp = base.set(database=name).render_as_string(hide_password=False)
    asyncio.run(_pg_admin(admin, f'CREATE DATABASE "{name}"'))
    try:
        monkeypatch.setenv("CAREER_DATABASE_URL", temp)
        monkeypatch.setattr(settings, "database_url", temp, raising=False)
        config = _configured()
        command.upgrade(config, "0001")
        asyncio.run(_seed_legacy_0002_async(temp, dialect="postgresql"))
        command.upgrade(config, "head")
        asyncio.run(_assert_mapping_truth_backfill_async(temp))
        command.downgrade(config, "0001")
        command.upgrade(config, "head")
        asyncio.run(_assert_mapping_truth_backfill_async(temp))
    finally:
        asyncio.run(_pg_drop(admin, name))


def test_0003_job_title_key_roundtrips_and_backfills_on_a_fresh_sqlite_database(
    tmp_path, monkeypatch
):
    import sqlite3

    from app.core.config import settings

    db_url = f"sqlite+aiosqlite:///{tmp_path / 'job-title-key.db'}"
    monkeypatch.setenv("CAREER_DATABASE_URL", db_url)
    monkeypatch.setattr(settings, "database_url", db_url, raising=False)
    config = _configured()

    command.upgrade(config, "0002")
    asyncio.run(_seed_0003_async(db_url))
    command.upgrade(config, "head")
    asyncio.run(_seed_catalog_and_assert_keys_async(db_url))

    con = sqlite3.connect(tmp_path / "job-title-key.db")
    try:
        columns = {row[1] for row in con.execute("PRAGMA table_info('jobs')").fetchall()}
        assert "title_key" in columns
        key = con.execute("SELECT title_key FROM jobs WHERE code = 'legacy-title'").fetchone()[0]
        assert key == "r-and-d-engineer"
    finally:
        con.close()
    assert "ix_jobs_title_key" in _sqlite_jobs_indexes(tmp_path / "job-title-key.db")

    command.downgrade(config, "0002")
    con = sqlite3.connect(tmp_path / "job-title-key.db")
    try:
        columns = {row[1] for row in con.execute("PRAGMA table_info('jobs')").fetchall()}
        assert "title_key" not in columns
    finally:
        con.close()
    assert "ix_jobs_title_key" not in _sqlite_jobs_indexes(tmp_path / "job-title-key.db")

    command.upgrade(config, "head")
    assert "ix_jobs_title_key" in _sqlite_jobs_indexes(tmp_path / "job-title-key.db")
    con = sqlite3.connect(tmp_path / "job-title-key.db")
    try:
        key = con.execute("SELECT title_key FROM jobs WHERE code = 'legacy-title'").fetchone()[0]
        assert key == "r-and-d-engineer"
    finally:
        con.close()


def _sqlite_jobs_indexes(path) -> set[str]:
    import sqlite3

    con = sqlite3.connect(path)
    try:
        return {
            row[0]
            for row in con.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'jobs'"
            )
        }
    finally:
        con.close()


def test_0003_job_title_key_backfills_on_postgres(tmp_path, monkeypatch):
    from sqlalchemy.engine import make_url

    from app.core.config import settings

    base = make_url(settings.database_url)
    if base.get_backend_name() != "postgresql":
        import pytest

        pytest.skip("postgres lane only")
    name = f"career_mig0003_{uuid_seed()}"
    admin = base.set(database="postgres").render_as_string(hide_password=False)
    temp = base.set(database=name).render_as_string(hide_password=False)
    asyncio.run(_pg_admin(admin, f'CREATE DATABASE "{name}"'))
    try:
        monkeypatch.setenv("CAREER_DATABASE_URL", temp)
        monkeypatch.setattr(settings, "database_url", temp, raising=False)
        config = _configured()
        command.upgrade(config, "0002")
        asyncio.run(_seed_0003_async(temp))
        command.upgrade(config, "head")
        asyncio.run(_assert_0003_async(temp))
        command.downgrade(config, "0002")
        asyncio.run(_assert_0003_reverted_async(temp))
        command.upgrade(config, "head")
        asyncio.run(_assert_0003_async(temp))
    finally:
        asyncio.run(_pg_drop(admin, name))


async def _seed_0003_async(url: str) -> None:
    import uuid

    import sqlalchemy as sa
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.models.base import GuidType, StructuredJSON

    family_id = uuid.uuid4()
    job_id = uuid.uuid4()
    families = sa.table(
        "job_families",
        sa.column("id", GuidType()),
        sa.column("key", sa.String()),
        sa.column("label", sa.String()),
        sa.column("path", sa.String()),
        sa.column("level", sa.Integer()),
        sa.column("description", sa.Text()),
    )
    jobs = sa.table(
        "jobs",
        sa.column("id", GuidType()),
        sa.column("code", sa.String()),
        sa.column("title", sa.String()),
        sa.column("family_id", GuidType()),
        sa.column("short_description", sa.Text()),
        sa.column("status", sa.String()),
        sa.column("source", sa.String()),
        sa.column("attributes", StructuredJSON),
        sa.column("links", StructuredJSON),
    )
    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                sa.insert(families).values(
                    id=family_id,
                    key="legacy-family",
                    label="Legacy",
                    path="legacy-family",
                    level=0,
                    description="",
                )
            )
            await conn.execute(
                sa.insert(jobs).values(
                    id=job_id,
                    code="legacy-title",
                    title="R&D Engineer",
                    family_id=family_id,
                    short_description="",
                    status="published",
                    source="seed",
                    attributes={},
                    links=[],
                )
            )
    finally:
        await engine.dispose()


async def _seed_catalog_and_assert_keys_async(url: str) -> None:
    import sqlalchemy as sa
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

    from app.models.job_model import Job
    from app.seeds.run import seed_catalog

    engine = create_async_engine(url)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            await seed_catalog(session)
            rows = (
                (await session.execute(sa.select(Job).where(Job.status != "retired")))
                .scalars()
                .all()
            )
            assert rows
            assert all(job.title_key for job in rows)
    finally:
        await engine.dispose()


async def _assert_0003_async(url: str) -> None:
    import sqlalchemy as sa
    from sqlalchemy import inspect
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            columns = await conn.run_sync(
                lambda sync: {c["name"] for c in inspect(sync).get_columns("jobs")}
            )
            indexes = await conn.run_sync(
                lambda sync: {i["name"] for i in inspect(sync).get_indexes("jobs")}
            )
            key = (
                await conn.execute(
                    sa.text("SELECT title_key FROM jobs WHERE code = 'legacy-title'")
                )
            ).scalar_one()
    finally:
        await engine.dispose()
    assert "title_key" in columns
    assert "ix_jobs_title_key" in indexes
    assert key == "r-and-d-engineer"


async def _assert_0003_reverted_async(url: str) -> None:
    from sqlalchemy import inspect
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            columns = await conn.run_sync(
                lambda sync: {c["name"] for c in inspect(sync).get_columns("jobs")}
            )
            indexes = await conn.run_sync(
                lambda sync: {i["name"] for i in inspect(sync).get_indexes("jobs")}
            )
    finally:
        await engine.dispose()
    assert "title_key" not in columns
    assert "ix_jobs_title_key" not in indexes


def uuid_seed() -> str:
    import uuid

    return uuid.uuid4().hex[:10]


async def _pg_admin(url: str, statement: str) -> None:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            conn = await conn.execution_options(isolation_level="AUTOCOMMIT")
            await conn.execute(text(statement))
    finally:
        await engine.dispose()


async def _pg_drop(url: str, name: str) -> None:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            conn = await conn.execution_options(isolation_level="AUTOCOMMIT")
            await conn.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :name AND pid <> pg_backend_pid()"
                ),
                {"name": name},
            )
            await conn.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
    finally:
        await engine.dispose()


def _seed_legacy_0002(path, *, dialect: str) -> None:
    import asyncio

    asyncio.run(_seed_legacy_0002_async(f"sqlite+aiosqlite:///{path}", dialect=dialect))


async def _seed_legacy_0002_async(url: str, *, dialect: str) -> None:
    import json
    import uuid
    from datetime import datetime

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    def ts(value: str):
        return datetime.fromisoformat(value) if dialect == "postgresql" else value

    def j(value) -> str:
        return json.dumps(value)

    def cast(param: str) -> str:
        return f"CAST(:{param} AS jsonb)" if dialect == "postgresql" else f":{param}"

    def new_id() -> str:
        return uuid.uuid4().hex if dialect == "sqlite" else str(uuid.uuid4())

    source_id = new_id()
    created = "2026-11-01T10:00:00+00:00"
    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO job_sources "
                    "(id, key, connector_key, kind, config, secrets, enabled, sync_state, "
                    "query_mode, query_batch_size, error, last_status) "
                    f"VALUES (:id, :key, :connector, 'posting', {cast('config')}, "
                    f"{cast('secrets')}, true, {cast('sync')}, 'radar', 2, '', 'ok')"
                ),
                {
                    "id": source_id,
                    "key": f"mig-{uuid.uuid4().hex[:8]}",
                    "connector": "mig",
                    "config": j({}),
                    "secrets": j({}),
                    "sync": j({}),
                },
            )
            postings = [
                ("p-fallback", 1, {}, None),
                (
                    "p-failed",
                    1,
                    {},
                    ("failed", "2026-11-02T10:00:00+00:00", None),
                ),
                (
                    "p-latest-success",
                    1,
                    {},
                    ("failed", "2026-11-01T10:00:00+00:00", None),
                ),
                (
                    "p-resolve-only",
                    1,
                    {},
                    ("failed", created, "resolve"),
                ),
                (
                    "p-proposal",
                    1,
                    {
                        # v2 shape (the write path stamps proposal_version);
                        # migration 0014 retires v1 proposals, so a seed
                        # without the marker would not survive to head.
                        "job_proposal": {
                            "proposal_version": 2,
                            "proposed_at": "2026-11-01T12:00:00+00:00",
                        }
                    },
                    None,
                ),
                ("p-null", None, {}, None),
            ]
            for external_id, version, facts, job in postings:
                posting_id = new_id()
                await conn.execute(
                    text(
                        "INSERT INTO job_postings "
                        "(id, source_id, external_id, ref, title, org, location, url, "
                        "content_hash, raw, extract_version, needs_review, detail_attempts, "
                        "posting_facts, status, mapping_reason) "
                        f"VALUES (:id, :source, :external, :ref, :title, '', {cast('location')}, "
                        f"'https://mig.example', :hash, {cast('raw')}, :version, false, 0, "
                        f"{cast('facts')}, 'new', '')"
                    ),
                    {
                        "id": posting_id,
                        "source": source_id,
                        "external": external_id,
                        "ref": uuid.uuid4().hex[:8].upper(),
                        "title": external_id,
                        "location": j({}),
                        "hash": "0" * 64,
                        "raw": j({}),
                        "version": version,
                        "facts": j(facts),
                    },
                )
                if job is None:
                    continue
                status, job_created, mode = job
                payload = {"posting_id": posting_id}
                if mode:
                    payload["mode"] = mode
                await conn.execute(
                    text(
                        "INSERT INTO background_jobs "
                        "(id, job_type, status, progress, payload, attempts, max_attempts, "
                        "cancel_requested, created_at) "
                        "VALUES (:id, 'posting_extract', :status, 0, "
                        f"{cast('payload')}, 1, 2, false, :created)"
                    ),
                    {
                        "id": str(uuid.uuid4()),
                        "status": status,
                        "payload": j(payload),
                        "created": ts(job_created),
                    },
                )
                if external_id == "p-latest-success":
                    await conn.execute(
                        text(
                            "INSERT INTO background_jobs "
                            "(id, job_type, status, progress, payload, attempts, max_attempts, "
                            "cancel_requested, created_at) "
                            "VALUES (:id, 'posting_extract', 'succeeded', 0, "
                            f"{cast('payload')}, 1, 2, false, :created)"
                        ),
                        {
                            "id": str(uuid.uuid4()),
                            "payload": j({"posting_id": posting_id}),
                            "created": ts("2026-11-02T11:00:00+00:00"),
                        },
                    )
    finally:
        await engine.dispose()


def _assert_mapping_truth_backfill(path, *, dialect: str) -> None:
    import asyncio

    asyncio.run(_assert_mapping_truth_backfill_async(f"sqlite+aiosqlite:///{path}"))


async def _assert_mapping_truth_backfill_async(url: str) -> None:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            rows = (
                (
                    await conn.execute(
                        text(
                            "SELECT external_id, extract_status, proposal_proposed_at "
                            "FROM job_postings ORDER BY external_id"
                        )
                    )
                )
                .mappings()
                .all()
            )
    finally:
        await engine.dispose()
    statuses = {row["external_id"]: row["extract_status"] for row in rows}
    assert statuses == {
        "p-failed": "failed",
        "p-fallback": "succeeded",
        "p-latest-success": "succeeded",
        "p-null": None,
        "p-proposal": "succeeded",
        "p-resolve-only": "succeeded",
    }
    proposal = next(row for row in rows if row["external_id"] == "p-proposal")
    assert str(proposal["proposal_proposed_at"]).startswith("2026-11-01")


def test_0008_folds_the_retired_use_languages_toggle(tmp_path, monkeypatch):
    import json
    import sqlite3
    import uuid

    from app.core.config import settings

    path = tmp_path / "fold-languages.db"
    db_url = f"sqlite+aiosqlite:///{path}"
    monkeypatch.setenv("CAREER_DATABASE_URL", db_url)
    monkeypatch.setattr(settings, "database_url", db_url, raising=False)
    config = _configured()

    command.upgrade(config, "0007")
    con = sqlite3.connect(path)
    try:
        con.execute(
            "INSERT INTO autopilot_goals "
            "(id, user_id, goal_text, constraints, cadence, budget, status, "
            "last_run_at, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, NULL, ?, 'active', NULL, ?, ?)",
            (
                uuid.uuid4().hex,
                uuid.uuid4().hex,
                "junior data analyst",
                json.dumps(
                    {
                        "profile": {
                            "use_skills": True,
                            "use_languages": False,
                            "use_education": True,
                        }
                    }
                ),
                "{}",
                "2026-11-11T00:00:00+00:00",
                "2026-11-11T00:00:00+00:00",
            ),
        )
        con.commit()
    finally:
        con.close()

    command.upgrade(config, "head")
    con = sqlite3.connect(path)
    try:
        raw = con.execute("SELECT constraints FROM autopilot_goals").fetchone()[0]
    finally:
        con.close()
    assert "use_languages" not in json.loads(raw)["profile"]


def test_0012_folds_legacy_application_contact_on_sqlite(tmp_path, monkeypatch):
    import json
    import sqlite3
    import uuid

    from app.core.config import settings

    db_url = f"sqlite+aiosqlite:///{tmp_path / 'contacts-fold.db'}"
    monkeypatch.setenv("CAREER_DATABASE_URL", db_url)
    monkeypatch.setattr(settings, "database_url", db_url, raising=False)
    config = _configured()
    command.upgrade(config, "0011")
    path = tmp_path / "contacts-fold.db"
    con = sqlite3.connect(path)
    user_id = str(uuid.uuid4()).replace("-", "")
    posting_id = str(uuid.uuid4()).replace("-", "")
    application_id = str(uuid.uuid4()).replace("-", "")
    con.execute(
        "INSERT INTO applications (user_id, posting_id, stage, applied_via, "
        "applied_via_url, contact, offer, external_ref, notes, meta, id) "
        "VALUES (?, ?, 'applied', 'url', '', ?, '{}', '', '', '{}', ?)",
        (
            user_id,
            posting_id,
            json.dumps({"name": "Ada", "email": "ada@example.com", "role": "Talent"}),
            application_id,
        ),
    )
    con.commit()
    con.close()
    command.upgrade(config, "head")
    con = sqlite3.connect(path)
    try:
        contact = con.execute("SELECT name, email, email_key, source FROM contacts").fetchone()
        assert contact == ("Ada", "ada@example.com", "ada@example.com", "application_migration")
        assert con.execute("SELECT contact_id FROM applications").fetchone()[0] is not None
        assert "contact" not in {row[1] for row in con.execute("PRAGMA table_info(applications)")}
    finally:
        con.close()


def _object_storage_tables():
    import sqlalchemy as sa

    documents = sa.table(
        "documents",
        sa.column("id", sa.Uuid()),
        sa.column("user_id", sa.Uuid()),
        sa.column("kind", sa.String()),
        sa.column("filename", sa.String()),
        sa.column("mime", sa.String()),
        sa.column("size_bytes", sa.Integer()),
        sa.column("page_count", sa.Integer()),
        sa.column("status", sa.String()),
        sa.column("error", sa.String()),
        sa.column("extraction", sa.JSON()),
        sa.column("object_key", sa.String()),
    )
    users = sa.table(
        "users",
        sa.column("id", sa.Uuid()),
        sa.column("email", sa.String()),
        sa.column("full_name", sa.String()),
        sa.column("is_active", sa.Boolean()),
        sa.column("is_admin", sa.Boolean()),
        sa.column("failed_login_attempts", sa.Integer()),
        sa.column("token_version", sa.Integer()),
    )
    jobs = sa.table(
        "background_jobs",
        sa.column("id", sa.Uuid()),
        sa.column("user_id", sa.Uuid()),
        sa.column("job_type", sa.String()),
        sa.column("status", sa.String()),
        sa.column("progress", sa.Integer()),
        sa.column("payload", sa.JSON()),
        sa.column("result", sa.JSON()),
        sa.column("attempts", sa.Integer()),
        sa.column("max_attempts", sa.Integer()),
        sa.column("cancel_requested", sa.Boolean()),
    )
    return documents, jobs, users


async def _seed_0015_async(url: str, document_id, user_id, job_id) -> None:
    from sqlalchemy.ext.asyncio import create_async_engine

    documents, jobs, users = _object_storage_tables()
    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                users.insert().values(
                    id=user_id,
                    email=f"{user_id}@example.com",
                    full_name="",
                    is_active=True,
                    is_admin=False,
                    failed_login_attempts=0,
                    token_version=1,
                )
            )
            await conn.execute(
                documents.insert().values(
                    id=document_id,
                    user_id=user_id,
                    kind="cv",
                    filename="cv.pdf",
                    mime="application/pdf",
                    size_bytes=3,
                    page_count=2,
                    status="ready",
                    error="",
                    extraction={
                        "pages": [
                            {
                                "index": 0,
                                "text": "hello",
                                "image_path": "/app/uploads/derived/x/page-0.png",
                            },
                            {"index": 1, "text": "", "image_path": None},
                        ]
                    },
                )
            )
            await conn.execute(
                jobs.insert().values(
                    id=job_id,
                    user_id=user_id,
                    job_type="data_export",
                    status="succeeded",
                    progress=100,
                    payload={},
                    result={
                        "export_path": "/app/uploads/exports/x.zip",
                        "filename": "x.zip",
                    },
                    attempts=1,
                    max_attempts=1,
                    cancel_requested=False,
                )
            )
    finally:
        await engine.dispose()


async def _assert_0015_async(url: str, document_id, user_id, job_id) -> None:
    import sqlalchemy as sa
    from sqlalchemy.ext.asyncio import create_async_engine

    documents, jobs, _users = _object_storage_tables()
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            row = (
                (
                    await conn.execute(
                        sa.select(documents.c.object_key, documents.c.extraction).where(
                            documents.c.id == document_id
                        )
                    )
                )
                .mappings()
                .one()
            )
            result: dict = (
                await conn.execute(sa.select(jobs.c.result).where(jobs.c.id == job_id))
            ).scalar_one()
    finally:
        await engine.dispose()
    # 0015 is DDL-only: keys/extraction/export paths are rewritten by
    # migrate-objects --backfill-db after a clean verify, never by upgrade.
    assert row["object_key"] is None
    assert row["extraction"]["pages"][0]["image_path"] == "/app/uploads/derived/x/page-0.png"
    assert row["extraction"]["pages"][1]["image_path"] is None
    assert result["export_path"] == "/app/uploads/exports/x.zip"
    assert result["filename"] == "x.zip"


def test_0015_adds_object_key_without_data_backfill_on_postgres(tmp_path, monkeypatch):
    import asyncio
    import uuid

    from sqlalchemy.engine import make_url

    from app.core.config import settings

    base = make_url(settings.database_url)
    if base.get_backend_name() != "postgresql":
        import pytest

        pytest.skip("postgres lane only")
    name = f"career_mig0015_{uuid_seed()}"
    admin = base.set(database="postgres").render_as_string(hide_password=False)
    temp = base.set(database=name).render_as_string(hide_password=False)
    document_id = uuid.uuid4()
    user_id = uuid.uuid4()
    job_id = uuid.uuid4()
    asyncio.run(_pg_admin(admin, f'CREATE DATABASE "{name}"'))
    try:
        monkeypatch.setenv("CAREER_DATABASE_URL", temp)
        monkeypatch.setattr(settings, "database_url", temp, raising=False)
        config = _configured()
        command.upgrade(config, "0014")
        asyncio.run(_seed_0015_async(temp, document_id, user_id, job_id))
        command.upgrade(config, "head")
        asyncio.run(_assert_0015_async(temp, document_id, user_id, job_id))
        command.downgrade(config, "0014")
        command.upgrade(config, "head")
        asyncio.run(_assert_0015_async(temp, document_id, user_id, job_id))
    finally:
        asyncio.run(_pg_drop(admin, name))


def test_0017_adds_mount_columns_without_backfill_on_sqlite(tmp_path, monkeypatch):
    """ADR-0071: the operator-feeder provenance columns are additive and
    nullable; existing sources keep NULL (no backfill, no rewrite)."""
    import sqlite3

    from app.core.config import settings

    db_url = f"sqlite+aiosqlite:///{tmp_path / 'mount-cols.db'}"
    monkeypatch.setenv("CAREER_DATABASE_URL", db_url)
    monkeypatch.setattr(settings, "database_url", db_url, raising=False)
    config = _configured()
    command.upgrade(config, "0016")
    path = tmp_path / "mount-cols.db"
    con = sqlite3.connect(path)
    con.execute(
        "INSERT INTO extension_sources (origin, subpath, kind, descriptor, candidates, "
        "secrets, status, consecutive_failures, error, id) VALUES "
        "('https://git.example.com/x/y', '', 'git', '{}', '[]', '{}', 'ok', 0, '', ?)",
        ("0" * 32,),
    )
    con.commit()
    con.close()
    command.upgrade(config, "head")
    con = sqlite3.connect(path)
    try:
        cols = {row[1] for row in con.execute("PRAGMA table_info(extension_sources)")}
        assert {"mount_key", "mount_path"} <= cols
        assert con.execute(
            "SELECT mount_key, mount_path FROM extension_sources WHERE id = ?",
            ("0" * 32,),
        ).fetchone() == (None, None)
        indexes = {row[1] for row in con.execute("PRAGMA index_list(extension_sources)")}
        assert "ix_extension_sources_mount_key" in indexes
    finally:
        con.close()
