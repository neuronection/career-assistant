from app.services.job_worker import JobWorker


async def test_candidates_rank_by_fit(
    client, auth_headers, profile_ready, seeded_catalog
):
    response = await client.get(
        "/api/v1/match/candidates?limit=5", headers=auth_headers
    )
    assert response.status_code == 200
    candidates = response.json()
    assert candidates
    scores = [c["fit_score"] for c in candidates]
    assert scores == sorted(scores, reverse=True)
    top = candidates[0]
    assert top["fit_score"] > 0
    assert top["breakdown"]["dimensions"]["skills"]["score"] is not None


async def test_candidates_respect_gates(
    client, auth_headers, profile_ready, seeded_catalog
):
    await client.put(
        "/api/v1/profile",
        json={
            "constraints": {
                "physical_conditions": ["mobility_limited"],
                "willing_to_relocate": False,
            }
        },
        headers=auth_headers,
    )
    response = await client.get(
        "/api/v1/match/candidates?limit=50", headers=auth_headers
    )
    codes = [c["job"]["code"] for c in response.json()]
    assert "firefighter" not in codes


async def test_score_specific_job_persists_insight(
    client, auth_headers, profile_ready, seeded_catalog
):
    job = (
        await client.get("/api/v1/jobs/software-developer", headers=auth_headers)
    ).json()
    response = await client.post(
        "/api/v1/match/score", json={"job_id": job["id"]}, headers=auth_headers
    )
    assert response.status_code == 200, response.text
    insights = response.json()
    assert len(insights) == 1
    insight = insights[0]
    assert insight["ai_score"] is not None
    assert 0 <= insight["ai_score"] <= 10
    assert insight["ai_positives"]
    assert insight["prerequisites"]


async def test_score_batch_and_idempotent(
    client, db, auth_headers, profile_ready, seeded_catalog
):
    first = await client.post(
        "/api/v1/match/score", json={"limit": 3}, headers=auth_headers
    )
    assert first.status_code == 202
    job_id = first.json()["job_id"]
    worker = JobWorker(db)
    while await worker.run_once():
        pass
    insights = (await client.get("/api/v1/match/insights", headers=auth_headers)).json()
    scored = [i for i in insights if i["ai_score"] is not None]
    assert len(scored) == 3

    detail = await client.get(f"/api/v1/background-jobs/{job_id}", headers=auth_headers)
    assert detail.json()["status"] == "succeeded"

    # A second batch scores nothing new (mock scores are deterministic, so the
    # insight set is idempotent).
    again = await client.post(
        "/api/v1/match/score", json={"limit": 3}, headers=auth_headers
    )
    assert again.status_code == 202
    while await worker.run_once():
        pass
    after = (await client.get("/api/v1/match/insights", headers=auth_headers)).json()
    assert {i["job_id"]: i["ai_score"] for i in after if i["ai_score"] is not None} == {
        i["job_id"]: i["ai_score"] for i in scored
    }

    forced = await client.post(
        "/api/v1/match/score", json={"limit": 3, "force": True}, headers=auth_headers
    )
    assert forced.status_code == 202
    while await worker.run_once():
        pass
    forced_insights = (
        await client.get("/api/v1/match/insights", headers=auth_headers)
    ).json()
    # force re-scores the same top-3 by fit — the set stays identical
    assert len([i for i in forced_insights if i["ai_score"] is not None]) == 3


async def test_rate_and_my_insights(
    client, auth_headers, profile_ready, seeded_catalog
):
    job = (await client.get("/api/v1/jobs/nurse", headers=auth_headers)).json()
    rated = await client.put(
        "/api/v1/match/rate",
        json={
            "job_id": job["id"],
            "user_score": 7,
            "status": "interested",
            "notes": "sounds meaningful",
        },
        headers=auth_headers,
    )
    assert rated.status_code == 200
    body = rated.json()
    assert body["user_score"] == 7
    assert body["status"] == "interested"

    insights = (await client.get("/api/v1/match/insights", headers=auth_headers)).json()
    assert len(insights) == 1
    assert insights[0]["user_notes"] == "sounds meaningful"

    bad = await client.put(
        "/api/v1/match/rate",
        json={"job_id": job["id"], "user_score": 42},
        headers=auth_headers,
    )
    assert bad.status_code == 422


