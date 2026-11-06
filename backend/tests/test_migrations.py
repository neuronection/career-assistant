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

BASELINE = "0001"


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
