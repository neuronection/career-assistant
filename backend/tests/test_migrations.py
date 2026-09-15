"""Migration round-trip discipline: the newest revision must downgrade
back to the previous shape and upgrade again on the suite's test DB."""

import asyncio
import os

from alembic import command
from alembic.config import Config


def _configured() -> Config:
    from app.core.config import settings

    os.environ["DATABASE_URL"] = settings.DATABASE_URL
    return Config("alembic.ini")


def _table_present(table: str = "cv_synth_items") -> bool:
    """A fresh engine per probe — pool connections are loop-bound.

    Probes via the SQLAlchemy inspector so the round-trips also run on the
    SQLite (desktop) CI profile — information_schema is Postgres-only.
    """

    async def probe():
        from sqlalchemy import inspect
        from sqlalchemy.ext.asyncio import create_async_engine

        from app.core.config import settings

        engine = create_async_engine(settings.DATABASE_URL)
        try:
            async with engine.connect() as conn:
                return bool(
                    await conn.run_sync(
                        lambda sync_conn: inspect(sync_conn).has_table(table)
                    )
                )
        finally:
            await engine.dispose()

    return bool(asyncio.run(probe()))


def _column_present(table: str, column: str) -> bool:
    from sqlalchemy import inspect
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.core.config import settings

    async def run():
        engine = create_async_engine(settings.DATABASE_URL)
        try:
            async with engine.connect() as conn:
                columns = await conn.run_sync(
                    lambda sync_conn: [
                        col["name"] for col in inspect(sync_conn).get_columns(table)
                    ]
                )
            return column in columns
        finally:
            await engine.dispose()

    return bool(asyncio.run(run()))


def test_0027_cv_synth_items_roundtrip():
    from alembic.script import ScriptDirectory

    config = _configured()
    assert ScriptDirectory.from_config(config).get_heads() == ["0035"], (
        "revision chain stays linear on one head"
    )

    command.upgrade(config, "head")
    assert _table_present(), "cv_synth_items exists at head"

    command.downgrade(config, "0026")
    assert not _table_present(), "downgrade 0026 drops the table"

    command.upgrade(config, "head")
    assert _table_present(), "re-upgrade restores the table"


def test_0033_profile_proposals_roundtrip():
    config = _configured()

    command.upgrade(config, "head")
    assert _table_present("profile_proposals"), "profile_proposals exists at head"

    command.downgrade(config, "0032")
    assert not _table_present("profile_proposals"), "downgrade 0032 drops the table"

    command.upgrade(config, "head")
    assert _table_present("profile_proposals"), "re-upgrade restores the table"


def _schedules_checks() -> dict[str, str]:
    """kind/task CHECK expressions on `schedules` (dialect-safe)."""

    async def run():
        from sqlalchemy import inspect
        from sqlalchemy.ext.asyncio import create_async_engine

        from app.core.config import settings

        engine = create_async_engine(settings.DATABASE_URL)
        try:
            async with engine.connect() as conn:
                checks = await conn.run_sync(
                    lambda sync_conn: inspect(sync_conn).get_check_constraints(
                        "schedules"
                    )
                )
            # The metadata naming convention renders prefixed names
            # (ck_schedules_kind_allowed) — normalize to the short name.
            return {
                c["name"].replace("ck_schedules_", ""): c["sqltext"] for c in checks
            }
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
    assert not _column_present("certifications", "language_code"), (
        "downgrade 0025 drops the column"
    )

    command.upgrade(config, "head")
    assert _column_present("certifications", "language_code"), (
        "re-upgrade restores the column"
    )


def test_0031_user_skill_hidden_roundtrip():
    config = _configured()

    command.upgrade(config, "head")
    assert _column_present("user_skills", "hidden"), "user_skills.hidden exists at head"

    command.downgrade(config, "0030")
    assert not _column_present("user_skills", "hidden"), (
        "downgrade 0030 drops the column"
    )

    command.upgrade(config, "head")
    assert _column_present("user_skills", "hidden"), "re-upgrade restores the column"


def test_0029_run_linkage_roundtrip():
    config = _configured()

    command.upgrade(config, "head")
    assert _column_present("ai_generations", "run_id"), (
        "ai_generations.run_id exists at head"
    )
    assert _column_present("ai_generations", "run_stage"), (
        "ai_generations.run_stage exists at head"
    )


def test_0030_derive_enabled_roundtrip():
    config = _configured()

    command.upgrade(config, "head")
    assert _column_present("user_skills", "derive_enabled"), (
        "user_skills.derive_enabled exists at head"
    )

    command.downgrade(config, "0029")
    assert not _column_present("user_skills", "derive_enabled"), (
        "downgrade 0029 drops the column"
    )

    command.upgrade(config, "head")
    assert _column_present("user_skills", "derive_enabled"), (
        "re-upgrade restores the column"
    )

    command.downgrade(config, "0028")
    assert not _column_present("ai_generations", "run_id"), (
        "downgrade 0028 drops the run columns"
    )
    assert not _column_present("ai_generations", "run_stage"), (
        "downgrade 0028 drops the run columns"
    )

    command.upgrade(config, "head")
    assert _column_present("ai_generations", "run_id"), (
        "re-upgrade restores the run columns"
    )
    assert _column_present("ai_generations", "run_stage"), (
        "re-upgrade restores the run columns"
    )


def _start_nullable() -> bool:
    from sqlalchemy import inspect
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.core.config import settings

    async def probe():
        engine = create_async_engine(settings.DATABASE_URL)
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
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setattr("app.core.config.settings.DATABASE_URL", db_url, raising=False)
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

        engine = create_async_engine(settings.DATABASE_URL)
        try:
            async with engine.connect() as conn:
                checks = await conn.run_sync(
                    lambda sync_conn: inspect(sync_conn).get_check_constraints(
                        "profile_proposals"
                    )
                )
            return {
                c["name"].replace("ck_profile_proposals_", ""): c["sqltext"]
                for c in checks
            }["kind_allowed"]
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
