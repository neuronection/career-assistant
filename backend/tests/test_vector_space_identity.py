"""Stored space-key identity (plan 52 T3a).

A space's key is a value the row owns: created once, returned verbatim by
``canonical_space``/status/activation, and compared by ``create_space``.
A changed key pre-image (the tokenizer/chunker fold in T3b) must never make
an existing row look like a different live space, and a DTO whose identity
disagrees with the row is refused instead of silently recomputed.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import Column, MetaData, Table, Uuid, create_engine, event, select
from sqlalchemy.orm import Session

from app.ai.tokenizers import tiktoken_spec
from app.models.background_job_model import BackgroundJob
from app.models.vector_model import (
    RetrievalCoverageSnapshot,
    RetrievalQueryRollup,
    VectorDocument,
    VectorRecord,
)
from app.models.vector_model import VectorSpace as VectorSpaceRow
from app.services.vector_status import read_space_statuses
from app.storage import vector_contract as vc
from app.storage.tokenizer_contract import ChunkConfig
from app.storage.vector_backends import LinearBackend, VectorSpaceMismatch
from app.storage.vector_store import VectorStoreService, canonical_space

DIM = 4
NAME = "identity"


def _foreign_keys_on(dbapi_connection, _record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


@pytest.fixture
def engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'space-identity.db'}")
    event.listen(engine, "connect", _foreign_keys_on)
    metadata = MetaData()
    Table("users", metadata, Column("id", Uuid, primary_key=True))
    Table("profiles", metadata, Column("id", Uuid, primary_key=True))
    for model in (
        VectorSpaceRow,
        VectorDocument,
        VectorRecord,
        RetrievalCoverageSnapshot,
        RetrievalQueryRollup,
        BackgroundJob,
    ):
        model.__table__.to_metadata(metadata)
    metadata.create_all(engine)
    try:
        yield engine
    finally:
        engine.dispose()


def _store(engine) -> VectorStoreService:
    return VectorStoreService(engine, backend=LinearBackend(engine))


def _create(store: VectorStoreService, *, status=vc.SpaceStatus.ACTIVE, dim: int = DIM):
    return store.create_space(
        name=NAME,
        provider="openai",
        model="text-embedding-3-small",
        dim=dim,
        normalize=True,
        query_prefix=None,
        document_prefix=None,
        chunker_version="1",
        composer_version="1",
        status=status,
    )


def _v1(dim: int = DIM) -> str:
    return vc.space_key("openai", "text-embedding-3-small", dim, True, None, None, "1", "1")


def _tokenizer():
    return tiktoken_spec(max_input_tokens=8191)


def _chunk() -> ChunkConfig:
    return ChunkConfig(max_chunk_tokens=64, overlap_tokens=8, max_chars=400)


def _v2(dim: int = DIM) -> str:
    return vc.space_key_v2(
        "openai",
        "text-embedding-3-small",
        dim,
        True,
        None,
        None,
        "2",
        "1",
        tokenizer=_tokenizer(),
        chunk=_chunk(),
    )


def _create_v2(store: VectorStoreService, *, status=vc.SpaceStatus.ACTIVE):
    return store.create_space(
        name=NAME,
        provider="openai",
        model="text-embedding-3-small",
        dim=DIM,
        normalize=True,
        chunker_version="1",
        composer_version="1",
        status=status,
        tokenizer=_tokenizer(),
        chunk=_chunk(),
    )


def _replace_stored_key(engine, space_id: str, key: str) -> None:
    with Session(engine) as session:
        row = session.get(VectorSpaceRow, uuid.UUID(space_id))
        assert row is not None
        row.space_key = key
        session.commit()


def test_create_space_persists_the_v1_key(engine):
    space = _create(_store(engine))
    assert space.key == _v1()
    with Session(engine) as session:
        row = session.get(VectorSpaceRow, uuid.UUID(str(space.space_id)))
        assert row is not None
        assert row.space_key == _v1()


def test_active_create_returns_the_row_with_the_matching_stored_key(engine):
    store = _store(engine)
    first = _create(store)
    again = _create(store)
    assert again.space_id == first.space_id
    assert again.key == first.key


def test_active_create_refuses_a_different_stored_identity(engine):
    store = _store(engine)
    first = _create(store)
    other = "a" * 64
    _replace_stored_key(engine, str(first.space_id), other)

    with pytest.raises(VectorSpaceMismatch) as raised:
        _create(store)
    assert "stored identity" in str(raised.value)
    assert other in str(raised.value)


def test_active_create_refuses_a_different_configuration(engine):
    store = _store(engine)
    _create(store)
    with pytest.raises(VectorSpaceMismatch) as raised:
        _create(store, dim=DIM + 1)
    assert "stored identity" in str(raised.value)


def test_building_create_is_idempotent_by_stored_key(engine):
    store = _store(engine)
    first = _create(store, status=vc.SpaceStatus.BUILDING)
    again = _create(store, status=vc.SpaceStatus.BUILDING)
    assert again.space_id == first.space_id
    assert again.key == first.key

    _replace_stored_key(engine, str(first.space_id), "b" * 64)
    with pytest.raises(VectorSpaceMismatch):
        _create(store, status=vc.SpaceStatus.BUILDING)


def test_canonical_space_and_status_return_the_stored_key(engine):
    space = _create(_store(engine))
    stored = "c" * 64
    _replace_stored_key(engine, str(space.space_id), stored)

    with Session(engine) as session:
        row = session.get(VectorSpaceRow, uuid.UUID(str(space.space_id)))
        assert row is not None
        assert canonical_space(row).key == stored
        statuses = read_space_statuses(session)
    assert statuses[0]["space_key"] == stored


def test_resolve_refuses_a_dto_with_a_different_key_identity(engine):
    store = _store(engine)
    space = _create(store)
    forged = vc.VectorSpace(
        name=space.name,
        provider=space.provider,
        model=space.model,
        dim=space.dim,
        normalize=space.normalize,
        chunker_version=space.chunker_version,
        composer_version=space.composer_version,
        status=space.status,
        stored_key="d" * 64,
    )
    with pytest.raises(VectorSpaceMismatch) as raised:
        store.resolve_space(forged)
    assert "key identity" in str(raised.value)


def test_resolve_accepts_a_matching_stored_key_dto(engine):
    store = _store(engine)
    space = _create(store)
    resolved = store.resolve_space(space)
    assert resolved.space_id == space.space_id
    assert resolved.key == space.key


def test_model_insert_stamps_rows_created_directly(engine):
    with Session(engine) as session:
        row = VectorSpaceRow(
            name=f"direct-{uuid.uuid4().hex[:8]}",
            provider="openai",
            model="text-embedding-3-small",
            dim=DIM,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
    assert row.space_key == _v1()


def test_status_lists_no_recomputed_key_after_a_preimage_change(engine):
    """The status read is a stored-key read: the pre-image is irrelevant."""
    space = _create(_store(engine))
    stored = "e" * 64
    _replace_stored_key(engine, str(space.space_id), stored)
    with Session(engine) as session:
        row = session.scalars(select(VectorSpaceRow)).one()
        assert row.space_key == stored
        assert row.space_key != _v1()


def test_create_space_persists_the_v2_tokenizer_and_key(engine):
    space = _create_v2(_store(engine))
    assert space.token_aware is True
    assert space.chunker_version == "2", "token-aware creation forces chunker v2"
    assert space.key == _v2()
    assert space.key != _v1()
    with Session(engine) as session:
        row = session.get(VectorSpaceRow, uuid.UUID(str(space.space_id)))
        assert row is not None
        assert row.space_key == _v2()
        assert row.tokenizer_kind == "tiktoken"
        assert row.tokenizer_identifier == "cl100k_base"
        assert row.tokenizer_exact is True
        assert row.max_input_tokens == 8191
        assert row.chunk_max_tokens == 64
        assert row.chunk_overlap_tokens == 8
        assert row.chunk_max_chars == 400
        assert canonical_space(row).key == _v2()
        rebuilt = canonical_space(row).tokenizer
        assert rebuilt is not None
        assert rebuilt.kind is _tokenizer().kind
        assert rebuilt.identifier == _tokenizer().identifier
        assert rebuilt.revision == _tokenizer().revision
        assert rebuilt.artifact_sha256 == _tokenizer().artifact_sha256
        assert rebuilt.exact is True
        assert rebuilt.max_input_tokens == 8191
        assert canonical_space(row).chunk == _chunk()


def test_create_space_refuses_a_half_configured_space(engine):
    store = _store(engine)
    with pytest.raises(ValueError, match="together"):
        store.create_space(
            name=NAME,
            provider="openai",
            model="text-embedding-3-small",
            dim=DIM,
            tokenizer=_tokenizer(),
        )
    with pytest.raises(ValueError, match="together"):
        store.create_space(
            name=NAME,
            provider="openai",
            model="text-embedding-3-small",
            dim=DIM,
            chunk=_chunk(),
        )


def test_direct_model_insert_with_v2_columns_stamps_the_v2_key(engine):
    with Session(engine) as session:
        row = VectorSpaceRow(
            name=f"direct-v2-{uuid.uuid4().hex[:8]}",
            provider="openai",
            model="text-embedding-3-small",
            dim=DIM,
            chunker_version="2",
            tokenizer_kind="tiktoken",
            tokenizer_identifier="cl100k_base",
            tokenizer_artifact_sha256=_tokenizer().artifact_sha256,
            tokenizer_exact=True,
            max_input_tokens=8191,
            chunk_max_tokens=64,
            chunk_overlap_tokens=8,
            chunk_max_chars=400,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
    assert row.space_key == _v2()
    assert row.space_key != _v1(), "the direct-insert default must not stamp v1 on v2"


def test_status_reports_the_persisted_tokenizer_and_chunk(engine):
    space = _create_v2(_store(engine))
    with Session(engine) as session:
        entry = read_space_statuses(session)[0]
    assert entry["space_id"] == space.space_id
    assert entry["space_key"] == _v2()
    assert entry["token_aware"] is True
    assert entry["tokenizer"]["kind"] == "tiktoken"
    assert entry["tokenizer"]["identifier"] == "cl100k_base"
    assert entry["tokenizer"]["exact"] is True
    assert entry["chunk"] == {
        "max_chunk_tokens": 64,
        "overlap_tokens": 8,
        "max_chars": 400,
    }