async def test_rankings_fit_default_and_filtered(
    client, auth_headers, profile_ready, seeded_catalog
):
    job = (
        await client.get("/api/v1/jobs/software-developer", headers=auth_headers)
    ).json()
    await client.post(
        "/api/v1/match/score", json={"job_id": job["id"]}, headers=auth_headers
    )
    await client.put(
        "/api/v1/match/rate",
        json={"job_id": job["id"], "user_score": 9},
        headers=auth_headers,
    )

    response = await client.get("/api/v1/rankings", headers=auth_headers)
    assert response.status_code == 200
    rankings = response.json()
    assert rankings["total"] >= 40
    top = rankings["items"][0]
    assert top["score"] >= 6.0
    assert top["fit_score"] is not None
    assert top["breakdown"]["dimensions"]["skills"]["score"] is not None
    scored = next(
        i for i in rankings["items"] if i["job"]["code"] == "software-developer"
    )
    assert scored["ai_score"] is not None and scored["user_score"] == 9
    # fit + ai agree within the blend: score sits between the two signals
    assert scored["fit_score"] <= scored["score"] <= scored["ai_score"] or (
        scored["ai_score"] <= scored["score"] <= scored["fit_score"]
    )

    filtered = await client.get(
        "/api/v1/rankings?family_key=healthcare", headers=auth_headers
    )
    codes = {i["job"]["code"] for i in filtered.json()["items"]}
    assert "nurse" in codes
    assert "software-developer" not in codes

    by_interest = await client.get(
        "/api/v1/rankings?interests=people-health", headers=auth_headers
    )
    interest_codes = {i["job"]["code"] for i in by_interest.json()["items"]}
    assert "nurse" in interest_codes
    assert "software-developer" not in interest_codes

    min_score = await client.get(
        "/api/v1/rankings?ai_score_min=1", headers=auth_headers
    )
    assert len(min_score.json()["items"]) == 1

    sorted_by_user = await client.get(
        "/api/v1/rankings?sort=user_score", headers=auth_headers
    )
    assert sorted_by_user.json()["items"][0]["job"]["code"] == "software-developer"

    plain_demand = await client.get(
        "/api/v1/rankings?sort=demand&page_size=5", headers=auth_headers
    )
    demand_items = plain_demand.json()["items"]
    outlooks = [i["job"]["attributes"]["demand"]["outlook"] for i in demand_items]
    assert outlooks == sorted(outlooks, reverse=True)  # plain opt-in sort


async def test_rankings_gated_jobs_reach_stretch_tab(
    client, auth_headers, profile_ready, seeded_catalog
):
    """doctorate jobs exceed the profile's max_education_years=6 gate."""
    feed = await client.get("/api/v1/rankings?sort=title", headers=auth_headers)
    feed_codes = {i["job"]["code"] for i in feed.json()["items"]}
    stretch = await client.get("/api/v1/rankings?stretch=true", headers=auth_headers)
    stretch_items = stretch.json()["items"]
    assert stretch_items
    gated_codes = {i["job"]["code"] for i in stretch_items}
    assert not (gated_codes & feed_codes)  # gated never mix into the feed
    physician = next(i for i in stretch_items if i["job"]["code"] == "physician")
    assert "education_years" in physician["gate_reasons"]
    assert physician["gated"] is True


async def test_rankings_isolated_per_user(
    client, auth_headers, profile_ready, seeded_catalog
):
    job = (
        await client.get("/api/v1/jobs/software-developer", headers=auth_headers)
    ).json()
    await client.post(
        "/api/v1/match/score", json={"job_id": job["id"]}, headers=auth_headers
    )
    other = await client.post(
        "/api/v1/auth/register",
        json={"email": "rankother@example.com", "password": "password123"},
    )
    other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}
    response = await client.get(
        "/api/v1/rankings?ai_score_min=0", headers=other_headers
    )
    assert response.json()["items"] == []


async def test_job_match_detail(client, auth_headers, profile_ready, seeded_catalog):
    await client.post(
        "/api/v1/match/score", json={"job_id": None, "limit": 2}, headers=auth_headers
    )
    detail = await client.get(
        "/api/v1/jobs/software-developer/match", headers=auth_headers
    )
    body = detail.json()
    assert body["job"]["code"] == "software-developer"
    assert body["university_pathways"] == []
