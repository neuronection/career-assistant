"""Layer coverage for bulk reprocessing (plan 184 S3.1): every AI-adjacent
queue layer — requeue as a fresh row → the real HANDLERS path → success,
with the ledger linkage the layers write (run_id/run_stage)."""

import asyncio
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from app.core.config import settings
from app.models.ai_model import AIGeneration
from app.models.background_job_model import BackgroundJob
from app.services.cv.cv_source_service import (
    CvPageTextSource,
    CvSourceExtraction,
    CvSourcePage,
)
from app.services.job_reprocess_service import JobReprocessService
from app.services.job_worker import drain_queue
from tests.conftest import _make_posting, decode_session_token

CV_TEXT = (
    "ILIAS PETROU\nAthens, Greece\n\nEXPERIENCE\nData Analyst intern at Acme (2025)\n"
    "Analyzed sales data with SQL and Python.\n\nSKILLS\nPython, SQL, Excel\n\n"
    "EDUCATION\nHigh school diploma, 2024\n"
)


def _uid(auth_headers) -> uuid.UUID:
    return decode_session_token(auth_headers["Authorization"].split(" ", 1)[1])[0]


async def _failed_job(
    *,
    job_type: str,
    payload: dict,
    user_id: uuid.UUID | None = None,
) -> BackgroundJob:
    return BackgroundJob(
        user_id=user_id,
        job_type=job_type,
        status="failed",
        attempts=2,
        max_attempts=2,
        error="503 provider unavailable",
        payload=payload,
        created_at=datetime.now(UTC),
    )


async def _requeue_and_drain(db, job: BackgroundJob) -> uuid.UUID:
    result = await JobReprocessService(db).requeue(
        job_ids=[job.id], window=None, date_from=None, date_to=None
    )
    assert result["requeued"] == 1
    new_id = result["items"][0]["new_job_id"]
    await asyncio.wait_for(drain_queue(db), timeout=60)
    return new_id if isinstance(new_id, uuid.UUID) else uuid.UUID(str(new_id))


async def _job_status(db, job_id: uuid.UUID) -> tuple[str, str]:
    row = (
        await db.execute(
            select(BackgroundJob.status, BackgroundJob.error).where(BackgroundJob.id == job_id)
        )
    ).one()
    return row.status, row.error or ""


async def _ledger_rows(db, run_id: uuid.UUID) -> list[AIGeneration]:
    rows = await db.execute(select(AIGeneration).where(AIGeneration.run_id == run_id))
    return list(rows.scalars().all())


async def _seed_cv_document(db, user_id: uuid.UUID, *, extraction: dict | None):
    from app.models.document_model import Document

    document = Document(
        user_id=user_id,
        kind="cv",
        filename="cv.txt",
        mime="text/plain",
        size_bytes=len(CV_TEXT.encode()),
        page_count=0,
        status="ready" if extraction else "uploaded",
        error="",
        extraction=extraction,
    )
    db.add(document)
    await db.flush()
    path = Path(settings.upload_dir) / f"{document.id}.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(CV_TEXT, encoding="utf-8")
    return document, path


async def test_posting_extract_reprocesses_and_links_the_ledger(db, source, seeded_catalog):
    posting = await _make_posting(db, source)
    job = await _failed_job(job_type="posting_extract", payload={"posting_id": str(posting.id)})
    db.add(job)
    await db.flush()

    new_id = await _requeue_and_drain(db, job)
    status, error = await _job_status(db, new_id)
    assert status == "succeeded", error
    await db.refresh(posting)
    assert posting.extract_version is not None, "the deep pass ran"

    ledger = await _ledger_rows(db, new_id)
    assert ledger, "the requeued attempt writes fresh ledger rows"
    assert all(row.run_stage == "posting_extract" for row in ledger)


async def test_detail_enrichment_reprocesses(db, source, seeded_catalog):
    await _make_posting(db, source)
    job = await _failed_job(job_type="detail_enrichment", payload={"source_id": str(source.id)})
    db.add(job)
    await db.flush()

    new_id = await _requeue_and_drain(db, job)
    status, error = await _job_status(db, new_id)
    assert status == "succeeded", error


async def test_query_curator_reprocesses(db):
    job = await _failed_job(job_type="query_curator", payload={})
    db.add(job)
    await db.flush()

    new_id = await _requeue_and_drain(db, job)
    status, error = await _job_status(db, new_id)
    assert status == "succeeded", error


async def test_catalog_enrich_reprocesses(db):
    job = await _failed_job(job_type="catalog_enrich", payload={"limit": 2})
    db.add(job)
    await db.flush()

    new_id = await _requeue_and_drain(db, job)
    status, error = await _job_status(db, new_id)
    assert status == "succeeded", error


