"""Plan 212 S1.3 — the application kit.

One pre-application kit per posting (`GET /postings/{ref}/kit`), an
idempotent deterministic prep (`POST .../kit/prepare` that creates
nothing), and the application-scoped kit (`GET /applications/{id}/kit`)
with timeline and linked documents. These tests pin the shapes, the
bounds, the degraded no-extract state, the ownership check and the
"nothing auto-applies" law: prepare writes no CV, no cover letter, no
application row and makes no AI call.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.ai.agents.posting_extractor import ExtractSkill, PostingExtract
from app.models.ai_model import AIGeneration
from app.models.application_model import Application
from app.models.cv_model import CvDocument, CvVersion
from app.models.taxonomy_model import Skill
from app.services.postings.application_kit_service import (
    ANSWER_PROMPTS,
    CV_CANDIDATE_CAP,
)
from tests.conftest import _make_posting, _uid, mint_session_headers


async def _extracted_posting(db, source, external_id: str | None = None):
    """A posting whose extract resolves one label onto a seeded skill."""
    skill_row = (await db.execute(select(Skill).limit(1))).scalars().first()
    assert skill_row is not None
    posting = await _make_posting(
        db, source, external_id=external_id or f"kit-{uuid.uuid4().hex[:8]}"
    )
    from app.services.postings.extract_service import apply_extract

    await apply_extract(
        db,
        posting,
        PostingExtract(
            title_norm="Junior Data Analyst",
            language_requirements=[
                {
                    "code": "en",
                    "level": "advanced",
                    "evidence_quote": "Fluent English required",
                    "confidence": 0.9,
                },
                {
                    "code": "el",
                    "level": "intermediate",
                    "evidence_quote": "Greek is a plus",
                    "confidence": 0.8,
                },
            ],
            skills=[
                ExtractSkill(
                    raw_label=skill_row.label,
                    required_level=4,
                    priority="must_have",
                    evidence_quote="solid SQL required",
                    confidence=0.9,
                ),
            ],
        ),
    )
    await db.commit()
    await db.refresh(posting)
    return posting, skill_row


async def _cv(client, headers, title: str, **payload) -> dict:
    response = await client.post("/api/v1/cv", json={"title": title, **payload}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


async def _letter(client, headers, posting_id: str) -> dict:
    response = await client.post(
        "/api/v1/cv/cover-letters", json={"posting_id": posting_id}, headers=headers
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _track(client, headers, posting, **payload) -> dict:
    response = await client.post(
        "/api/v1/me/applications",
        json={"posting_id": str(posting.id), **payload},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


# ----------------------------------------------------------------- kit GET


async def test_kit_shape_without_cv_or_application(
    client, auth_headers, db, source, seeded_catalog
):
    posting, _skill = await _extracted_posting(db, source)
    response = await client.get(f"/api/v1/postings/{posting.ref}/kit", headers=auth_headers)
    assert response.status_code == 200, response.text
    kit = response.json()

    assert kit["posting"]["ref"] == posting.ref
    assert kit["posting"]["extract_ready"] is True
    assert kit["posting"]["title"] == posting.title
    # The S1.1 gap report rides the kit unchanged.
    assert set(kit["gap"]) == {"must_have", "nice_to_have", "bonus"}
    assert kit["gap"]["must_have"][0]["evidence_quote"] == "solid SQL required"

    assert kit["cv"]["needs_cv"] is True
    assert kit["cv"]["candidates"] == []
    assert kit["cv"]["variant"] is None
    assert kit["cover_letter"]["doc"] is None

    # Deterministic prompts, all unsaved — the S1.5 library ships later.
    assert len(kit["answers"]) == len(ANSWER_PROMPTS) + 1  # + the languages prompt
    assert len(kit["answers"]) <= 8
    assert all(prompt["saved_answer"] is None for prompt in kit["answers"])
    assert {prompt["key"] for prompt in kit["answers"]} == {
        key for key, _text in ANSWER_PROMPTS
    } | {"languages_posting"}

    ids = [item["id"] for item in kit["checklist"]]
    assert ids[:1] == ["posting_open"]
    assert "cv_missing" in ids
    assert {"file_format", "file_size", "file_name"} <= set(ids)
    for item in kit["checklist"]:
        assert item["source"] in {"posting", "kit", "lint", "guidance"}
    assert kit["application"] is None

    unknown = await client.get(f"/api/v1/postings/{uuid.uuid4()}/kit", headers=auth_headers)
    assert unknown.status_code == 404


async def test_kit_without_extract_is_degraded_but_explicit(
    client, auth_headers, db, source, seeded_catalog
):
    posting = await _make_posting(db, source, external_id=f"kit-raw-{uuid.uuid4().hex[:8]}")
    response = await client.get(f"/api/v1/postings/{posting.ref}/kit", headers=auth_headers)
    assert response.status_code == 200, response.text
    kit = response.json()
    assert kit["posting"]["extract_ready"] is False
    assert kit["gap"] is None
    # Answers and checklist still work — only evidence-backed parts degrade.
    assert len(kit["answers"]) == len(ANSWER_PROMPTS)
    assert "posting_open" in {item["id"] for item in kit["checklist"]}


async def test_kit_cv_state_prefers_the_scoped_variant(
    client, auth_headers, db, source, seeded_catalog
):
    posting, _skill = await _extracted_posting(db, source)
    generic = await _cv(client, auth_headers, "Generic CV")
    variant = await _cv(client, auth_headers, "Tailored CV", target_posting_id=str(posting.id))
    await _letter(client, auth_headers, str(posting.id))

    response = await client.get(f"/api/v1/postings/{posting.ref}/kit", headers=auth_headers)
    kit = response.json()
    assert kit["cv"]["needs_cv"] is False
    assert kit["cv"]["variant"]["id"] == variant["id"]
    assert kit["cv"]["variant"]["target_posting_id"] == str(posting.id)
    assert {row["id"] for row in kit["cv"]["candidates"]} == {generic["id"], variant["id"]}
    assert kit["cover_letter"]["doc"]["target_posting_id"] == str(posting.id)


async def test_kit_checklist_reports_closed_postings(
    client, auth_headers, db, source, seeded_catalog
):
    posting = await _make_posting(
        db,
        source,
        external_id=f"kit-expired-{uuid.uuid4().hex[:8]}",
        expires_at=datetime.now(UTC) - timedelta(days=1),
    )
    response = await client.get(f"/api/v1/postings/{posting.ref}/kit", headers=auth_headers)
    kit = response.json()
    posting_open = next(item for item in kit["checklist"] if item["id"] == "posting_open")
    assert posting_open["level"] == "warn"
    assert posting_open["source"] == "posting"


async def test_kit_page_count_reports_its_source(client, auth_headers, db, source, seeded_catalog):
    posting, _skill = await _extracted_posting(db, source)
    await _cv(client, auth_headers, "Only CV", target_posting_id=str(posting.id))
    response = await client.get(f"/api/v1/postings/{posting.ref}/kit", headers=auth_headers)
    kit = response.json()
    pages = next(item for item in kit["checklist"] if item["id"] == "cv_pages")
    # When the PDF engine measured, the item says so; when no engine (and
    # no prior export) exists, the item stays honestly unmeasured — never
    # an estimate dressed as a count.
    if pages["level"] == "info":
        assert "export once" in pages["label"]
    else:
        assert pages["label"].startswith("Measured ")
        assert pages["source"] in {"pdf", "last_export"}


# --------------------------------------------------------------- prepare


async def test_prepare_is_idempotent_and_writes_nothing(
    client, auth_headers, db, source, seeded_catalog
):
    from app.models.user_model import UserSkill

    posting, skill_row = await _extracted_posting(db, source)
    user_id = _uid(auth_headers)
    db.add(UserSkill(user_id=user_id, skill_id=skill_row.id, level=6))
    await db.commit()
    await _cv(client, auth_headers, "My CV", target_posting_id=str(posting.id))

    first = await client.post(f"/api/v1/postings/{posting.ref}/kit/prepare", headers=auth_headers)
    assert first.status_code == 200, first.text
    second = await client.post(f"/api/v1/postings/{posting.ref}/kit/prepare", headers=auth_headers)
    assert second.status_code == 200, second.text
    assert first.json() == second.json()

    payload = first.json()
    assert payload["needs_cv"] is False
    assert payload["extract_ready"] is True
    assert payload["cv_id"] is not None
    covered = payload["coverage"]["covered"]
    assert covered and covered[0]["status"] == "met"
    assert covered[0]["evidence_quote"] == "solid SQL required"

    # The law: no CV, no letter, no application row, no version, no AI call.
    assert (await db.execute(select(func.count()).select_from(CvDocument))).scalar_one() == 1
    assert (await db.execute(select(func.count()).select_from(Application))).scalar_one() == 0
    assert (await db.execute(select(func.count()).select_from(CvVersion))).scalar_one() == 0
    assert (await db.execute(select(func.count()).select_from(AIGeneration))).scalar_one() == 0


async def test_prepare_without_cv_asks_for_cv_studio(
    client, auth_headers, db, source, seeded_catalog
):
    posting, _skill = await _extracted_posting(db, source)
    response = await client.post(
        f"/api/v1/postings/{posting.ref}/kit/prepare", headers=auth_headers
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["needs_cv"] is True
    assert payload["cv_id"] is None
    assert payload["coverage"] is None


async def test_prepare_without_extract_returns_no_coverage(
    client, auth_headers, db, source, seeded_catalog
):
    posting = await _make_posting(db, source, external_id=f"kit-prep-{uuid.uuid4().hex[:8]}")
    await _cv(client, auth_headers, "Plain CV")
    response = await client.post(
        f"/api/v1/postings/{posting.ref}/kit/prepare", headers=auth_headers
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["extract_ready"] is False
    assert payload["coverage"] is None
    # The deterministic section report still runs on the CV.
    assert isinstance(payload["section_gaps"], list)


# -------------------------------------------------------- application kit


async def test_application_kit_composes_timeline_and_documents(
    client, auth_headers, db, source, seeded_catalog
):
    posting, _skill = await _extracted_posting(db, source)
    cv = await _cv(client, auth_headers, "Sent CV", target_posting_id=str(posting.id))
    letter = await _letter(client, auth_headers, str(posting.id))
    tracked = await _track(
        client,
        auth_headers,
        posting,
        cv_id=cv["id"],
        cover_letter_id=letter["id"],
    )

    response = await client.get(
        f"/api/v1/me/applications/{tracked['id']}/kit", headers=auth_headers
    )
    assert response.status_code == 200, response.text
    kit = response.json()
    assert kit["application"]["id"] == tracked["id"]
    assert kit["application"]["stage"] == "applied"
    assert [event["kind"] for event in kit["timeline"]] == ["stage_change"]
    assert kit["timeline_truncated"] is False
    assert kit["documents"]["cv"]["id"] == cv["id"]
    assert kit["documents"]["cover_letter"]["id"] == letter["id"]
    # Everything the posting kit carries rides along.
    assert kit["posting"]["ref"] == posting.ref
    assert kit["cv"]["variant"]["id"] == cv["id"]


async def test_application_kit_foreign_is_404(client, auth_headers, db, source, seeded_catalog):
    posting = await _make_posting(db, source, external_id=f"kit-own-{uuid.uuid4().hex[:8]}")
    tracked = await _track(client, auth_headers, posting)
    other = mint_session_headers(email=f"kit-other-{_uid(auth_headers)[:8]}@example.com")
    response = await client.get(f"/api/v1/me/applications/{tracked['id']}/kit", headers=other)
    assert response.status_code == 404


async def test_application_kit_unknown_is_404(client, auth_headers, db):
    response = await client.get(f"/api/v1/me/applications/{uuid.uuid4()}/kit", headers=auth_headers)
    assert response.status_code == 404


async def test_cv_candidates_are_bounded(client, auth_headers, db, source, seeded_catalog):
    posting, _skill = await _extracted_posting(db, source)
    for index in range(CV_CANDIDATE_CAP + 3):
        await _cv(client, auth_headers, f"CV {index}")
    response = await client.get(f"/api/v1/postings/{posting.ref}/kit", headers=auth_headers)
    kit = response.json()
    assert len(kit["cv"]["candidates"]) == CV_CANDIDATE_CAP
