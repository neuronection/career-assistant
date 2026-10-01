"""Migration round-trip discipline: the newest revision must downgrade
back to the previous shape and upgrade again on the suite's test DB."""

import asyncio
import os

import pytest
from alembic import command
from alembic.config import Config


@pytest.fixture(autouse=True)
def _restore_head_after_migration_test():
    """Data-migration tests run ON a pinned revision — the suite's schema
    must come back to head after each one (the identity fixtures wipe
    tables that only exist at head)."""
    yield
    command.upgrade(_configured(), "head")


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
    from datetime import datetime, timezone

    from sqlalchemy import text

    row = (await session.execute(text("SELECT id FROM users LIMIT 1"))).first()
    if row is not None:
        return str(row[0])
    user_id = _uuid.uuid4()
    now = datetime.now(timezone.utc)
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
        engine = create_async_engine(settings.database_url)
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
    assert ScriptDirectory.from_config(config).get_heads() == ["0044"], (
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
        from datetime import datetime, timezone

        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine

        from app.core.config import settings

        user_ids = [uuid.uuid4() for _ in range(2)]
        now = datetime.now(timezone.utc)
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
        from datetime import datetime, timezone

        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine

        from app.core.config import settings

        now = datetime.now(timezone.utc)
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

        engine = create_async_engine(settings.database_url)
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

    engine = create_async_engine(settings.database_url)
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


def test_0044_data_key_family_wipe_and_drain(monkeypatch):
    """Plan 16 P3d (C7): stored AI provider keys are wiped outright; the
    remaining Fernet-sealed values are re-encrypted under the DATA_KEY
    family where the legacy JWT-derived source still decrypts them and
    cleared otherwise — never left as JWT-derived ciphertext."""
    import base64
    import hashlib
    import uuid
    from datetime import datetime, timezone

    from cryptography.fernet import Fernet, InvalidToken
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.core.config import settings
    from app.core.encryption import decrypt_secret

    legacy_secret = "legacy-jwt-secret-0123456789abcdef"
    legacy = Fernet(
        base64.urlsafe_b64encode(hashlib.sha256(legacy_secret.encode()).digest())
    )

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

    now = datetime.now(timezone.utc)
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
                    names["providers"], (sealed("sk-secret-123"), "sk-plain-legacy")
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
                            sa.select(
                                providers.c.name, providers.c.api_key_encrypted
                            ).where(providers.c.name.in_(names["providers"]))
                        )
                    ).fetchall()
                    setting_rows = {
                        row[0]: row[1]
                        for row in (
                            await conn.execute(
                                sa.select(
                                    app_settings.c.key, app_settings.c.value
                                ).where(app_settings.c.key.in_(names["settings"]))
                            )
                        ).fetchall()
                    }
                    mcp_rows = {
                        row[0]: row[1]
                        for row in (
                            await conn.execute(
                                sa.select(
                                    mcp_servers.c.name, mcp_servers.c.token
                                ).where(mcp_servers.c.name.in_(names["mcp"]))
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
                        delete(providers).where(
                            providers.c.name.in_(names["providers"])
                        )
                    )
                    await conn.execute(
                        delete(app_settings).where(
                            app_settings.c.key.in_(names["settings"])
                        )
                    )
                    await conn.execute(
                        delete(mcp_servers).where(mcp_servers.c.name.in_(names["mcp"]))
                    )
            finally:
                await engine.dispose()

        asyncio.run(cleanup())
