"""slice 4 — catalog parity: v2 vocabulary on archetypes,
benefits-driven values hints, moderation-reviewed enrichment sweep."""

from app.models.enums import ScheduleKind
from app.services.catalog_enrich_service import CatalogEnrichService
from app.services.fit.dimensions import FIT_VERSION, job_values_signal
from app.services.scheduler.runner import KIND_TASKS


def test_job_attributes_accept_v2_vocabulary():
    from app.schemas.job import JobAttributes

    attrs = JobAttributes.model_validate(
        {
            "contract_type": "permanent",
            "work_hours": {
                "pattern": "full_time",
                "hours_per_week_min": 35,
                "hours_per_week_max": 40,
            },
            "schedule_cues": ["flexible", "shift_work"],
            "travel_required": {"level": "occasional", "days_per_month": None},
            "benefits_kinds": ["healthcare", "learning"],
        }
    )
    assert attrs.contract_type == "permanent"
    assert attrs.work_hours.hours_per_week_min == 35
    assert attrs.travel_required.days_per_month is None

    legacy = JobAttributes.model_validate({})
    assert legacy.contract_type is None
    assert legacy.schedule_cues == [], "old attribute shapes stay valid"


def test_benefit_kinds_feed_values_signal():
    base = job_values_signal({"work_style": {}})
    assert base == {}, "no inputs ⇒ no signal"

    pension_only = job_values_signal({"benefits_kinds": ["pension"]})
    assert pension_only == {"values.security": 7.0}, (
        "a pension alone is a grounded security signal"
    )

    combined = job_values_signal(
        {
            "demand": {"outlook": "stable"},
            "benefits_kinds": ["equity", "leave", "meals"],
        }
    )
    assert combined["values.security"] == 6.0
    assert combined["values.compensation"] == 8.0, "strongest hint wins"
    assert combined["values.work_life_balance"] == 7.0


def test_fit_version_bumped_for_signal_change():
    assert FIT_VERSION == 5


async def test_generator_emits_v2_vocabulary(db, auth_headers, seeded_catalog):
    from app.ai.agents.job_generator import generate_jobs
    from app.core.security import decode_access_token

    token = auth_headers["Authorization"].split(" ", 1)[1]
    user_id = decode_access_token(token)[0]
    drafts = await generate_jobs(
        db,
        user_id,
        count=2,
        family_keys=["technology"],
        interest_keys=["technology-software"],
        skill_keys=["programming"],
    )
    assert drafts.drafts
    attrs = drafts.drafts[0].attributes
    assert attrs.contract_type in ("permanent", "contract")
    assert attrs.work_hours.pattern == "full_time"
    assert "flexible" in attrs.schedule_cues
    assert set(attrs.benefits_kinds) == {"learning", "pension"}


async def test_enrichment_sweep_propose_apply_reject(
    client, auth_headers, client_admin_headers, seeded_catalog, db
):
    from sqlalchemy import select

    from app.models.job_model import Job

    job = (
        (await db.execute(select(Job).where(Job.code == "software-developer")))
        .scalars()
        .first()
    )
    assert job is not None
    salary_before = (job.attributes or {}).get("salary")
    assert salary_before, "seeded archetype carries human-owned salary"

    service = CatalogEnrichService(db)
    assert job in await service.candidates(), "archetype lacks v2 fields"

    result = await service.run_sweep(limit=5)
    assert result["proposed"] >= 1
    await db.refresh(job)
    proposal = (job.ai_metadata or {}).get("enrichment_proposal")
    assert proposal and proposal["contract_type"]
    assert job not in await service.candidates(), "pending proposal holds the slot"

    salary_before = dict(salary_before)
    applied = await service.apply(job)
    assert applied is job
    attrs = job.attributes
    assert attrs["contract_type"] == proposal["contract_type"]
    assert attrs["work_hours"] == proposal["work_hours"]
    assert attrs["salary"] == salary_before, "salary stays human-owned"
    assert (job.ai_metadata or {}).get("enrichment_proposal") is None
    assert job not in await service.candidates()

    other = next(
        candidate for candidate in await service.pending() if candidate.id != job.id
    )
    rejected = await service.reject(other)
    assert rejected is other
    assert ((other.ai_metadata or {}).get("enrichment_proposal")) is None
    assert ((other.ai_metadata or {}).get("enrichment_rejected_at")) is not None


async def test_enrichment_moderation_endpoints(
    client, auth_headers, client_admin_headers, seeded_catalog, db
):
    from sqlalchemy import select

    from app.models.job_model import Job

    job = (
        (await db.execute(select(Job).where(Job.code == "software-developer")))
        .scalars()
        .first()
    )
    service = CatalogEnrichService(db)
    await service.run_sweep(limit=5)
    await db.refresh(job)

    queue = (
        await client.get("/api/v1/admin/jobs/enrichment", headers=client_admin_headers)
    ).json()
    assert any(row["id"] == str(job.id) for row in queue)

    rejected = await client.post(
        f"/api/v1/admin/jobs/{job.id}/enrichment/reject",
        headers=client_admin_headers,
    )
    assert rejected.status_code == 200
    assert rejected.json() == {"id": str(job.id), "applied": False}

    empty = (
        await client.get("/api/v1/admin/jobs/enrichment", headers=client_admin_headers)
    ).json()
    assert all(row["id"] != str(job.id) for row in empty)

    missing = await client.post(
        f"/api/v1/admin/jobs/{job.id}/enrichment/reject",
        headers=client_admin_headers,
    )
    assert missing.status_code == 404


async def test_sweep_runs_through_the_queue(
    client, auth_headers, client_admin_headers, seeded_catalog, db
):
    from app.services.job_worker import JobWorker, enqueue
    from app.models.enums import BackgroundJobType

    await enqueue(db, BackgroundJobType.CATALOG_ENRICH.value, {"limit": 5})
    worker = JobWorker(db)
    assert await worker.run_once() is True

    result = (
        await client.get("/api/v1/admin/jobs/enrichment", headers=client_admin_headers)
    ).json()
    assert result, "queue-run sweep produced moderation proposals"


def test_scheduler_provisions_the_enrichment_sweep():
    assert KIND_TASKS[ScheduleKind.SYSTEM_CATALOG_ENRICH.value] == "catalog_enrich"
