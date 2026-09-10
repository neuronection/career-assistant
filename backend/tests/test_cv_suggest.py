"""— CV AI actions: grounded, draft-then-approve, audited."""

import uuid

from sqlalchemy import select

from tests.conftest import _make_posting, _uid

from app.ai.agents.posting_extractor import ExtractSkill, PostingExtract
from app.models.taxonomy_model import Skill
from app.models.user_model import UserSkill


async def _experience(client, headers, **overrides) -> dict:
    body = {
        "title": "DevOps intern",
        "kind": "internship",
        "org_name": "Acme Cloud",
        "start": "2025-01-01",
        "end": "2025-12-31",
        "hours_per_week": 40,
        "description": "Deployed things.",
        "skills": [],
        "achievements": [{"text": "Cut deploy time 40%"}],
        **overrides,
    }
    created = await client.post("/api/v1/me/experience", json=body, headers=headers)
    assert created.status_code == 201, created.text
    return created.json()


async def _education(client, headers, **overrides) -> dict:
    body = {
        "institution": "Sample University",
        "program": "BSc Computer Science",
        "level": "bachelor",
        "start": "2022-09-01",
        "in_progress": True,
        **overrides,
    }
    created = await client.post("/api/v1/me/education", json=body, headers=headers)
    assert created.status_code == 201, created.text
    return created.json()


