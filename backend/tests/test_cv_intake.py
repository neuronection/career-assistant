"""— CV intake: parse → review draft → apply (review-first).

Covers the full flow on marker-formatted text (the mock parser's contract):
auto-parse after extraction, draft read, partial apply with provenance,
unknown-skill proposal, skill evidence with the cv_document FK, conflicts,
re-intake dedupe, discard, and ownership.
"""

from sqlalchemy import select

from app.models.experience_model import ExperienceItem, SkillEvidence
from app.models.user_model import UserSkill


CV_TEXT = (
    "NAME: Jane Doe\n"
    "HEADLINE: Aspiring data engineer\n"
    "EMAIL: jane@example.com\n"
    "PHONE: +30 555 0100\n"
    "LOCATION: Athens\n"
    "LINK: github=https://github.com/janedoe\n"
    "SUMMARY: Student with a passion for pipelines.\n"
    "EDUCATION: BSc Computer Science at University of Sample (2022-09 - 2026-06)\n"
    "EXPERIENCE: Software Intern at Sample Corp (2024-06 - 2024-09); Built QA tooling\n"
    "SKILL: Python: 7\n"
    "SKILL: Zzz Craft\n"
    "LANGUAGE: en advanced\n"
    "CERTIFICATION: Cambridge B2 — Cambridge Assessment\n"
    "AWARD: award | Hackathon winner — SampleCon (2025-03)\n"
    "INTEREST: technology-software\n"
)


async def _drain(db):
    from app.services.job_worker import JobWorker

    worker = JobWorker(db)
    while await worker.run_once():
        pass


async def _upload_and_parse(client, db, headers, text=CV_TEXT) -> str:
    upload = await client.post(
        "/api/v1/documents?kind=cv",
        files={
            "file": ("cv.txt", __import__("io").BytesIO(text.encode()), "text/plain")
        },
        headers=headers,
    )
    assert upload.status_code == 202, upload.text
    doc_id = upload.json()["document"]["id"]
    await _drain(db)  # extraction → auto-enqueues parse
    await _drain(db)  # parse
    return doc_id


async def test_auto_parse_creates_review_draft(client, db, auth_headers):
    doc_id = await _upload_and_parse(client, db, auth_headers)
    drafts = await client.get(
        f"/api/v1/cv/intake/{doc_id}/drafts", headers=auth_headers
    )
    assert drafts.status_code == 200, drafts.text
    body = drafts.json()
    assert body["status"] == "pending"
    payload = body["payload"]
    assert payload["basics"]["full_name"] == "Jane Doe"
    assert payload["experience"][0]["title"] == "Software Intern"
    assert payload["experience"][0]["org"] == "Sample Corp"
    assert payload["skills"][0]["level_claim"] == 7
    assert payload["skills"][0]["evidence"]["quote"], "evidence quote required"


async def test_apply_writes_provenance_and_evidence(client, db, auth_headers):
    doc_id = await _upload_and_parse(client, db, auth_headers)
    applied = await client.post(
        f"/api/v1/cv/intake/{doc_id}/apply",
        json={"selections": {"experience": True, "skills": True}},
        headers=auth_headers,
    )
    assert applied.status_code == 200, applied.text
    report = applied.json()["report"]
    assert report["created"]["experience_items"] == 1
    assert "zzz-craft" in report["proposed_skills"]

    rows = await db.execute(select(ExperienceItem))
    item = rows.scalars().one()
    assert item.status == "draft"
    assert item.source == "cv_parse"
    assert item.org_name == "Sample Corp"
    assert item.org_id is not None, "org proposed via 39 lifecycle"

    skills = (await db.execute(select(UserSkill))).scalars().all()
    assert {s.source for s in skills} == {"document"}
    evidence = (await db.execute(select(SkillEvidence))).scalars().all()
    assert evidence, "evidence ledger must receive cv_document rows"
    assert all(e.cv_document_id is not None for e in evidence)


