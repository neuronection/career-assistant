"""residuals — revealed preferences (opt-in, capped), outcome
funnel metrics (observation only), registry-driven engine dimension
lists, and the RIASEC/values bank templates for 37's library."""

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select

from tests.conftest import _make_posting, _uid

from app.models.enums import TemplateSource, TemplateStatus
from app.models.job_model import Job, JobTag
from app.models.assessment_template_model import AssessmentTemplate
from app.models.metric_model import UserMetricProfile
from app.models.posting_model import JobPosting, PostingInteraction
from app.models.taxonomy_model import InterestTag
from app.models.user_model import Profile
from app.seeds.metrics import riasec_of_category, seed_metric_templates
from app.services.metric_service import MetricService, revealed_prefs


async def _catalog_job_with_tag(db) -> tuple[Job, InterestTag]:
    job = (await db.execute(select(Job).limit(1))).scalars().first()
    assert job is not None
    tags = (await db.execute(select(InterestTag).limit(20))).scalars().all()
    tag = next((t for t in tags if riasec_of_category(t.category) is not None), None)
    assert tag is not None, "seeded taxonomy must carry RIASEC-mapped categories"
    return job, tag


async def _engaged_posting(db, headers, source) -> JobPosting:
    job, tag = await _catalog_job_with_tag(db)
    posting = await _make_posting(db, source, external_id="reveal-1")
    posting.catalog_job_id = job.id
    db.add(posting)
    existing = (
        (
            await db.execute(
                select(JobTag).where(
                    JobTag.job_id == job.id, JobTag.interest_tag_id == tag.id
                )
            )
        )
        .scalars()
        .first()
    )
    if existing is None:
        db.add(JobTag(job_id=job.id, interest_tag_id=tag.id))
    now = datetime.now(timezone.utc)
    db.add(
        PostingInteraction(
            user_id=UUID(_uid(headers)),
            posting_id=posting.id,
            seen_at=now,
            saved_at=now,
            applied_at=now,
        )
    )
    await db.commit()
    await db.refresh(posting)
    return posting


async def _interest_rows(db, user_id: str) -> dict[str, UserMetricProfile]:
    rows = (
        (
            await db.execute(
                select(UserMetricProfile).where(
                    UserMetricProfile.user_id == UUID(user_id),
                    UserMetricProfile.dimension_key.like("interest.%"),
                )
            )
        )
        .scalars()
        .all()
    )
    return {row.dimension_key: row for row in rows}


async def test_revealed_preferences_off_by_default(
    client, auth_headers, profile_ready, seeded_catalog, db, source
):
    service = MetricService(db)
    user_id = UUID(_uid(auth_headers))
    await _engaged_posting(db, auth_headers, source)
    before = await _interest_rows(db, _uid(auth_headers))
    result = await service.apply_revealed_preferences(user_id)
    assert result == {"applied": False, "reason": "disabled"}
    after = await _interest_rows(db, _uid(auth_headers))
    assert {k: r.value for k, r in before.items()} == {
        k: r.value for k, r in after.items()
    }


async def test_revealed_preferences_drift_capped(
    client, auth_headers, profile_ready, seeded_catalog, db, source
):
    service = MetricService(db)
    user_id = UUID(_uid(auth_headers))
    profile = (
        (await db.execute(select(Profile).where(Profile.user_id == user_id)))
        .scalars()
        .first()
    )
    profile.preferences = {
        **(profile.preferences or {}),
        "revealed_preferences": {"enabled": True},
    }
    await db.commit()

    await _engaged_posting(db, auth_headers, source)
    from sqlalchemy import delete

    await db.execute(
        delete(UserMetricProfile).where(
            UserMetricProfile.user_id == user_id,
            UserMetricProfile.dimension_key.like("interest.%"),
        )
    )
    await db.commit()
    first = await service.apply_revealed_preferences(user_id)
    assert first["applied"] is True
    assert first["samples"] >= 1
    assert first["moved"], "a fresh profile must move toward the signal"
    after_first = await _interest_rows(db, _uid(auth_headers))
    start = {key: row.value for key, row in after_first.items()}
    assert all(5.0 <= value <= 6.0 for value in start.values()), (
        "first drift must stay within the ±0.5 (5%/week) cap from 5.5"
    )

    second = await service.apply_revealed_preferences(user_id)
    assert second["applied"] is True
    after_second = await _interest_rows(db, _uid(auth_headers))
    for key, row in after_second.items():
        assert abs(row.value - start[key]) <= 0.5 + 1e-9
        assert row.source == "behavior"
        assert row.evidence["basis"] == "revealed_preferences"