async def test_cv_extract_text_reprocesses_and_chains_cv_parse(client, db):
    from tests.conftest import session_headers

    login = await client.post(
        "/api/v1/auth/register",
        json={"email": "cv-intake@example.com", "password": "supersecret1"},
    )
    assert login.status_code == 201
    headers = session_headers(login)
    uid = decode_session_token(headers["Authorization"].split(" ", 1)[1])[0]

    document, path = await _seed_cv_document(db, uid, extraction=None)
    job = await _failed_job(
        job_type="cv_extract_text",
        payload={"document_id": str(document.id)},
        user_id=uid,
    )
    db.add(job)
    await db.flush()
    try:
        new_id = await _requeue_and_drain(db, job)
        status, error = await _job_status(db, new_id)
        assert status == "succeeded", error
        rows = (
            (await db.execute(select(BackgroundJob).where(BackgroundJob.requeue_of == job.id)))
            .scalars()
            .all()
        )
        assert [str(row.id) for row in rows] == [str(new_id)]
    finally:
        path.unlink(missing_ok=True)


async def test_cv_ocr_reprocesses(client, db):
    from tests.conftest import session_headers

    login = await client.post(
        "/api/v1/auth/register",
        json={"email": "cv-ocr@example.com", "password": "supersecret1"},
    )
    assert login.status_code == 201
    headers = session_headers(login)
    uid = decode_session_token(headers["Authorization"].split(" ", 1)[1])[0]

    document, path = await _seed_cv_document(db, uid, extraction=None)
    job = await _failed_job(
        job_type="cv_ocr",
        payload={"document_id": str(document.id)},
        user_id=uid,
    )
    db.add(job)
    await db.flush()
    try:
        new_id = await _requeue_and_drain(db, job)
        status, error = await _job_status(db, new_id)
        assert status == "succeeded", error
    finally:
        path.unlink(missing_ok=True)


async def test_cv_parse_reprocesses(client, db):
    from tests.conftest import session_headers

    login = await client.post(
        "/api/v1/auth/register",
        json={"email": "cv-parse@example.com", "password": "supersecret1"},
    )
    assert login.status_code == 201
    headers = session_headers(login)
    uid = decode_session_token(headers["Authorization"].split(" ", 1)[1])[0]

    extraction = CvSourceExtraction(
        pages=[CvSourcePage(index=0, text=CV_TEXT, source=CvPageTextSource.TEXT_LAYER.value)],
        full_text=CV_TEXT,
        has_text_layer=True,
        ocr_used=False,
        content_sha256="0" * 64,
        engine={"ocr": "none"},
    )
    document, path = await _seed_cv_document(db, uid, extraction=extraction.model_dump(mode="json"))
    job = await _failed_job(
        job_type="cv_parse",
        payload={"document_id": str(document.id)},
        user_id=uid,
    )
    db.add(job)
    await db.flush()
    try:
        new_id = await _requeue_and_drain(db, job)
        status, error = await _job_status(db, new_id)
        assert status == "succeeded", error
    finally:
        path.unlink(missing_ok=True)


async def test_smart_digest_reprocesses(db, client):
    from tests.conftest import session_headers

    login = await client.post(
        "/api/v1/auth/register",
        json={"email": "digest@example.com", "password": "supersecret1"},
    )
    assert login.status_code == 201
    headers = session_headers(login)
    uid = decode_session_token(headers["Authorization"].split(" ", 1)[1])[0]

    job = await _failed_job(job_type="smart_digest", payload={"user_id": str(uid)}, user_id=uid)
    db.add(job)
    await db.flush()

    new_id = await _requeue_and_drain(db, job)
    status, error = await _job_status(db, new_id)
    assert status == "succeeded", error


async def test_radar_digest_reprocesses(db, client, seeded_catalog, kinds):
    from app.models.enums import RadarCadence
    from app.models.radar_model import JobRadar
    from app.models.user_model import Profile
    from tests.conftest import session_headers

    login = await client.post(
        "/api/v1/auth/register",
        json={"email": "radar@example.com", "password": "supersecret1"},
    )
    assert login.status_code == 201
    headers = session_headers(login)
    uid = decode_session_token(headers["Authorization"].split(" ", 1)[1])[0]

    profile = (await db.execute(select(Profile).where(Profile.user_id == uid))).scalars().first()
    assert profile is not None, "registration provisions the Default profile"
    radar = JobRadar(
        profile_id=profile.id,
        keywords=["analyst"],
        locations=[],
        seniority=[],
        cadence=RadarCadence.DAILY.value,
        enabled=True,
    )
    db.add(radar)
    await db.flush()

    job = await _failed_job(
        job_type="radar_digest",
        payload={"radar_id": str(radar.id), "user_id": str(uid)},
        user_id=uid,
    )
    db.add(job)
    await db.flush()

    new_id = await _requeue_and_drain(db, job)
    status, error = await _job_status(db, new_id)
    assert status == "succeeded", error


async def test_autopilot_run_reprocesses(client, db, auth_headers, profile_ready, seeded_catalog):
    uid = _uid(auth_headers)
    created = await client.post(
        "/api/v1/autopilot/goals",
        json={
            "goal_text": "Find me a junior data job where I can use programming",
            "constraints": {"salary_min": 1},
        },
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    goal_id = created.json()["id"]

    job = await _failed_job(
        job_type="autopilot_run",
        payload={"goal_id": goal_id},
        user_id=uid,
    )
    db.add(job)
    await db.flush()

    new_id = await _requeue_and_drain(db, job)
    status, error = await _job_status(db, new_id)
    assert status == "succeeded", error
