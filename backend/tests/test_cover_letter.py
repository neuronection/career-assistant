"""— cover letters: brief, grounded draft, letters via the
renderer/export paths."""

import uuid

from sqlalchemy import select

from tests.conftest import _make_posting, _uid

from app.ai.agents.posting_extractor import ExtractSkill, PostingExtract
from app.models.ai_model import AIGeneration
from app.models.taxonomy_model import Skill
from app.models.user_model import UserSkill
from app.schemas.cv_template import TemplateContent
from app.services.cv_builder_service import FALLBACK_CONTENT
from app.services.cv_renderer import render_cv


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


async def _seeded_skill(db) -> Skill:
    skill_row = (await db.execute(select(Skill).limit(1))).scalars().first()
    assert skill_row is not None
    return skill_row


async def _user_skill(db, headers, skill_row: Skill, level: int = 6) -> None:
    db.add(UserSkill(user_id=_uid(headers), skill_id=skill_row.id, level=level))
    await db.commit()


async def _extracted_posting(db, source, skill_row: Skill) -> dict:
    posting = await _make_posting(db, source, external_id="letter-1")
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
        responsibilities=[],
    ).model_dump(mode="json")
    db.add(posting)
    await db.commit()
    await db.refresh(posting)
    return posting


async def test_create_seeds_letter_blocks(
    client, auth_headers, profile_ready, seeded_catalog, db, source
):
    posting = await _make_posting(db, source)
    response = await client.post(
        "/api/v1/cv/cover-letters",
        json={"posting_id": str(posting.id)},
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["kind"] == "cover_letter"
    assert body["target_posting_id"] == str(posting.id)
    assert body["title"].startswith("Cover letter —")
    kinds = [block["kind"] for block in body["working_content"]["blocks"]]
    assert kinds == ["header", "letter"]
    recipient_org = body["working_content"]["blocks"][1]["props"]["recipient_org"]
    assert recipient_org == posting.org


async def test_create_with_base_cv_copies_context_and_template(
    client, auth_headers, profile_ready, seeded_catalog, db, source
):
    posting = await _make_posting(db, source)
    base = await client.post(
        "/api/v1/cv",
        json={
            "title": "Base CV",
            "language": "de",
            "context": {
                "mode": "none",
                "include": [{"source_key": "experience", "item_id": "whatever"}],
                "exclude": [],
            },
        },
        headers=auth_headers,
    )
    assert base.status_code == 201, base.text
    response = await client.post(
        "/api/v1/cv/cover-letters",
        json={
            "posting_id": str(posting.id),
            "title": "Letter (DE)",
            "base_cv_id": base.json()["id"],
        },
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["language"] == "de"
    assert body["context"]["mode"] == "none"


async def test_brief_reports_coverage_and_quotes(
    client, auth_headers, profile_ready, seeded_catalog, db, source
):
    skill_row = await _seeded_skill(db)
    await _user_skill(db, auth_headers, skill_row)
    posting = await _extracted_posting(db, source, skill_row)
    response = await client.get(
        f"/api/v1/cv/cover-letters/brief?posting_id={posting.id}",
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    brief = response.json()
    assert brief["posting_title"] == posting.title
    assert brief["extract_ready"] is True
    must_keys = {skill["skill_key"] for skill in brief["must_have"]}
    assert skill_row.key in must_keys and "kubernetes" in must_keys
    covered = {entry["skill_key"] for entry in brief["coverage"]["covered"]}
    missing = {entry["skill_key"] for entry in brief["coverage"]["missing"]}
    assert skill_row.key in covered and "kubernetes" in missing
    programming = next(
        skill for skill in brief["must_have"] if skill["skill_key"] == skill_row.key
    )
    assert programming["user_level"] == 6
    assert programming["evidence_quote"] == "must know the thing"
    assert brief["evidence_items"] > 0


async def test_draft_returns_verified_paragraphs(
    client, auth_headers, profile_ready, seeded_catalog, db, source
):
    skill_row = await _seeded_skill(db)
    await _experience(client, auth_headers)
    posting = await _extracted_posting(db, source, skill_row)
    created = await client.post(
        "/api/v1/cv/cover-letters",
        json={"posting_id": str(posting.id)},
        headers=auth_headers,
    )
    letter = created.json()
    response = await client.post(
        f"/api/v1/cv/{letter['id']}/ai/cover_letter", json={}, headers=auth_headers
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["action"] == "cover_letter"
    assert body["draft"]["paragraphs"], "mock drafts at least one paragraph"
    known = {
        (key, item_id)
        for key, ids in (
            await client.get(f"/api/v1/cv/{letter['id']}/context", headers=auth_headers)
        )
        .json()["snapshot_index"]
        .items()
        for item_id in ids
    }
    assert body["paragraphs"]
    for paragraph in body["paragraphs"]:
        refs = {
            (ref["source_key"], ref["item_id"]) for ref in paragraph["evidence_refs"]
        }
        assert refs, "every paragraph must cite evidence"
        assert refs <= known, "citations must resolve to the letter's context"
        assert paragraph["verified"] is True
    audited = (
        (
            await db.execute(
                select(AIGeneration).where(AIGeneration.task_type == "cv_cover_letter")
            )
        )
        .scalars()
        .all()
    )
    assert audited, "the draft call must land in ai_generations"
    assert audited[0].status == "ok"


async def test_draft_verification_flags_unknown_refs():
    from app.schemas.cover_letter import CoverLetterDraft, LetterParagraph
    from app.schemas.cv_suggest import CvEvidenceRef
    from app.services.cover_letter_service import _verified

    allowlist = {("experience", "item-1")}
    ok = LetterParagraph(
        text="Grounded.",
        evidence_refs=[CvEvidenceRef(source_key="experience", item_id="item-1")],
    )
    fabricated = LetterParagraph(
        text="Invented.",
        evidence_refs=[CvEvidenceRef(source_key="experience", item_id="nope")],
    )
    unbacked = LetterParagraph(text="No citations.")
    assert _verified(ok, allowlist)
    assert not _verified(fabricated, allowlist)
    assert not _verified(unbacked, allowlist)
    CoverLetterDraft(paragraphs=[ok, fabricated, unbacked])


async def test_letter_kind_rejects_resume_actions(
    client, auth_headers, profile_ready, seeded_catalog, db, source
):
    posting = await _make_posting(db, source)
    created = await client.post(
        "/api/v1/cv/cover-letters",
        json={"posting_id": str(posting.id)},
        headers=auth_headers,
    )
    letter = created.json()
    response = await client.post(
        f"/api/v1/cv/{letter['id']}/ai/summary", json={}, headers=auth_headers
    )
    assert response.status_code == 400
    assert "cover_letter" in response.json()["detail"]


async def test_cover_letter_action_rejects_resume_kind(
    client, auth_headers, profile_ready, seeded_catalog
):
    await _experience(client, auth_headers)
    cv = await client.post("/api/v1/cv", json={"title": "Resume"}, headers=auth_headers)
    response = await client.post(
        f"/api/v1/cv/{cv.json()['id']}/ai/cover_letter", json={}, headers=auth_headers
    )
    assert response.status_code == 400


async def test_letter_exports_and_versions(
    client, auth_headers, profile_ready, seeded_catalog, db, source
):
    posting = await _make_posting(db, source)
    created = await client.post(
        "/api/v1/cv/cover-letters",
        json={"posting_id": str(posting.id)},
        headers=auth_headers,
    )
    letter = created.json()
    patched = await client.patch(
        f"/api/v1/cv/{letter['id']}",
        json={
            "working_content": {
                "blocks": [
                    {"kind": "header"},
                    {
                        "kind": "letter",
                        "props": {
                            "recipient_org": posting.org,
                            "date_label": "Sep 2026",
                            "salutation": "Dear Hiring Team,",
                            "paragraphs": [
                                "I am applying for the Data Analyst role, "
                                "where my analytics coursework and project "
                                "work fit the must-have skills.",
                                "Programming has been my strongest tool "
                                "so far, and it maps directly to this "
                                "team's stack.",
                            ],
                            "closing": "Sincerely,",
                        },
                    },
                ],
                "overrides": {},
            }
        },
        headers=auth_headers,
    )
    assert patched.status_code == 200, patched.text

    md = await client.post(
        f"/api/v1/cv/{letter['id']}/export",
        json={"format": "md"},
        headers=auth_headers,
    )
    assert md.status_code == 200, md.text
    text = md.content.decode()
    assert "Dear Hiring Team," in text
    assert "Data Analyst role" in text
    assert "Sincerely," in text

    versions = (
        await client.get(f"/api/v1/cv/{letter['id']}/versions", headers=auth_headers)
    ).json()
    assert versions and versions[0]["created_by"] == "export"

    docx = await client.post(
        f"/api/v1/cv/{letter['id']}/export",
        json={"format": "docx"},
        headers=auth_headers,
    )
    assert docx.status_code == 200
    assert docx.content[:2] == b"PK"

    lint = (
        await client.get(f"/api/v1/cv/{letter['id']}/lint", headers=auth_headers)
    ).json()
    check_ids = {check["id"] for check in lint["checks"]}
    assert "letter_length" in check_ids
    order = next(check for check in lint["checks"] if check["id"] == "section_order")
    assert order["level"] == "pass"


async def test_letter_block_renders_and_hides():
    blocks = [
        {"kind": "header"},
        {
            "kind": "letter",
            "props": {
                "recipient_name": "Alex Sample",
                "recipient_org": "Sample Corp",
                "date_label": "Jun 2024",
                "paragraphs": ["First paragraph about real work."],
                "salutation": "Dear Hiring Team,",
                "closing": "Sincerely,",
            },
        },
    ]
    content = TemplateContent.model_validate(FALLBACK_CONTENT)
    result = render_cv(
        content.model_copy(update={"blocks": blocks}),
        {"basics": {"name": "Alex Sample", "email": "a@b.co"}},
    )
    body = result.html.split("<body>")[1]
    assert "letter-p" in body
    assert "Dear Hiring Team," in body
    assert "Alex Sample" in body

    empty = TemplateContent.model_validate(
        {**FALLBACK_CONTENT, "blocks": [{"kind": "header"}, {"kind": "letter"}]}
    )
    hidden = render_cv(empty, {"basics": {"name": "Alex Sample"}})
    hidden_body = hidden.html.split("<body>")[1]
    assert "letter-p" not in hidden_body
    assert hidden.metrics.empty_blocks.count("letter") == 1


async def test_unknown_posting_is_404(client, auth_headers, profile_ready):
    response = await client.post(
        "/api/v1/cv/cover-letters",
        json={"posting_id": str(uuid.uuid4())},
        headers=auth_headers,
    )
    assert response.status_code == 404