async def test_outcome_funnel_counts_and_rates(
    client, auth_headers, profile_ready, seeded_catalog, db, source
):
    job, _tag = await _catalog_job_with_tag(db)
    postings = []
    for index in range(4):
        posting = await _make_posting(db, source, external_id=f"funnel-{index}")
        posting.catalog_job_id = job.id
        db.add(posting)
        postings.append(posting)
    now = datetime.now(timezone.utc)
    user_id = UUID(_uid(auth_headers))
    db.add_all(
        [
            PostingInteraction(
                user_id=user_id,
                posting_id=postings[0].id,
                seen_at=now,
                saved_at=now,
                applied_at=now,
                stage="interview",
            ),
            PostingInteraction(
                user_id=user_id,
                posting_id=postings[1].id,
                seen_at=now,
                applied_at=now,
                stage="offer",
            ),
            PostingInteraction(
                user_id=user_id, posting_id=postings[2].id, seen_at=now, saved_at=now
            ),
            PostingInteraction(
                user_id=user_id, posting_id=postings[3].id, seen_at=now, applied_at=now
            ),
        ]
    )
    await db.commit()

    funnel = await MetricService(db).outcome_funnel(user_id)
    assert len(funnel) == 1
    entry = funnel[0]
    assert entry["saved"] == 2
    assert entry["applied"] == 3
    assert entry["interview"] == 1
    assert entry["offer"] == 1
    assert entry["interview_rate"] == round(1 / 3, 2)
    assert entry["offer_rate"] == round(1 / 3, 2)

    surface = await client.get("/api/v1/metrics/me/outcomes", headers=auth_headers)
    assert surface.status_code == 200
    assert surface.json()[0]["family"] == entry["family"]


async def test_engine_dimensions_endpoint(
    client, auth_headers, profile_ready, seeded_catalog, db
):
    response = await client.get(
        "/api/v1/metrics/engine-dimensions", headers=auth_headers
    )
    assert response.status_code == 200, response.text
    body = response.json()
    fit = [d for d in body if d["engine"] == "fit"]
    posting = [d for d in body if d["engine"] == "posting_fit"]
    assert {d["key"] for d in fit} == {
        "skills",
        "location",
        "experience",
        "education",
        "interests",
        "values",
    }
    assert all("default_weight" in d for d in fit)
    assert {d["key"] for d in posting} == {
        "skills",
        "prereqs",
        "location_remote",
        "seniority_stage",
        "freshness",
    }


async def test_metric_bank_templates_seed_idempotent(
    client, auth_headers, profile_ready, seeded_catalog, db
):
    added = await seed_metric_templates(db)
    assert added == 2
    again = await seed_metric_templates(db)
    assert again == 0

    rows = (
        (
            await db.execute(
                select(AssessmentTemplate).where(
                    AssessmentTemplate.author_key == "bank",
                    AssessmentTemplate.source == TemplateSource.BANK.value,
                )
            )
        )
        .scalars()
        .all()
    )
    keys = {row.key for row in rows}
    assert keys == {"riasec-interest-battery", "work-values-battery"}
    assert all(row.status == TemplateStatus.PUBLISHED.value for row in rows)
    dimension_keys = {
        q["dimension_key"]
        for row in rows
        for phase in row.content["phases"]
        for q in phase["questions"]
    }
    assert any(k.startswith("interest.") for k in dimension_keys)
    assert any(k.startswith("values.") for k in dimension_keys)


def test_revealed_prefs_shape():
    assert revealed_prefs(None) == {"enabled": False, "window_days": 28}
    assert revealed_prefs({"revealed_preferences": {"enabled": True}})["enabled"]
