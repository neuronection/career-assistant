"""Minimal retrieval status/health reads (plan 50 §11, P1c).

Two admin reads over the portable vector store: per-space coverage and the
backend's physical health. Both read the store through the synchronous
engine (the write path's engine), never a request transaction, so a job's
committed rows are visible immediately.

The full management surface — query rollups, dashboards, alerts, quality
gates — is plan 51; this module deliberately composes only the facts the P1
status card needs and reports ``never_reconciled`` when no coverage snapshot
exists (a cold space is not a zero).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Connection, func, select, text
from sqlalchemy.orm import Session

from app.models.background_job_model import BackgroundJob
from app.models.vector_model import (
    RetrievalCoverageSnapshot,
    VectorDocument,
    VectorRecord,
)
from app.models.vector_model import VectorSpace as VectorSpaceRow
from app.storage.vector_contract import (
    BACKEND_CAPS,
    BACKEND_LINEAR,
    BACKEND_PGVECTOR,
    BACKEND_SQLITE_VEC,
    BackendHealth,
    VectorSpace,
)
from app.storage.vector_provisioning import space_status
from app.storage.vector_store import VectorStoreService, canonical_space

VECTOR_INDEX_JOB = "vector_index"
VECTOR_RECONCILE_JOB = "vector_reconcile"
VECTOR_JOB_TYPES = (VECTOR_INDEX_JOB, VECTOR_RECONCILE_JOB)
DEFAULT_SPACE = "content"
_RECENT_JOBS = 25


def _backend_name(row: VectorSpaceRow, dialect: str) -> str:
    if row.index_table is None:
        return BACKEND_LINEAR
    return BACKEND_PGVECTOR if dialect == "postgresql" else BACKEND_SQLITE_VEC


def _space_kinds(session: Session, space_id: uuid.UUID) -> list[dict[str, Any]]:
    documents = dict(
        session.execute(
            select(VectorDocument.kind, func.count(VectorDocument.id))
            .where(VectorDocument.space_id == space_id)
            .group_by(VectorDocument.kind)
        ).all()
    )
    records = dict(
        session.execute(
            select(VectorDocument.kind, func.count(VectorRecord.id))
            .join(VectorRecord, VectorRecord.document_id == VectorDocument.id)
            .where(VectorDocument.space_id == space_id)
            .group_by(VectorDocument.kind)
        ).all()
    )
    return [
        {
            "kind": kind,
            "documents": int(documents.get(kind, 0)),
            "records": int(records.get(kind, 0)),
        }
        for kind in sorted(set(documents) | set(records))
    ]


def _documents_without_records(session: Session, space_id: uuid.UUID) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(VectorDocument)
            .outerjoin(VectorRecord, VectorRecord.document_id == VectorDocument.id)
            .where(
                VectorDocument.space_id == space_id,
                VectorRecord.id.is_(None),
            )
        )
        or 0
    )


def _coverage(session: Session, space_id: uuid.UUID) -> dict[str, Any]:
    rows = list(
        session.scalars(
            select(RetrievalCoverageSnapshot)
            .where(RetrievalCoverageSnapshot.space_id == space_id)
            .order_by(RetrievalCoverageSnapshot.as_of.desc())
        )
    )
    latest: dict[str, RetrievalCoverageSnapshot] = {}
    for row in rows:
        latest.setdefault(row.kind, row)
    if not latest:
        return {
            "source": "never_reconciled",
            "as_of": None,
            "total": 0,
            "embedded": 0,
            "missing": 0,
            "stale": 0,
            "failed": 0,
            "percent": None,
            "ann_recall": None,
            "ann_recall_k": None,
            "probe_size": None,
        }
    total = sum(row.total for row in latest.values())
    embedded = sum(row.embedded for row in latest.values())
    recall_rows = [row for row in latest.values() if row.ann_recall is not None]
    return {
        "source": "snapshot",
        "as_of": max(row.as_of for row in latest.values()),
        "total": total,
        "embedded": embedded,
        "missing": sum(row.missing for row in latest.values()),
        "stale": sum(row.stale for row in latest.values()),
        "failed": sum(row.failed for row in latest.values()),
        "percent": round(embedded / total * 100, 2) if total else None,
        "ann_recall": (
            round(sum(row.ann_recall or 0.0 for row in recall_rows) / len(recall_rows), 4)
            if recall_rows
            else None
        ),
        "ann_recall_k": recall_rows[0].ann_recall_k if recall_rows else None,
        "probe_size": recall_rows[0].probe_size if recall_rows else None,
    }


def _last_jobs(session: Session, row: VectorSpaceRow) -> tuple[dict[str, Any] | None, str | None]:
    jobs = list(
        session.scalars(
            select(BackgroundJob)
            .where(BackgroundJob.job_type.in_(VECTOR_JOB_TYPES))
            .order_by(BackgroundJob.created_at.desc())
            .limit(_RECENT_JOBS)
        )
    )
    jobs.sort(key=lambda job: (job.finished_at or job.created_at, job.created_at), reverse=True)
    for job in jobs:
        payload = job.payload or {}
        target_id = payload.get("space_id")
        if target_id is not None:
            if str(target_id) != str(row.id):
                continue
        elif str(payload.get("space") or DEFAULT_SPACE) != row.name:
            continue
        summary = {
            "job_id": str(job.id),
            "job_type": job.job_type,
            "status": job.status,
            "stage": job.stage,
            "progress": job.progress,
            "finished_at": job.finished_at,
            "error": job.error,
            "result": job.result,
        }
        return summary, (job.error or None if job.status == "failed" else None)
    return None, None


def read_space_statuses(session: Session) -> list[dict[str, Any]]:
    """One entry per persisted space, ordered by name and creation."""
    dialect = session.get_bind().dialect.name
    rows = list(
        session.scalars(
            select(VectorSpaceRow).order_by(VectorSpaceRow.name, VectorSpaceRow.created_at)
        )
    )
    statuses: list[dict[str, Any]] = []
    for row in rows:
        try:
            physical = space_status(session, row)
            physical_detail: dict[str, Any] = {
                "backend": physical.backend,
                "index_table": physical.index_table,
                "table_exists": physical.table_exists,
                "table_dim": physical.table_dim,
                "index_present": physical.index_present,
                "index_rows": physical.row_count,
                "detail": physical.detail,
            }
        except Exception as exc:  # a broken physical store is a status, not a 500
            physical_detail = {
                "backend": _backend_name(row, dialect),
                "index_table": row.index_table,
                "table_exists": False,
                "table_dim": None,
                "index_present": False,
                "index_rows": 0,
                "detail": f"status probe failed: {exc}",
            }
        documents = int(
            session.scalar(
                select(func.count())
                .select_from(VectorDocument)
                .where(VectorDocument.space_id == row.id)
            )
            or 0
        )
        records = int(
            session.scalar(
                select(func.count())
                .select_from(VectorRecord)
                .where(VectorRecord.space_id == row.id)
            )
            or 0
        )
        last_reindex, last_error = _last_jobs(session, row)
        token_aware = row.tokenizer_kind is not None
        tokenizer_payload = (
            {
                "kind": row.tokenizer_kind,
                "identifier": row.tokenizer_identifier,
                "revision": row.tokenizer_revision,
                "artifact_sha256": row.tokenizer_artifact_sha256,
                "exact": bool(row.tokenizer_exact),
                "max_input_tokens": row.max_input_tokens,
            }
            if token_aware
            else None
        )
        chunk_payload = (
            {
                "max_chunk_tokens": row.chunk_max_tokens,
                "overlap_tokens": row.chunk_overlap_tokens,
                "max_chars": row.chunk_max_chars,
            }
            if token_aware
            else None
        )
        statuses.append(
            {
                "space_id": str(row.id),
                "name": row.name,
                "status": row.status,
                "provider": row.provider,
                "model": row.model,
                "dim": row.dim,
                "metric": row.metric,
                "normalize": row.normalize,
                "composer_version": row.composer_version,
                "chunker_version": row.chunker_version,
                "space_key": row.space_key,
                "token_aware": token_aware,
                "tokenizer": tokenizer_payload,
                "chunk": chunk_payload,
                "backend": physical_detail["backend"],
                "index_table": row.index_table,
                "index_present": physical_detail["index_present"],
                "documents": documents,
                "records": records,
                "documents_without_records": _documents_without_records(session, row.id),
                "kinds": _space_kinds(session, row.id),
                "coverage": _coverage(session, row.id),
                "physical": physical_detail,
                "last_reindex": last_reindex,
                "last_error": last_error,
                "backfill_done": row.backfill_done,
                "backfill_total": row.backfill_total,
                "activated_at": row.activated_at,
                "retired_at": row.retired_at,
            }
        )
    return statuses


def _extension_info(session: Session, dialect: str) -> dict[str, Any] | None:
    if dialect == "postgresql":
        version = session.execute(
            text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
        ).scalar()
        return {"name": "vector", "version": str(version)} if version is not None else None
    if dialect == "sqlite":
        try:
            import sqlite_vec

            bind = session.get_bind()
            engine = bind.engine if isinstance(bind, Connection) else bind
            with engine.connect() as connection:
                raw = connection.connection.driver_connection
                if raw is None:
                    return None
                raw.enable_load_extension(True)
                sqlite_vec.load(raw)
                version = connection.exec_driver_sql("SELECT vec_version()").scalar()
        except Exception:
            return None
        return {"name": "sqlite-vec", "version": str(version) if version else None}
    return None


def read_health(session: Session, store: VectorStoreService | None = None) -> dict[str, Any]:
    """Backend capability + physical health for every persisted space."""
    dialect = session.get_bind().dialect.name
    extension = _extension_info(session, dialect)
    backend_name = store.backend.name if store is not None else BACKEND_LINEAR
    caps = BACKEND_CAPS[backend_name]
    rows = list(
        session.scalars(
            select(VectorSpaceRow).order_by(VectorSpaceRow.name, VectorSpaceRow.created_at)
        )
    )
    spaces: list[dict[str, Any]] = []
    for row in rows:
        space: VectorSpace = canonical_space(row)
        if store is None:
            health = BackendHealth(ok=True, detail="no store wired")
        else:
            try:
                health = store.health(space)
            except Exception as exc:  # a probe failure is a health detail, not a 500
                health = BackendHealth(ok=False, detail=str(exc))
        spaces.append(
            {
                "space_id": str(row.id),
                "name": row.name,
                "status": row.status,
                "backend": _backend_name(row, dialect),
                "index_table": row.index_table,
                "differs_from_process_backend": _backend_name(row, dialect) != backend_name,
                "ok": health.ok,
                "detail": health.detail,
            }
        )
    ok = all(space["ok"] for space in spaces)
    return {
        "ok": ok,
        "dialect": dialect,
        "backend": backend_name,
        "semantic_available": bool(caps.ann and extension is not None),
        "extension": extension,
        "capabilities": {
            "ann": caps.ann,
            "max_dim": caps.max_dim,
            "max_recommended_rows": caps.max_recommended_rows,
            "scope_enforcement": str(caps.scope_enforcement),
        },
        "spaces": spaces,
        "detail": "no vector spaces provisioned" if not spaces else f"{len(spaces)} space(s)",
    }


__all__ = ["read_health", "read_space_statuses"]