async def test_empty_selection_writes_nothing(client, db, auth_headers):
    doc_id = await _upload_and_parse(client, db, auth_headers)
    applied = await client.post(
        f"/api/v1/cv/intake/{doc_id}/apply",
        json={"selections": {}},
        headers=auth_headers,
    )
    assert applied.status_code == 200
    assert applied.json()["report"]["created"] == {}
    assert (await db.execute(select(ExperienceItem))).scalars().all() == []


async def test_apply_twice_dedupes(client, db, auth_headers):
    doc_id = await _upload_and_parse(client, db, auth_headers)
    payload = {"selections": {"experience": True}}
    first = await client.post(
        f"/api/v1/cv/intake/{doc_id}/apply", json=payload, headers=auth_headers
    )
    assert first.json()["report"]["created"]["experience_items"] == 1
    second = await client.post(
        f"/api/v1/cv/intake/{doc_id}/apply", json=payload, headers=auth_headers
    )
    report = second.json()["report"]
    assert report["created"].get("experience_items", 0) == 0
    assert report["duplicates"], "re-intake must dedupe, not duplicate"


async def test_basics_languages_interests_apply(client, db, auth_headers):
    from app.seeds.run import seed_taxonomy

    await seed_taxonomy(db)
    doc_id = await _upload_and_parse(client, db, auth_headers)
    applied = await client.post(
        f"/api/v1/cv/intake/{doc_id}/apply",
        json={
            "selections": {
                "basics": True,
                "languages": True,
                "interests": True,
                "education": True,
                "certifications": True,
                "awards": True,
            }
        },
        headers=auth_headers,
    )
    assert applied.status_code == 200, applied.text
    report = applied.json()["report"]
    assert report["created"]["education_items"] == 1
    assert report["created"]["certifications"] == 1
    assert report["created"]["profile_achievements"] == 1
    assert not report["unmapped_interests"], "technology-software is a seeded tag"

    from app.models.taxonomy_model import InterestTag
    from app.models.user_model import Profile, UserInterest

    profile = (await db.execute(select(Profile))).scalars().one()
    assert profile.basics["email"] == "jane@example.com"
    assert profile.basics["links"][0]["url"] == "https://github.com/janedoe"
    assert profile.academics["languages"][0]["code"] == "en"
    tags = {t.id: t.key for t in (await db.execute(select(InterestTag))).scalars()}
    interests = (await db.execute(select(UserInterest))).scalars().all()
    assert {tags[i.interest_tag_id] for i in interests} == {"technology-software"}


async def test_discard_blocks_apply(client, db, auth_headers):
    doc_id = await _upload_and_parse(client, db, auth_headers)
    discarded = await client.post(
        f"/api/v1/cv/intake/{doc_id}/discard", headers=auth_headers
    )
    assert discarded.status_code == 204
    blocked = await client.post(
        f"/api/v1/cv/intake/{doc_id}/apply",
        json={"selections": {"skills": True}},
        headers=auth_headers,
    )
    assert blocked.status_code == 400


async def test_intake_ownership_enforced(client, db, auth_headers):
    doc_id = await _upload_and_parse(client, db, auth_headers)
    other = await client.post(
        "/api/v1/auth/register",
        json={"email": "intake-other@example.com", "password": "supersecret1"},
    )
    other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}
    response = await client.get(
        f"/api/v1/cv/intake/{doc_id}/drafts", headers=other_headers
    )
    assert response.status_code == 404


async def test_document_delete_cascades_draft(client, db, auth_headers):
    doc_id = await _upload_and_parse(client, db, auth_headers)
    deleted = await client.delete(f"/api/v1/documents/{doc_id}", headers=auth_headers)
    assert deleted.status_code == 204
    from app.models.cv_intake_model import CvParseDraft

    assert (await db.execute(select(CvParseDraft))).scalars().all() == []


