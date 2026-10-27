"""Migration round-trip discipline: the newest revision must downgrade
back to the previous shape and upgrade again on the suite's test DB."""

import asyncio
import contextlib
import os
from datetime import UTC, datetime

import pytest
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


def test_0027_cv_synth_items_roundtrip():
    from alembic.script import ScriptDirectory

    config = _configured()
    assert ScriptDirectory.from_config(config).get_heads() == ["0066"], (
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
                session.add_all(
                    [
                        JobSource(
                            key="fold-sample",
                            connector_key="synthetic",
                            kind="posting",
                            config={"keywords": "x", "fetch_details": True},
                        ),
                        JobSource(
                            key="fold-off",
                            connector_key="synthetic",
                            kind="posting",
                            config={"keywords": "x", "fetch_details": False},
                        ),
                        JobSource(
                            key="fold-plain",
                            connector_key="synthetic",
                            kind="posting",
                            config={"keywords": "x"},
                        ),
                    ]
                )
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(_run())


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
                session.add_all(
                    [
                        JobSource(
                            key="timeout-mint",
                            connector_key="mcp",
                            kind="posting",
                            config={"tool": "fetch_postings", "timeout_seconds": 30},
                        ),
                        JobSource(
                            key="timeout-kept",
                            connector_key="mcp",
                            kind="posting",
                            config={"timeout_seconds": 60},
                        ),
                        JobSource(
                            key="timeout-other",
                            connector_key="synthetic",
                            kind="posting",
                            config={"timeout_seconds": 30},
                        ),
                    ]
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
                            " VALUES (:id, :src, 'manual', :status, 0, 0, '', now(), now())"
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
