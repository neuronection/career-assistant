"""— interview prep: plan generation (calibration + taxonomy),
session lifecycle, plan-edit rules, ownership."""

import json
import uuid

from sqlalchemy import select

from tests.conftest import _make_posting, _uid

from app.ai.agents.posting_extractor import ExtractSkill, PostingExtract
from app.models.ai_model import AIGeneration
from app.models.enums import AITaskType
from app.models.job_model import Job, JobSkill
from app.models.taxonomy_model import Skill
from app.models.user_model import UserSkill


async def _seeded_skill(db) -> Skill:
    skill_row = (await db.execute(select(Skill).limit(1))).scalars().first()
    assert skill_row is not None
    return skill_row


async def _user_skill(db, headers, skill_row: Skill, level: int) -> None:
    db.add(UserSkill(user_id=_uid(headers), skill_id=skill_row.id, level=level))
    await db.commit()


async def _extracted_posting(db, source, skill_row: Skill, *, required=6):
    posting = await _make_posting(db, source, external_id="interview-1")
    posting.extract = PostingExtract(
        title_norm="Backend Engineer",
        skills=[
            ExtractSkill(
                skill_key=skill_row.key,
                required_level=required,
                priority="must_have",
                evidence_quote="must know the thing",
                confidence=0.9,
            ),
            ExtractSkill(
                skill_key="totally-made-up-key",
                required_level=3,
                priority="must_have",
                evidence_quote="mystery requirement",
                confidence=0.9,
            ),
        ],
        responsibilities=[
            {"text": "Ship the payments service", "time_pct": 40},
            {"text": "Mentor juniors", "time_pct": 10},
        ],
    ).model_dump(mode="json")
    db.add(posting)
    await db.commit()
    await db.refresh(posting)
    return posting


