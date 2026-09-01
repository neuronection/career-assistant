"""Phase 22 API surface: weight sliders, deterministic refit, staleness."""

from sqlalchemy import select

from app.models.matching_model import MatchInsight
from app.models.user_model import User
from app.services.job_worker import JobWorker


async def _student_id(db):
    return (
        (await db.execute(select(User).where(User.email == "student@example.com")))
        .scalars()
        .first()
    ).id


async def test_put_scoring_weights_refits_without_ai(
    client, auth_headers, profile_ready, seeded_catalog
):
    # seed one AI insight; weight changes must NOT add or change AI scores
    job = (
        await client.get("/api/v1/jobs/software-developer", headers=auth_headers)
    ).json()
    await client.post(
        "/api/v1/match/score", json={"job_id": job["id"]}, headers=auth_headers
    )
    before = (await client.get("/api/v1/match/insights", headers=auth_headers)).json()
    ai_before = {i["job_id"]: i["ai_score"] for i in before if i["ai_score"]}

    response = await client.put(
        "/api/v1/me/preferences/scoring",
        json={
            "skills": 5,
            "location": 1,
            "experience": 1,
            "education": 2,
            "interests": 4,
        },
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["scoring_weights"]["skills"] == 5
    assert body["refitted"] >= 45

    after = (await client.get("/api/v1/match/insights", headers=auth_headers)).json()
    assert {i["job_id"]: i["ai_score"] for i in after if i["ai_score"]} == ai_before
    # every job carries a current fit
    assert all(i["fit_score"] is not None for i in after)
    from app.services.fit.dimensions import FIT_VERSION

    assert all(i["fit_version"] == FIT_VERSION for i in after)

    invalid = await client.put(
        "/api/v1/me/preferences/scoring",
        json={"skills": 9},
        headers=auth_headers,
    )
    assert invalid.status_code == 400


async def test_refit_single_job_sync_and_all_queued(
    client, db, auth_headers, profile_ready, seeded_catalog
):
    job = (await client.get("/api/v1/jobs/nurse", headers=auth_headers)).json()
    single = await client.post(
        "/api/v1/match/fit", json={"job_id": job["id"]}, headers=auth_headers
    )
    assert single.status_code == 200, single.text
    body = single.json()
    assert 0 <= body["fit_score"] <= 10
    assert body["breakdown"]["dimensions"]

    queued = await client.post(
        "/api/v1/match/fit", json={"all": True}, headers=auth_headers
    )
    assert queued.status_code == 200
    worker = JobWorker(db)
    while await worker.run_once():
        pass
    rows = (
        (
            await db.execute(
                select(MatchInsight).where(
                    MatchInsight.user_id == await _student_id(db)
                )
            )
        )
        .scalars()
        .all()
    )
    assert rows
    assert all(r.fit_score is not None for r in rows)


async def test_job_detail_and_candidates_carry_breakdown(
    client, auth_headers, profile_ready, seeded_catalog
):
    detail = await client.get(
        "/api/v1/jobs/software-developer/match", headers=auth_headers
    )
    insight = detail.json()["insight"]
    assert insight is None or insight["fit_breakdown"] is None  # pre-score

    candidates = (
        await client.get("/api/v1/match/candidates?limit=3", headers=auth_headers)
    ).json()
    assert candidates
    assert candidates[0]["fit_score"] is not None
