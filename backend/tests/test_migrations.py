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


def _table_present() -> bool:
    """A fresh engine per probe — pool connections are loop-bound."""

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.core.config import settings

    async def probe():
        engine = create_async_engine(settings.DATABASE_URL)
        try:
            async with engine.connect() as conn:
                return bool(
                    (
                        await conn.execute(
                            text(
                                "SELECT count(*) FROM information_schema.tables "
                                "WHERE table_name = :t"
                            ),
                            {"t": "cv_synth_items"},
                        )
                    ).scalar()
                )
        finally:
            await engine.dispose()

    return bool(asyncio.run(probe()))


def _column_present(table: str, column: str) -> bool:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.core.config import settings

    async def run():
        engine = create_async_engine(settings.DATABASE_URL)
        try:
            async with engine.connect() as conn:
                return bool(
                    (
                        await conn.execute(
                            text(
                                "SELECT count(*) FROM information_schema.columns "
                                "WHERE table_name = :t AND column_name = :c"
                            ),
                            {"t": table, "c": column},
                        )
                    ).scalar()
                )
        finally:
            await engine.dispose()

    return bool(asyncio.run(run()))


def test_0027_cv_synth_items_roundtrip():
    from alembic.script import ScriptDirectory

    config = _configured()
    assert ScriptDirectory.from_config(config).get_heads() == ["0032"], (
        "revision chain stays linear on one head"
    )

    command.upgrade(config, "head")
    assert _table_present(), "cv_synth_items exists at head"

    command.downgrade(config, "0026")
    assert not _table_present(), "downgrade 0026 drops the table"

    command.upgrade(config, "head")
    assert _table_present(), "re-upgrade restores the table"


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
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.core.config import settings

    async def probe():
        engine = create_async_engine(settings.DATABASE_URL)
        try:
            async with engine.connect() as conn:
                value = (
                    await conn.execute(
                        text(
                            "SELECT is_nullable FROM information_schema.columns "
                            "WHERE table_name = 'experience_items' "
                            "AND column_name = 'start'"
                        )
                    )
                ).scalar()
                return bool(value == "YES")
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