async def _make_cv(client, headers, **overrides) -> dict:
    created = await client.post(
        "/api/v1/cv",
        json={"title": "Backend Intern CV", **overrides},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    return created.json()


async def _context_refs(client, headers, cv_id) -> set[tuple[str, str]]:
    context = (await client.get(f"/api/v1/cv/{cv_id}/context", headers=headers)).json()
    return {
        (key, item_id)
        for key, ids in context["snapshot_index"].items()
        for item_id in ids
    }


async def test_summary_grounds_and_verifies(
    client, auth_headers, profile_ready, seeded_catalog
):
    await _experience(client, auth_headers)
    cv = await _make_cv(client, auth_headers)
    response = await client.post(
        f"/api/v1/cv/{cv['id']}/ai/summary", json={}, headers=auth_headers
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["action"] == "summary" and body["proposals"]
    known = await _context_refs(client, auth_headers, cv["id"])
    for entry in body["proposals"]:
        refs = {
            (ref["source_key"], ref["item_id"])
            for ref in entry["proposal"]["evidence_refs"]
        }
        assert refs, "proposals must cite evidence"
        assert refs <= known, "citations must resolve to CV context items"
        assert entry["verified"] is True


async def test_bullet_requires_target_ref(
    client, auth_headers, profile_ready, seeded_catalog
):
    await _experience(client, auth_headers)
    cv = await _make_cv(client, auth_headers)
    response = await client.post(
        f"/api/v1/cv/{cv['id']}/ai/bullet", json={}, headers=auth_headers
    )
    assert response.status_code == 400
    assert "ref" in response.json()["detail"]


async def test_bullet_proposes_metric_rewrite(
    client, auth_headers, profile_ready, seeded_catalog
):
    item = await _experience(client, auth_headers)
    cv = await _make_cv(client, auth_headers)
    response = await client.post(
        f"/api/v1/cv/{cv['id']}/ai/bullet",
        json={
            "ref": {
                "source_key": "experience",
                "item_id": item["id"],
                "text": "Deployed things.",
            }
        },
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["proposals"]
    first = body["proposals"][0]
    assert first["verified"] is True
    assert first["proposal"]["ref"]["item_id"] == item["id"]
    assert "<your number>" in first["proposal"]["text"], (
        "missing metrics stay explicit placeholders, never invented values"
    )


async def test_compaction_auto_targets_long_text(
    client, auth_headers, profile_ready, seeded_catalog
):
    long_text = "Deployed the service across regions with care. " * 8
    await _experience(client, auth_headers, description=long_text)
    cv = await _make_cv(client, auth_headers)
    response = await client.post(
        f"/api/v1/cv/{cv['id']}/ai/compaction", json={}, headers=auth_headers
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["proposals"], "long descriptions must be picked up automatically"
    assert all(entry["verified"] for entry in body["proposals"])


async def test_gaps_is_deterministic(
    client, auth_headers, profile_ready, seeded_catalog
):
    await _experience(client, auth_headers)
    await _education(client, auth_headers)
    cv = await _make_cv(client, auth_headers)
    await client.patch(
        f"/api/v1/cv/{cv['id']}",
        json={
            "working_content": {
                "blocks": [{"kind": "header"}, {"kind": "summary"}],
                "overrides": {},
            }
        },
        headers=auth_headers,
    )
    response = await client.post(
        f"/api/v1/cv/{cv['id']}/ai/gaps", json={}, headers=auth_headers
    )
    assert response.status_code == 200, response.text
    gaps = response.json()["gaps"]
    assert {"experience", "education"} <= {gap["source_key"] for gap in gaps}


async def test_tailor_coverage_and_flagged_proposals(
    client, auth_headers, profile_ready, seeded_catalog, db, source
):
    skill_row = (await db.execute(select(Skill).limit(1))).scalars().first()
    assert skill_row is not None
    user_id = _uid(auth_headers)
    db.add(UserSkill(user_id=user_id, skill_id=skill_row.id, level=6))
    await db.commit()
    await _experience(client, auth_headers)
    cv = await _make_cv(client, auth_headers)

    posting = await _make_posting(db, source, external_id="tailor-1")
    posting.extract = PostingExtract(
        title_norm="Junior DevOps Engineer",
        skills=[
            ExtractSkill(
                skill_key=skill_row.key,
                required_level=4,
                priority="must_have",
                evidence_quote="must know the thing",
                confidence=0.9,
            ),
            ExtractSkill(
                skill_key="kubernetes",
                required_level=3,
                priority="must_have",
                evidence_quote="kubernetes required",
                confidence=0.9,
            ),
        ],
    ).model_dump(mode="json")
    db.add(posting)
    await db.commit()

    no_target = await client.post(
        f"/api/v1/cv/{cv['id']}/ai/tailor", json={}, headers=auth_headers
    )
    assert no_target.status_code == 400

    response = await client.post(
        f"/api/v1/cv/{cv['id']}/ai/tailor",
        json={"posting_id": str(posting.id)},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["action"] == "tailor"
    coverage = body["coverage"]
    covered_keys = {entry["skill_key"] for entry in coverage["covered"]}
    missing_keys = {entry["skill_key"] for entry in coverage["missing"]}
    assert skill_row.key in covered_keys, "user has this skill at level 6"
    assert "kubernetes" in missing_keys, "user has no such skill"
    covered_entry = next(
        entry for entry in coverage["covered"] if entry["skill_key"] == skill_row.key
    )
    assert covered_entry["user_level"] == 6
    assert body["proposals"]


async def test_isolated_cv_cannot_run_actions(
    client, auth_headers, profile_ready, seeded_catalog
):
    cv = await _make_cv(client, auth_headers)
    other = await client.post(
        "/api/v1/auth/register",
        json={
            "email": f"{uuid.uuid4().hex[:10]}@example.com",
            "password": "Str0ngPass!23",
            "full_name": "Other",
        },
    )
    headers = {"Authorization": f"Bearer {other.json()['access_token']}"}
    response = await client.post(
        f"/api/v1/cv/{cv['id']}/ai/summary", json={}, headers=headers
    )
    assert response.status_code == 404


def test_compose_system_includes_tone_and_length():
    from app.ai.agents.cv_suggester import compose_system

    styled = compose_system("summary", tone="confident", length="short")
    assert "confident" in styled and "brevity" in styled
    plain = compose_system("summary")
    assert "brevity" not in plain


async def test_translate_action_targets_cv_language(
    client, auth_headers, profile_ready, seeded_catalog
):
    await _experience(client, auth_headers)
    cv = await _make_cv(client, auth_headers, language="de")
    response = await client.post(
        f"/api/v1/cv/{cv['id']}/ai/translate", json={}, headers=auth_headers
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["action"] == "translate"
    assert body["target_language"] == "de"
    assert body["proposals"], "mock translate proposes per evidence item"
    for entry in body["proposals"]:
        refs = {
            (ref["source_key"], ref["item_id"])
            for ref in entry["proposal"]["evidence_refs"]
        }
        assert refs <= await _context_refs(client, auth_headers, cv["id"])
        assert entry["verified"] is True
        assert "[DE]" in entry["proposal"]["text"]