async def test_plan_calibrates_to_user_level_and_resolves_taxonomy(
    client, auth_headers, profile_ready, seeded_catalog, db, source
):
    skill_row = await _seeded_skill(db)
    await _user_skill(db, auth_headers, skill_row, level=3)
    posting = await _extracted_posting(db, source, skill_row)

    response = await client.post(
        "/api/v1/interview/sessions",
        json={"posting_ref": posting.ref, "kind": "mixed"},
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "planned"
    assert body["role_label"] == posting.title
    assert body["posting_ref"] == posting.ref

    technical = [i for i in body["plan"] if i["kind"] == "technical"]
    assert technical, "mock plan must carry technical questions"
    known = next(i for i in technical if i["skill_key"] == skill_row.key)
    assert known["target_level"] == 3
    assert known["skill_label"] == skill_row.label

    invented = [i for i in technical if i["skill_key"] is None]
    assert invented, "the made-up key must lose its key (label kept)"
    assert all(i["skill_label"] for i in invented)

    audits = (
        (
            await db.execute(
                select(AIGeneration).where(
                    AIGeneration.task_type == AITaskType.INTERVIEW_PLAN.value
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(audits) == 1
    assert audits[0].user_id == uuid.UUID(_uid(auth_headers))


async def test_archetype_session_works_without_postings(
    client, auth_headers, profile_ready, seeded_catalog, db
):
    skill_row = await _seeded_skill(db)
    linked = (await db.execute(select(JobSkill.job_id).limit(1))).scalar_one_or_none()
    assert linked is not None, "seeded catalog must carry job skills"
    job = await db.get(Job, linked)
    await _user_skill(db, auth_headers, skill_row, level=7)
    response = await client.post(
        "/api/v1/interview/sessions",
        json={"job_code": job.code, "kind": "technical"},
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["posting_ref"] is None
    assert body["role_label"] == job.title
    assert body["plan"], "archetype plan must have questions"
    assert {item["kind"] for item in body["plan"]} == {"technical"}


async def test_create_requires_a_role_source(client, auth_headers, profile_ready):
    response = await client.post(
        "/api/v1/interview/sessions",
        json={"kind": "mixed"},
        headers=auth_headers,
    )
    assert response.status_code == 400
    missing = await client.post(
        "/api/v1/interview/sessions",
        json={"job_code": "no-such-job", "kind": "mixed"},
        headers=auth_headers,
    )
    assert missing.status_code == 404


async def test_plan_patch_rules(
    client, auth_headers, profile_ready, seeded_catalog, db, source
):
    skill_row = await _seeded_skill(db)
    posting = await _extracted_posting(db, source, skill_row)
    created = (
        await client.post(
            "/api/v1/interview/sessions",
            json={"posting_ref": posting.ref, "kind": "mixed"},
            headers=auth_headers,
        )
    ).json()
    session_id = created["id"]
    plan = created["plan"]

    trimmed = await client.patch(
        f"/api/v1/interview/sessions/{session_id}/plan",
        json={"items": plan[:2]},
        headers=auth_headers,
    )
    assert trimmed.status_code == 200, trimmed.text
    assert len(trimmed.json()["plan"]) == 2

    duplicated = await client.patch(
        f"/api/v1/interview/sessions/{session_id}/plan",
        json={"items": [plan[0], {**plan[0], "question": "Again?"}]},
        headers=auth_headers,
    )
    assert duplicated.status_code == 400

    interview = await _get_session(db, session_id)
    interview.rubric_scores = [
        {"question_id": plan[0]["id"], "structure": 5, "evidence": 5, "clarity": 5}
    ]
    await db.commit()
    dropped_answered = await client.patch(
        f"/api/v1/interview/sessions/{session_id}/plan",
        json={"items": plan[1:2]},
        headers=auth_headers,
    )
    assert dropped_answered.status_code == 400


async def _get_session(db, session_id: str):
    from app.models.interview_model import InterviewSession

    return await db.get(InterviewSession, uuid.UUID(session_id))


async def _register(client, email: str) -> dict:
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "supersecret1",
            "full_name": "Other Student",
        },
    )
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def test_cross_user_access_is_not_found(
    client, auth_headers, profile_ready, seeded_catalog, db
):
    job = (await db.execute(select(Job).limit(1))).scalars().first()
    created = (
        await client.post(
            "/api/v1/interview/sessions",
            json={"job_code": job.code, "kind": "mixed"},
            headers=auth_headers,
        )
    ).json()
    other = await _register(client, "interview-other@example.com")
    response = await client.get(
        f"/api/v1/interview/sessions/{created['id']}",
        headers=other,
    )
    assert response.status_code == 404


async def test_history_lists_own_sessions(
    client, auth_headers, profile_ready, seeded_catalog, db
):
    job = (await db.execute(select(Job).limit(1))).scalars().first()
    await client.post(
        "/api/v1/interview/sessions",
        json={"job_code": job.code, "kind": "behavioral"},
        headers=auth_headers,
    )
    listing = await client.get("/api/v1/interview/sessions", headers=auth_headers)
    assert listing.status_code == 200
    body = listing.json()
    assert len(body) == 1
    assert body[0]["kind"] == "behavioral"


# ---------------------------------------------------------- practice (35.2)


def _parse_sse(text: str) -> list[tuple[str, dict]]:
    events = []
    for block in text.split("\n\n"):
        if not block.strip():
            continue
        name = ""
        data = ""
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line[len("event: ") :]
            elif line.startswith("data: "):
                data = line[len("data: ") :]
        events.append((name, json.loads(data)))
    return events


async def _make_session(client, headers, db, kind="technical") -> dict:
    skill_row = await _seeded_skill(db)
    job = (await db.execute(select(Job).limit(1))).scalars().first()
    db.add(UserSkill(user_id=_uid(headers), skill_id=skill_row.id, level=4))
    await db.commit()
    created = await client.post(
        "/api/v1/interview/sessions",
        json={"job_code": job.code, "kind": kind},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    return created.json()


async def test_start_binds_chat_and_seeds_opening_question(
    client, auth_headers, profile_ready, seeded_catalog, db
):
    session = await _make_session(client, auth_headers, db)
    started = await client.post(
        f"/api/v1/interview/sessions/{session['id']}/start",
        headers=auth_headers,
    )
    assert started.status_code == 200, started.text
    body = started.json()
    assert body["status"] == "active"
    assert body["chat_session_id"]

    messages = (
        await client.get(
            f"/api/v1/chat/sessions/{body['chat_session_id']}/messages",
            headers=auth_headers,
        )
    ).json()
    assert len(messages) == 1
    assert messages[0]["role"] == "assistant"
    assert "Question 1/" in messages[0]["content"]
    assert body["plan"][0]["question"] in messages[0]["content"]

    resumed = await client.post(
        f"/api/v1/interview/sessions/{session['id']}/start",
        headers=auth_headers,
    )
    assert resumed.status_code == 200
    assert resumed.json()["chat_session_id"] == body["chat_session_id"]


async def test_practice_turn_stream_persists_rubric(
    client, auth_headers, profile_ready, seeded_catalog, db
):
    session = await _make_session(client, auth_headers, db)
    started = (
        await client.post(
            f"/api/v1/interview/sessions/{session['id']}/start",
            headers=auth_headers,
        )
    ).json()
    chat_id = started["chat_session_id"]

    response = await client.post(
        f"/api/v1/chat/sessions/{chat_id}/messages",
        json={"content": "I would start from the data model."},
        params={"stream": "true"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    events = _parse_sse(response.text)
    names = [name for name, _ in events]
    assert names[0] == "flow_started"
    assert names[-1] == "done"
    assert "delta" in names
    assert "interview_state" in names
    state = dict(events)["interview_state"]
    assert state["answered"] == 1
    assert state["total"] == len(started["plan"])
    assert state["status"] == "active"

    detail = (
        await client.get(
            f"/api/v1/interview/sessions/{session['id']}",
            headers=auth_headers,
        )
    ).json()
    assert len(detail["rubric_scores"]) == 1
    assert detail["rubric_scores"][0]["question_id"] == started["plan"][0]["id"]


async def test_practice_walkthrough_completes(
    client, auth_headers, profile_ready, seeded_catalog, db
):
    session = await _make_session(client, auth_headers, db, kind="mixed")
    started = (
        await client.post(
            f"/api/v1/interview/sessions/{session['id']}/start",
            headers=auth_headers,
        )
    ).json()
    chat_id = started["chat_session_id"]
    total = len(started["plan"])

    for _ in range(total):
        reply = await client.post(
            f"/api/v1/chat/sessions/{chat_id}/messages",
            json={"content": "My answer, with a concrete example."},
            headers=auth_headers,
        )
        assert reply.status_code == 200, reply.text

    detail = (
        await client.get(
            f"/api/v1/interview/sessions/{session['id']}",
            headers=auth_headers,
        )
    ).json()
    assert detail["status"] == "completed"
    assert len(detail["rubric_scores"]) == total

    exhausted = await client.post(
        f"/api/v1/chat/sessions/{chat_id}/messages",
        json={"content": "One more?"},
        headers=auth_headers,
    )
    assert exhausted.status_code == 400


# ------------------------------------------------------------ debrief (35.3)


async def test_debrief_aggregate_resources_and_retry(
    client, auth_headers, profile_ready, seeded_catalog, db
):
    from app.models.growth_model import LearningResource

    session = await _make_session(client, auth_headers, db, kind="technical")
    plan_skill_key = next(
        item["skill_key"]
        for item in session["plan"]
        if item["kind"] == "technical" and item.get("skill_key")
    )
    plan_skill = (
        await db.execute(select(Skill).where(Skill.key == plan_skill_key))
    ).scalars().one()
    db.add(
        LearningResource(
            skill_id=plan_skill.id,
            kind="course",
            title="SQL for Interviewing",
            provider="Example Academy",
            url="https://example.com/sql",
        )
    )
    await db.commit()
    started = (
        await client.post(
            f"/api/v1/interview/sessions/{session['id']}/start",
            headers=auth_headers,
        )
    ).json()

    for question in started["plan"]:
        reply = await client.post(
            f"/api/v1/chat/sessions/{started['chat_session_id']}/messages",
            json={"content": "An answer with a concrete example."},
            headers=auth_headers,
        )
        assert reply.status_code == 200, reply.text

    early = await client.post(
        f"/api/v1/interview/sessions/{session['id']}/debrief",
        headers=auth_headers,
    )
    assert early.status_code == 200, early.text
    debrief = early.json()["debrief"]
    assert debrief is not None

    scores = (
        await client.get(
            f"/api/v1/interview/sessions/{session['id']}",
            headers=auth_headers,
        )
    ).json()["rubric_scores"]
    expected_structure = round(
        sum(float(r["structure"]) for r in scores) / len(scores), 2
    )
    assert debrief["aggregate"]["structure"] == expected_structure
    assert debrief["aggregate"]["answered"] == len(scores)

    weak_ids = set(debrief["weak_question_ids"])
    assert weak_ids, "the mock rubric keeps evidence below the bar"
    assert any(r["skill_key"] for r in debrief["per_question"] if r["weak"])
    assert any(r["title"] == "SQL for Interviewing" for r in debrief["resources"])

    audit = (
        (
            await db.execute(
                select(AIGeneration).where(
                    AIGeneration.task_type == AITaskType.INTERVIEW_DEBRIEF.value
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(audit) == 1

    again = await client.post(
        f"/api/v1/interview/sessions/{session['id']}/debrief",
        headers=auth_headers,
    )
    assert again.json()["debrief"] == debrief
    audit = (
        (
            await db.execute(
                select(AIGeneration).where(
                    AIGeneration.task_type == AITaskType.INTERVIEW_DEBRIEF.value
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(audit) == 1, "debrief generation is idempotent"

    retry = await client.post(
        f"/api/v1/interview/sessions/{session['id']}/retry",
        headers=auth_headers,
    )
    assert retry.status_code == 200, retry.text
    retry_body = retry.json()
    assert retry_body["status"] == "planned"
    assert retry_body["debrief"] is None
    assert retry_body["role_label"] == session["role_label"]
    retry_ids = {item["id"] for item in retry_body["plan"]}
    assert retry_ids == weak_ids

    source = (
        await client.get(
            f"/api/v1/interview/sessions/{session['id']}",
            headers=auth_headers,
        )
    ).json()
    assert source["status"] == "completed"


async def test_debrief_requires_completion(
    client, auth_headers, profile_ready, seeded_catalog, db
):
    session = await _make_session(client, auth_headers, db)
    response = await client.post(
        f"/api/v1/interview/sessions/{session['id']}/debrief",
        headers=auth_headers,
    )
    assert response.status_code == 400
    retry = await client.post(
        f"/api/v1/interview/sessions/{session['id']}/retry",
        headers=auth_headers,
    )
    assert retry.status_code == 400
