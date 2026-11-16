"""Plan 210 S6 — detail-now, re-propose and bulk map actions."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

from sqlalchemy import func, select

from app.extensions.sdk import RawPosting, SalarySpec
from app.models.background_job_model import BackgroundJob
from app.models.enums import BackgroundJobType
from app.models.identity_model import AuditEvent
from app.models.job_model import Job, JobFamily
from app.models.posting_model import JobPosting, PostingChange, SourceRun
from app.services.postings import detail_service


async def _family(db, key: str = "pipeline-family") -> JobFamily:
    family = JobFamily(key=key, label=key.title(), path=key)
    db.add(family)
    await db.commit()
    return family


async def _job(db, family, code: str, *, status: str = "published") -> Job:
    job = Job(code=code, title=code.replace("-", " ").title(), family_id=family.id, status=status)
    db.add(job)
    await db.commit()
    return job


async def _posting(db, source, external_id: str, *, status: str = "new") -> JobPosting:
    posting = JobPosting(
        source_id=source.id,
        external_id=external_id,
        title="Posting",
        org="Acme",
        content_hash=uuid.uuid4().hex,
        status=status,
        raw={"description": "Old description"},
    )
    db.add(posting)
    await db.commit()
    return posting


async def test_detail_now_fetches_one_without_run_or_attempt_increment(
    db, client, auth_headers, source, synthetic_connector, monkeypatch
):
    posting = await _posting(db, source, "detail-now-1")
    posting.extract = {"skills": []}
    posting.extract_version = 3
    posting.detail_attempts = 1
    await db.commit()

    calls: list[list[str]] = []

    async def fake_fetch(_db, _source, ids):
        calls.append(list(ids))
        return (
            [
                RawPosting(
                    external_id="detail-now-1",
                    title="Posting",
                    org="Acme",
                    raw={"description": "Fresh description"},
                )
            ],
            [],
            None,
            None,
        )

    monkeypatch.setattr(detail_service, "_fetch_details", fake_fetch)
    response = await client.post(
        f"/api/v1/admin/mappings/postings/{posting.id}/detail", headers=auth_headers
    )
    assert response.status_code == 200, response.text
    assert calls == [["detail-now-1"]]
    body = response.json()
    assert body["fetched"] == 1
    assert body["changed"] is True
    assert body["extract_requeued"] is True

    await db.refresh(posting)
    assert posting.raw["description"] == "Fresh description"
    assert posting.extract is None
    assert posting.extract_version is None
    assert posting.detail_fetched_at is not None
    assert posting.detail_attempts == 1, "manual detail does not consume an attempt"

    runs = (
        await db.execute(
            select(func.count()).select_from(SourceRun).where(SourceRun.source_id == source.id)
        )
    ).scalar_one()
    assert runs == 0, "manual detail never creates an enrichment run"
    jobs = (
        (
            await db.execute(
                select(BackgroundJob).where(
                    BackgroundJob.job_type == BackgroundJobType.POSTING_EXTRACT.value
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(jobs) == 1
    journal = (
        (
            await db.execute(
                select(PostingChange).where(
                    PostingChange.posting_id == posting.id,
                    PostingChange.actor_kind == "detail_fetch",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(journal) == 2, "merge row + distinct extract-reset row"
    assert any((row.operation or {}) == {"manual": True} for row in journal)
    assert any((row.operation or {}).get("reset") == "description_changed" for row in journal)
    audit = (
        (await db.execute(select(AuditEvent).where(AuditEvent.action == "admin.mapping.detail")))
        .scalars()
        .all()
    )
    assert len(audit) == 1


async def test_detail_now_same_description_with_salary_change_does_not_reset_extract(
    db, client, auth_headers, source, synthetic_connector, monkeypatch
):
    posting = await _posting(db, source, "detail-now-salary")
    posting.extract = {"skills": ["sql"]}
    posting.extract_version = 3
    await db.commit()

    async def fake_fetch(_db, _source, _ids):
        return (
            [
                RawPosting(
                    external_id="detail-now-salary",
                    title="Posting",
                    org="Acme",
                    raw={"description": "Old description"},
                    salary=SalarySpec(min=50000, max=70000, currency="EUR"),
                )
            ],
            [],
            None,
            None,
        )

    monkeypatch.setattr(detail_service, "_fetch_details", fake_fetch)
    response = await client.post(
        f"/api/v1/admin/mappings/postings/{posting.id}/detail", headers=auth_headers
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["changed"] is True
    assert body["extract_requeued"] is False
    await db.refresh(posting)
    assert posting.salary_min == 50000
    assert posting.salary_max == 70000
    assert posting.extract == {"skills": ["sql"]}
    assert posting.extract_version == 3
    assert posting.detail_fetched_at is not None
    jobs = (
        await db.execute(
            select(func.count())
            .select_from(BackgroundJob)
            .where(BackgroundJob.job_type == BackgroundJobType.POSTING_EXTRACT.value)
        )
    ).scalar_one()
    assert jobs == 0
    journal = (
        (
            await db.execute(
                select(PostingChange).where(
                    PostingChange.posting_id == posting.id,
                    PostingChange.actor_kind == "detail_fetch",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(journal) == 1, "a non-description merge has only the merge journal row"


async def test_detail_now_connector_payload_uses_detail_ids_override(db, source, monkeypatch):
    from app.extensions import registry

    calls: list[dict] = []

    class FakeConnector:
        capabilities = SimpleNamespace(network_scopes=[], max_requests_per_minute=30)

        async def fetch(self, config, _state, **_kwargs):
            calls.append(config)
            return SimpleNamespace(items=[], partial_errors=[], run_summary=None)

    async def _resolve(_db, _key):
        return FakeConnector()

    monkeypatch.setattr(registry, "resolve_connector", _resolve)
    rows, _partials, error, _summary = await detail_service._fetch_details(
        db, source, ["external-1"]
    )
    assert rows == []
    assert error is None
    assert calls[0]["detail_mode"] == "off"
    assert calls[0]["detail_ids"] == "external-1"
    assert calls[0]["detail_limit"] == 1


async def test_detail_now_is_fail_soft_for_unsupported_rows(
    db, client, auth_headers, source, synthetic_connector, monkeypatch
):
    posting = await _posting(db, source, "detail-now-unsupported")

    async def fake_fetch(_db, _source, _ids):
        return [], [], "unsupported source", None

    monkeypatch.setattr(detail_service, "_fetch_details", fake_fetch)
    response = await client.post(
        f"/api/v1/admin/mappings/postings/{posting.id}/detail", headers=auth_headers
    )
    assert response.status_code == 200, response.text
    assert response.json()["fetched"] == 0
    assert response.json()["changed"] is False
    await db.refresh(posting)
    assert posting.detail_attempts == 0
    assert posting.raw["description"] == "Old description"


async def test_repropose_queues_the_refresh_redecision_for_a_failed_proposal(
    db, client, auth_headers, source
):
    posting = await _posting(db, source, "repropose-1")
    posting.posting_facts = {
        "job_proposal": None,
        "job_proposal_failed_reason": "unconfigured",
        "job_proposal_failed_at": datetime.now(UTC).isoformat(),
    }
    await db.commit()

    response = await client.post(
        f"/api/v1/admin/mappings/postings/{posting.id}/repropose", headers=auth_headers
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["queued"] is True
    job = (
        (
            await db.execute(
                select(BackgroundJob).where(BackgroundJob.id == uuid.UUID(body["job_id"]))
            )
        )
        .scalars()
        .one()
    )
    assert job.job_type == BackgroundJobType.POSTING_REMAP.value
    assert job.payload["refresh_proposal"] is True
    audit = (
        (await db.execute(select(AuditEvent).where(AuditEvent.action == "admin.mapping.repropose")))
        .scalars()
        .all()
    )
    assert len(audit) == 1
    assert str(posting.id) in audit[0].resource
    assert str(job.id) in audit[0].resource

    missing = await client.post(
        f"/api/v1/admin/mappings/postings/{uuid.uuid4()}/repropose", headers=auth_headers
    )
    assert missing.status_code == 404


async def test_bulk_map_maps_already_terminal_and_missing_rows(db, client, auth_headers, source):
    family = await _family(db)
    target = await _job(db, family, "bulk-target")
    active = await _posting(db, source, "bulk-active")
    active.mapping_margin = 0.3
    active.mapping_review_state = "ignored"
    active.mapping_review_reason = "other"
    active.posting_facts = {"job_proposal": {"proposal_version": 2}}
    already = await _posting(db, source, "bulk-already")
    already.catalog_job_id = target.id
    expired = await _posting(db, source, "bulk-expired", status="expired")
    missing_id = uuid.uuid4()
    await db.commit()

    response = await client.post(
        "/api/v1/admin/mappings/map-bulk",
        json={
            "posting_ids": [
                str(active.id),
                str(already.id),
                str(expired.id),
                str(missing_id),
            ],
            "job_id": str(target.id),
        },
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["affected"] == 1
    assert body["mapped"] == [str(active.id)]
    assert body["already"] == [str(already.id)]
    assert body["blocked"] == {
        str(expired.id): "terminal",
        str(missing_id): "missing",
    }

    await db.refresh(active)
    assert active.catalog_job_id == target.id
    assert active.mapping_method == "manual"
    assert active.status == "mapped"
    assert active.mapping_margin is None
    assert active.mapping_review_state is None
    assert active.mapping_review_reason is None
    assert (active.posting_facts or {})["job_proposal"] is None
    journal = (
        (
            await db.execute(
                select(PostingChange).where(
                    PostingChange.posting_id == active.id,
                    PostingChange.actor_kind == "manual",
                )
            )
        )
        .scalars()
        .all()
    )
    assert any((row.operation or {}).get("bulk_map") is True for row in journal)
    audit = (
        (await db.execute(select(AuditEvent).where(AuditEvent.action == "admin.mapping.bulk_map")))
        .scalars()
        .all()
    )
    assert len(audit) == 1

    idempotent = await client.post(
        "/api/v1/admin/mappings/map-bulk",
        json={"posting_ids": [str(active.id)], "job_id": str(target.id)},
        headers=auth_headers,
    )
    assert idempotent.json()["affected"] == 0
    assert idempotent.json()["already"] == [str(active.id)]


async def test_bulk_map_refuses_a_retired_or_draft_target(db, client, auth_headers, source):
    family = await _family(db)
    retired = await _job(db, family, "bulk-retired-target", status="retired")
    draft = await _job(db, family, "bulk-draft-target", status="draft")
    posting = await _posting(db, source, "bulk-target-refusal")

    for target in (retired, draft):
        response = await client.post(
            "/api/v1/admin/mappings/map-bulk",
            json={"posting_ids": [str(posting.id)], "job_id": str(target.id)},
            headers=auth_headers,
        )
        assert response.status_code == 409, response.text
    await db.refresh(posting)
    assert posting.catalog_job_id is None

    too_many = await client.post(
        "/api/v1/admin/mappings/map-bulk",
        json={
            "posting_ids": [str(uuid.uuid4()) for _ in range(201)],
            "job_id": str(retired.id),
        },
        headers=auth_headers,
    )
    assert too_many.status_code == 413, too_many.text
