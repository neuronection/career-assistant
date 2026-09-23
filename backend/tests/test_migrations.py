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
    assert ScriptDirectory.from_config(config).get_heads() == ["0041"], (
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


def _scope_constraint_allows_bullets() -> bool:
    """The `scope_allowed` check constraint text admits 'bullets' — probed
    dialect-aware (pg_constraint on Postgres, table DDL on SQLite)."""

    async def probe() -> bool:
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine

        from app.core.config import settings

        engine = create_async_engine(settings.DATABASE_URL)
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
            }["status_allowed"]
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
    from app.models.user_model import User

    config = _configured()
    # The suite DB may sit at head from an earlier test — force the
    # pre-fold revision so this data migration actually runs below.
    command.downgrade(config, "0040")
    command.upgrade(config, "0040")

    async def seed():
        engine = create_async_engine(settings.DATABASE_URL)
        maker = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with maker() as session:
                user = (await session.execute(select(User).limit(1))).scalars().first()
                if user is None:
                    user = User(
                        email="fold0041@example.com",
                        password_hash="$2b$12$foldmigrationplaceholder",
                    )
                    session.add(user)
                    await session.flush()
                item_id = str(user.id)
                text_row = CvSynthItem(
                    user_id=user.id,
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
                    user_id=user.id,
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
                    user_id=user.id,
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
        engine = create_async_engine(settings.DATABASE_URL)
        maker = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with maker() as session:
                cv = (
                    (
                        await session.execute(
                            select(CvDocument).where(CvDocument.id == seeded["cv"])
                        )
                    )
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
                            select(CvSynthItem).where(
                                CvSynthItem.id == seeded["bullets"]
                            )
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

    engine = create_async_engine(settings.DATABASE_URL)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with maker() as session:
            await session.execute(
                delete(CvSynthItem).where(CvSynthItem.id == seeded["text"])
            )
            await session.execute(
                delete(CvSynthItem).where(CvSynthItem.id == seeded["bullets"])
            )
            await session.execute(delete(CvDocument).where(CvDocument.title == "Fold"))
            await session.execute(
                delete(User).where(User.email == "fold0041@example.com")
            )
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
        engine = create_async_engine(settings.DATABASE_URL)
        maker = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with maker() as session:
                user = User(
                    email="fold0041b@example.com",
                    password_hash="$2b$12$foldmigrationplaceholder",
                )
                session.add(user)
                await session.flush()

                def row(scope: str, payload: dict) -> CvSynthItem:
                    return CvSynthItem(
                        user_id=user.id,
                        scope=scope,
                        variant_key="default",
                        source_refs=[
                            {"source_key": "experience", "item_id": str(user.id)}
                        ],
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
                    user_id=user.id,
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
                    user_id=user.id,
                    title="FoldB",
                    context={
                        "mode": "custom",
                        "synth_pins": {ref_merge: str(b_merge.id)},
                    },
                )
                session.add_all([cv_a, cv_b])
                await session.commit()
                return {
                    "user": user.id,
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
        engine = create_async_engine(settings.DATABASE_URL)
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
    assert items[seeded["t_merge"]].payload["achievements"] == [
        {"text": "from bullets"}
    ]
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

        engine = create_async_engine(settings.DATABASE_URL)
        maker = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with maker() as session:
                for value in (
                    seeded["t_merge"],
                    seeded["b_merge"],
                    seeded["b_only"],
                    seeded["t_same"],
                ):
                    await session.execute(
                        delete(CvSynthItem).where(CvSynthItem.id == value)
                    )
                await session.execute(
                    delete(CvDocument).where(CvDocument.title.in_(["FoldA", "FoldB"]))
                )
                await session.execute(
                    delete(User).where(User.email == "fold0041b@example.com")
                )
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(cleanup())