async def test_import_history_lists_drafts_with_documents(client, db, auth_headers):
    doc_id = await _upload_and_parse(client, db, auth_headers)
    listing = await client.get("/api/v1/cv/intake/drafts", headers=auth_headers)
    assert listing.status_code == 200, listing.text
    rows = listing.json()
    assert len(rows) == 1
    row = rows[0]
    assert row["document_id"] == doc_id
    assert row["status"] == "pending"
    assert row["report"] == {}
    assert row["document"]["filename"] == "cv.txt"
    assert row["document"]["status"] == "ready"
    assert row["document"]["created_at"] is not None


async def test_import_history_reflects_apply_and_isolation(client, db, auth_headers):
    doc_id = await _upload_and_parse(client, db, auth_headers)
    applied = await client.post(
        f"/api/v1/cv/intake/{doc_id}/apply",
        json={"selections": {"skills": True}},
        headers=auth_headers,
    )
    assert applied.status_code == 200, applied.text

    rows = (await client.get("/api/v1/cv/intake/drafts", headers=auth_headers)).json()
    assert rows[0]["status"] == "applied"
    assert rows[0]["report"]["created"].get("skills") == 2

    other = await client.post(
        "/api/v1/auth/register",
        json={"email": "history-other@example.com", "password": "supersecret1"},
    )
    other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}
    assert (
        await client.get("/api/v1/cv/intake/drafts", headers=other_headers)
    ).json() == []


async def test_document_kind_filter(client, db, auth_headers):
    await _upload_and_parse(client, db, auth_headers)
    cvs = await client.get(
        "/api/v1/documents?kind=cv", params={"kind": "cv"}, headers=auth_headers
    )
    assert cvs.status_code == 200
    rows = cvs.json()
    assert len(rows) == 1
    assert rows[0]["kind"] == "cv"
    assert rows[0]["created_at"] is not None


async def test_mock_parser_heuristics_read_plain_text():
    from app.ai.agents.cv_parser import _mock_cv_extract

    text = (
        "Ilias Papadopoulos\n"
        "Athens, Greece\n"
        "ilias@example.com | +30 694 123 4567\n"
        "Summary\n"
        "Backend student who loves pipelines and data tooling.\n"
        "Skills\n"
        "Python, SQL, Docker\n"
        "Experience\n"
        "Software Intern — Acme (2024-06 - 2024-09)\n"
        "Education\n"
        "BSc Physics — NKUA (2022-09 - 2026-06)\n"
    )
    from app.ai.agents.context import context_json

    extract = _mock_cv_extract(dict, context_json({"cv_text": text}))
    assert extract["basics"]["full_name"] == "Ilias Papadopoulos"
    assert extract["basics"]["email"] == "ilias@example.com"
    assert "+30 694 123 4567" in extract["basics"]["phone"]
    assert [s["name"] for s in extract["skills"]] == ["Python", "SQL", "Docker"]
    assert extract["experience"][0]["title"] == "Software Intern"
    assert extract["experience"][0]["org"] == "Acme"
    assert extract["experience"][0]["start"] == "2024-06"
    assert extract["education"][0]["program"] == "BSc Physics"
    assert extract["education"][0]["institution"] == "NKUA"
    assert "pipelines" in extract["summary"]
    assert extract["experience"][0]["evidence"]["confidence"] == 0.55


async def test_import_history_reports_section_count(client, db, auth_headers):
    await _upload_and_parse(client, db, auth_headers)
    rows = (await client.get("/api/v1/cv/intake/drafts", headers=auth_headers)).json()
    assert rows[0]["section_count"] >= 5

    from app.models.cv_intake_model import CvParseDraft

    draft = (await db.execute(select(CvParseDraft))).scalars().first()
    draft.payload = {
        "basics": {},
        "education": [],
        "experience": [],
        "skills": [],
        "languages": [],
        "certifications": [],
        "awards": [],
        "interests": [],
        "summary": "",
    }
    await db.commit()
    rows = (await client.get("/api/v1/cv/intake/drafts", headers=auth_headers)).json()
    assert rows[0]["section_count"] == 0
