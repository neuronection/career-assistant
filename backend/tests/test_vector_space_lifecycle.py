"""Embedding-space lifecycle and the real cutover invalidation (plan 50 §3.4/§11, P2c.1).

Build creates a ``building`` row beside the active one and provisions its
table; backfill writes only into the building space and stamps its coverage;
activation refuses without/under coverage, flips the pointer atomically and
enqueues exactly one ``POSTING_REMAP`` for the retired key. Manual and
terminal semantic rows stay untouched. Drop never removes an active space and
needs the grace period or a typed force confirmation.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.gateway import MOCK_EMBED_DIM
from app.core.database import sync_engine
from app.extensions.sdk import RawPosting
from app.models.background_job_model import BackgroundJob
from app.models.enums import MappingMethod
from app.models.posting_model import JobPosting
from app.models.taxonomy_model import Skill
from app.models.vector_model import (
    RetrievalCoverageSnapshot,
    VectorDocument,
    VectorRecord,
)
from app.models.vector_model import VectorSpace as VectorSpaceRow
from app.services.postings.mapping_remap import run_posting_remap
from app.services.postings.postings_service import upsert_posting
from app.services.vector_space_lifecycle import (
    SpaceBuildResult,
    SpaceCoverageError,
    SpaceStateError,
    VectorSpaceLifecycleService,
)
from app.storage import vector_contract as vc
from app.storage.vector_backends import VectorSpaceMismatch, choose_backend
from app.storage.vector_provisioning import provision_space
from app.storage.vector_store import VectorStoreService
from tests.vector_harness import (
    create_native_engine,
    create_sqlite_engine,
    table_exists,
)

DIM = MOCK_EMBED_DIM
NAME = "content"


async def _mock_embed(texts):
    from app.ai.gateway import _mock_embedding

    return [_mock_embedding(text) for text in texts]


def _store(engine=sync_engine) -> VectorStoreService:
    return VectorStoreService(engine)


def _service(db=None, engine=sync_engine) -> VectorSpaceLifecycleService:
    return VectorSpaceLifecycleService(
        db,
        store=_store(engine),
        provision_backend=choose_backend(engine).name,
    )


def _create_active(
    engine=sync_engine,
    *,
    name: str = NAME,
    provider: str = "legacy",
    model: str = "legacy-embed",
    dim: int = DIM,
) -> vc.VectorSpace:
    """A persisted active space with a provisioned physical index."""
    store = _store(engine)
    space = store.create_space(name=name, provider=provider, model=model, dim=dim)
    with store.session_factory() as session:
        row = session.get(VectorSpaceRow, uuid.UUID(str(space.space_id)))
        assert row is not None
        provision_space(session, row, backend=choose_backend(engine).name)
    return space


def _insert_snapshot(
    engine,
    space_id: str,
    *,
    kind: str = "skill",
    total: int = 2,
    embedded: int = 2,
    missing: int = 0,
    stale: int = 0,
    as_of: datetime | None = None,
) -> None:
    with Session(engine) as session:
        session.add(
            RetrievalCoverageSnapshot(
                id=uuid.uuid4(),
                space_id=uuid.UUID(str(space_id)),
                kind=kind,
                as_of=as_of or datetime.now(UTC),
                total=total,
                embedded=embedded,
                missing=missing,
                stale=stale,
                failed=0,
            )
        )
        session.commit()


def _count(engine, model, **conditions) -> int:
    statement = select(func.count()).select_from(model)
    for column, value in conditions.items():
        statement = statement.where(getattr(model, column) == value)
    with Session(engine) as session:
        return int(session.scalar(statement) or 0)


async def _skills(db, count: int) -> list[Skill]:
    rows = [
        Skill(
            key=f"lifecycle-{uuid.uuid4().hex[:10]}",
            label=f"Lifecycle skill {index}",
            category="test",
        )
        for index in range(count)
    ]
    db.add_all(rows)
    await db.commit()
    return rows


async def _posting(db, source, external_id: str, *, status: str = "new") -> JobPosting:
    posting = await upsert_posting(
        db,
        source,
        RawPosting(
            external_id=external_id,
            title=f"Role {external_id}",
            url=f"https://syn.example/{external_id}",
            skills_raw=[],
            raw={},
        ),
    )
    assert posting is not None
    posting.status = status
    await db.flush()
    return posting


def _semantic(posting: JobPosting, space_key: str | None) -> None:
    posting.mapping_method = MappingMethod.SEMANTIC.value
    posting.mapping_features = (
        {"schema_version": 1, "space_key": space_key} if space_key is not None else None
    )


# ------------------------------------------------------------------ build


async def test_build_creates_a_building_row_and_a_physical_table(db):
    old = _create_active()
    service = _service(db)
    built = await service.build_space(
        NAME,
        provider="openai",
        model="text-embedding-3-small",
        dim=DIM,
    )

    assert isinstance(built, SpaceBuildResult)
    assert built.status == "building"
    assert built.space_id != old.space_id
    with Session(sync_engine) as session:
        rows = list(session.scalars(select(VectorSpaceRow).where(VectorSpaceRow.name == NAME)))
        by_status = {row.status: row for row in rows}
        assert set(by_status) == {"active", "building"}
        assert str(by_status["active"].id) == old.space_id
        assert by_status["building"].index_table == built.index_table
    if built.backend == vc.BACKEND_LINEAR:
        assert built.index_table is None
    else:
        assert built.index_table is not None
        assert table_exists(sync_engine, built.index_table)


async def test_build_is_idempotent_for_the_same_building_configuration(db):
    service = _service(db)
    first = await service.build_space(
        NAME, provider="openai", model="text-embedding-3-small", dim=DIM
    )
    second = await service.build_space(
        NAME, provider="openai", model="text-embedding-3-small", dim=DIM
    )
    assert second.space_id == first.space_id

    with pytest.raises(VectorSpaceMismatch) as raised:
        await service.build_space(NAME, provider="openai", model="other-model", dim=DIM)
    assert "building space" in str(raised.value)


# --------------------------------------------------------------- backfill


async def test_backfill_indexes_only_the_building_space_with_its_own_coverage(db):
    old = _create_active()
    await _skills(db, 2)
    service = _service(db)
    built = await service.build_space(NAME, provider="mock", model="mock-small", dim=DIM)

    result = await service.backfill_space(
        built.space_id,
        kinds=("skill",),
        embedder=_mock_embed,
        scan_limit=50,
    )

    assert result.space_id == built.space_id
    assert result.done is True
    assert result.embedded == 2
    assert _count(sync_engine, VectorDocument, space_id=uuid.UUID(built.space_id)) == 2
    assert _count(sync_engine, VectorRecord, space_id=uuid.UUID(built.space_id)) == 2
    assert _count(sync_engine, VectorDocument, space_id=uuid.UUID(old.space_id or "")) == 0
    assert _count(sync_engine, VectorRecord, space_id=uuid.UUID(old.space_id or "")) == 0

    with Session(sync_engine) as session:
        snapshots = list(
            session.scalars(
                select(RetrievalCoverageSnapshot).where(
                    RetrievalCoverageSnapshot.space_id == uuid.UUID(built.space_id)
                )
            )
        )
        assert [(row.kind, row.total, row.embedded) for row in snapshots] == [("skill", 2, 2)]
        row = session.get(VectorSpaceRow, uuid.UUID(built.space_id))
        assert row is not None
        assert (row.backfill_done, row.backfill_total) == (2, 2)


async def test_backfill_refuses_the_active_space(db):
    old = _create_active()
    service = _service(db)
    with pytest.raises(SpaceStateError) as raised:
        await service.backfill_space(old.space_id or "", kinds=("skill",))
    assert "expected one of ('building',)" in str(raised.value)


# -------------------------------------------------------------- activation


async def test_activation_refuses_without_a_coverage_snapshot(db):
    service = _service(db)
    built = await service.build_space(
        NAME, provider="openai", model="text-embedding-3-small", dim=DIM
    )
    with pytest.raises(SpaceCoverageError) as raised:
        await service.activate_space(built.space_id, kinds=("skill",))
    assert "no coverage snapshot" in str(raised.value)


async def test_activation_refuses_below_the_coverage_gate(db):
    service = _service(db)
    built = await service.build_space(
        NAME, provider="openai", model="text-embedding-3-small", dim=DIM
    )
    _insert_snapshot(sync_engine, built.space_id, total=200, embedded=198)
    with pytest.raises(SpaceCoverageError) as raised:
        await service.activate_space(built.space_id, coverage_gate=0.995, kinds=("skill",))
    assert "below the coverage gate" in str(raised.value)


async def test_activation_flips_and_retires_atomically(db, monkeypatch):
    old = _create_active()
    service = _service(db)
    built = await service.build_space(
        NAME, provider="openai", model="text-embedding-3-small", dim=DIM
    )
    _insert_snapshot(sync_engine, built.space_id, total=200, embedded=199)

    # Activation reads health; it must never provision (no request-time DDL).
    from app.services import vector_space_lifecycle as lifecycle

    def _no_ddl(*_args, **_kwargs):
        raise AssertionError("activation must not provision or issue DDL")

    monkeypatch.setattr(lifecycle, "provision_space", _no_ddl)

    result = await service.activate_space(built.space_id, coverage_gate=0.995, kinds=("skill",))

    assert result.already_active is False
    assert result.previous_space_id == old.space_id
    assert result.previous_space_key == old.key
    assert result.space_key == built.space_key
    assert result.gate is not None and result.gate.coverage["skill"] == 0.995
    assert result.remap_job_id is not None

    with Session(sync_engine) as session:
        rows = list(session.scalars(select(VectorSpaceRow).where(VectorSpaceRow.name == NAME)))
        active = [row for row in rows if row.status == "active"]
        retired = [row for row in rows if row.status == "retired"]
        assert [str(row.id) for row in active] == [built.space_id]
        assert [str(row.id) for row in retired] == [old.space_id]
        assert active[0].activated_at is not None
        assert retired[0].retired_at is not None

    jobs = list(
        (await db.execute(select(BackgroundJob).where(BackgroundJob.job_type == "posting_remap")))
        .scalars()
        .all()
    )
    assert len(jobs) == 1
    assert jobs[0].payload["space_key"] == old.key
    assert jobs[0].payload["all_postings"] is False


async def test_first_activation_enqueues_no_remap(db):
    service = _service(db)
    built = await service.build_space(
        NAME, provider="openai", model="text-embedding-3-small", dim=DIM
    )
    _insert_snapshot(sync_engine, built.space_id, total=1, embedded=1)
    result = await service.activate_space(built.space_id, kinds=("skill",))
    assert result.previous_space_key is None
    assert result.remap_job_id is None
    jobs = (
        (await db.execute(select(BackgroundJob).where(BackgroundJob.job_type == "posting_remap")))
        .scalars()
        .all()
    )
    assert jobs == []


async def test_activation_is_idempotent_for_an_active_space(db):
    service = _service(db)
    built = await service.build_space(
        NAME, provider="openai", model="text-embedding-3-small", dim=DIM
    )
    _insert_snapshot(sync_engine, built.space_id, total=1, embedded=1)
    first = await service.activate_space(built.space_id, kinds=("skill",))
    second = await service.activate_space(built.space_id, kinds=("skill",))
    assert first.already_active is False
    assert second.already_active is True
    assert second.remap_job_id is None


async def test_activation_cutover_remaps_old_and_legacy_rows_only(db, source):
    old = _create_active()
    service = _service(db)
    built = await service.build_space(
        NAME, provider="openai", model="text-embedding-3-small", dim=DIM
    )
    _insert_snapshot(sync_engine, built.space_id, total=1, embedded=1)

    stale = await _posting(db, source, "lifecycle-stale")
    _semantic(stale, old.key)
    current = await _posting(db, source, "lifecycle-current")
    _semantic(current, built.space_key)
    legacy = await _posting(db, source, "lifecycle-legacy")
    _semantic(legacy, None)
    manual = await _posting(db, source, "lifecycle-manual")
    manual.mapping_method = MappingMethod.MANUAL.value
    manual.mapping_features = {"schema_version": 1, "space_key": old.key}
    expired = await _posting(db, source, "lifecycle-expired", status="expired")
    _semantic(expired, old.key)
    await db.flush()

    result = await service.activate_space(built.space_id, kinds=("skill",))
    job = (
        (
            await db.execute(
                select(BackgroundJob).where(
                    BackgroundJob.job_type == "posting_remap",
                    BackgroundJob.payload["space_key"].as_string() == old.key,
                )
            )
        )
        .scalars()
        .one()
    )
    assert result.remap_job_id == str(job.id)
    assert job.payload["continuation_key"].startswith(old.key)

    remap = await run_posting_remap(db, job.payload)

    assert remap["remapped"] == 2, "the retired-space and legacy semantic rows"
    assert remap["skipped"] == 1, "the row already recorded the new space"
    assert stale.mapping_method is None
    assert legacy.mapping_method is None
    assert current.mapping_method == MappingMethod.SEMANTIC.value
    assert current.mapping_features["space_key"] == built.space_key
    assert manual.mapping_method == MappingMethod.MANUAL.value
    assert manual.mapping_features["space_key"] == old.key
    assert expired.mapping_method == MappingMethod.SEMANTIC.value
    assert expired.mapping_features["space_key"] == old.key


# ------------------------------------------------------------ retire/drop


async def test_retire_refuses_the_active_space(db):
    old = _create_active()
    service = _service(db)
    with pytest.raises(SpaceStateError):
        await service.retire_space(old.space_id or "")


async def test_drop_refuses_active_and_building_spaces(db):
    old = _create_active()
    service = _service(db)
    with pytest.raises(SpaceStateError) as active_error:
        await service.drop_space(old.space_id or "", force=True, confirm=NAME)
    assert "active" in str(active_error.value)

    built = await service.build_space(
        NAME, provider="openai", model="text-embedding-3-small", dim=DIM
    )
    with pytest.raises(SpaceStateError) as building_error:
        await service.drop_space(built.space_id)
    assert "retire it before drop" in str(building_error.value)


async def test_retired_space_drop_honours_the_grace_period_and_force(db):
    service = _service(db)
    built = await service.build_space(
        NAME, provider="openai", model="text-embedding-3-small", dim=DIM
    )
    retired = await service.retire_space(built.space_id)
    assert retired["status"] == "retired"

    with pytest.raises(SpaceStateError) as grace_error:
        await service.drop_space(built.space_id)
    assert "grace period" in str(grace_error.value)

    with pytest.raises(SpaceStateError) as confirm_error:
        await service.drop_space(built.space_id, force=True, confirm="wrong-name")
    assert "--confirm" in str(confirm_error.value)

    dropped = await service.drop_space(built.space_id, force=True, confirm=NAME)
    assert dropped["dropped"] is True
    with Session(sync_engine) as session:
        assert session.get(VectorSpaceRow, uuid.UUID(built.space_id)) is None
    if built.index_table is not None:
        assert table_exists(sync_engine, built.index_table) is False


async def test_a_retired_space_drops_after_the_grace_period_without_force(db):
    service = _service(db)
    built = await service.build_space(
        NAME, provider="openai", model="text-embedding-3-small", dim=DIM
    )
    await service.retire_space(built.space_id)
    with Session(sync_engine) as session:
        row = session.get(VectorSpaceRow, uuid.UUID(built.space_id))
        assert row is not None
        row.retired_at = datetime.now(UTC) - timedelta(days=30)
        session.commit()

    dropped = await service.drop_space(built.space_id)
    assert dropped["dropped"] is True


# ------------------------------------------------------- dialect coverage


@pytest.fixture(params=["native", "sqlite"])
def space_engine(request, tmp_path) -> Iterator:
    engine = (
        create_sqlite_engine(tmp_path / "vector-space-lifecycle.db")
        if request.param == "sqlite"
        else create_native_engine()
    )
    try:
        yield engine
    finally:
        engine.dispose()


async def test_build_and_first_activation_on_both_dialects(space_engine):
    service = _service(engine=space_engine)
    built = await service.build_space(
        NAME, provider="openai", model="text-embedding-3-small", dim=DIM
    )
    _insert_snapshot(space_engine, built.space_id, total=1, embedded=1)
    result = await service.activate_space(built.space_id, kinds=("skill",))
    assert result.already_active is False
    assert result.previous_space_key is None
    with Session(space_engine) as session:
        rows = list(session.scalars(select(VectorSpaceRow).where(VectorSpaceRow.name == NAME)))
        assert [row.status for row in rows] == ["active"]
