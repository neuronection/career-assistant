"""Plan 200 — `FitService.refit_jobs`: the batch seam equals per-job refits."""

from sqlalchemy import select

from app.models.job_model import Job
from app.models.matching_model import MatchInsight
from app.models.user_model import Profile
from app.services.catalog.job_service import JOB_LOAD_OPTIONS
from app.services.postings.fit.service import FitService


async def _snapshot(db, job_ids):
    rows = (
        (await db.execute(select(MatchInsight).where(MatchInsight.job_id.in_(job_ids))))
        .scalars()
        .all()
    )
    return {
        (row.user_id, row.job_id): float(row.fit_score) for row in rows if row.fit_score is not None
    }


async def test_refit_jobs_covers_every_user_and_matches_single_refits(
    db, client, auth_headers, profile_ready, seeded_catalog
):
    jobs = (
        (
            await db.execute(
                select(Job).where(Job.status == "published").options(*JOB_LOAD_OPTIONS).limit(2)
            )
        )
        .scalars()
        .all()
    )
    assert len(jobs) == 2
    users = (await db.execute(select(Profile.user_id))).scalars().all()
    assert users

    service = FitService(db)
    count = await service.refit_jobs([job.id for job in jobs])
    assert count == len(jobs) * len(users)

    batched = await _snapshot(db, [job.id for job in jobs])
    assert len(batched) == count

    await service.refit_job(jobs[0].id)
    after_single = await _snapshot(db, [job.id for job in jobs])
    assert after_single == batched, "a batch pass and a per-job pass must agree"
