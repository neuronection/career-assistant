"""Plan 129 phase 3 — structured prerequisites: typed extract rows, the
fit dimension consuming them, and the known/unknown display contract."""

import uuid

from app.ai.agents.posting_extractor import ExtractPrerequisite, PostingExtract
from app.models.profile_entities_model import Certification
from app.services.postings.extract_service import apply_extract
from app.services.postings.posting_fit_service import get_posting_fit
from app.services.postings.postings_service import upsert_posting
from tests.conftest import _raw_posting, _uid


def _extract(**overrides) -> PostingExtract:
    payload = {
        "prerequisites": [
            ExtractPrerequisite(
                kind="certificate",
                label="PMP certificate",
                evidence_quote="PMP certification required",
                confidence=0.9,
            ),
            ExtractPrerequisite(
                kind="degree",
                label="BSc in Computer Science",
                evidence_quote="holds a BSc in Computer Science",
                confidence=0.85,
            ),
        ],
        "field_confidence": {"prerequisites": 0.9},
    }
    payload.update(overrides)
    return PostingExtract(**payload)


async def test_apply_extract_persists_prerequisites(db, seeded_catalog, source):
    posting = await upsert_posting(db, source, _raw_posting())
    await apply_extract(db, posting, _extract())
    await db.commit()
    await db.refresh(posting)
    rows = posting.extract["prerequisites"]
    assert [row["kind"] for row in rows] == ["certificate", "degree"]
    assert rows[0]["label"] == "PMP certificate"
    assert rows[0]["evidence_quote"] == "PMP certification required"


async def test_low_confidence_prerequisites_suppressed(db, seeded_catalog, source):
    posting = await upsert_posting(db, source, _raw_posting())
    await apply_extract(db, posting, _extract(field_confidence={"prerequisites": 0.4}))
    await db.commit()
    await db.refresh(posting)
    assert posting.extract.get("prerequisites") == [], (
        "below the confidence threshold the rows are dropped, never guessed"
    )
    assert posting.needs_review is True, "suppressed rows flag the posting for review"


async def _fit_for(db, auth_headers, source, certifications: list[str]) -> dict:
    from app.models.profile_entities_model import Certification

    posting = await upsert_posting(db, source, _raw_posting(external_id="prereq-fit"))
    await apply_extract(db, posting, _extract())
    await db.commit()
    user_id = uuid.UUID(_uid(auth_headers))
    for name in certifications:
        db.add(Certification(user_id=user_id, name=name))
    await db.commit()
    return await get_posting_fit(db, user_id, posting)


async def test_stated_certificate_without_profile_match_caps_score(
    db, client, auth_headers, profile_ready, seeded_catalog, source
):
    result = await _fit_for(db, auth_headers, source, certifications=[])
    prereqs = result["breakdown"]["prereqs"]
    assert prereqs["score"] <= 6.0
    assert "PMP certificate not evidenced" in prereqs["detail"]
    assert "degree wording: BSc in Computer Science" in prereqs["detail"], (
        "degree rows are note-only — the level comparison rides education"
    )


async def test_matching_certification_recovers_score(
    db, client, auth_headers, profile_ready, seeded_catalog, source
):
    result = await _fit_for(db, auth_headers, source, certifications=["pmp certificate"])
    prereqs = result["breakdown"]["prereqs"]
    assert prereqs["score"] == 10.0
    assert "PMP certificate evidenced" in prereqs["detail"]


async def test_token_overlap_matches_across_wording(
    db, client, auth_headers, profile_ready, seeded_catalog, source
):
    result = await _fit_for(
        db,
        auth_headers,
        source,
        certifications=["project management professional certificate"],
    )
    prereqs = result["breakdown"]["prereqs"]
    assert "PMP certificate evidenced" in prereqs["detail"], (
        "a shared ≥4-char token (certificate) evidences across wording; "
        "the PMP acronym itself stays honestly unmatched"
    )


async def test_short_substring_never_evidences(
    db, client, auth_headers, profile_ready, seeded_catalog, source
):
    result = await _fit_for(db, auth_headers, source, certifications=["p", "pm"])
    prereqs = result["breakdown"]["prereqs"]
    assert prereqs["score"] <= 6.0, "a one/two-letter certification is not evidence"


async def test_draft_certifications_never_evidence(
    db, client, auth_headers, profile_ready, seeded_catalog, source
):
    from app.models.profile_entities_model import Certification

    posting = await upsert_posting(db, source, _raw_posting(external_id="prereq-draft"))
    await apply_extract(db, posting, _extract())
    user_id = uuid.UUID(_uid(auth_headers))
    db.add(
        Certification(user_id=user_id, name="PMP certificate", status="draft", source="cv_parse")
    )
    await db.commit()
    result = await get_posting_fit(db, user_id, posting)
    assert result["breakdown"]["prereqs"]["score"] <= 6.0, (
        "an unreviewed draft row is model-adjacent data, never fit evidence"
    )


async def test_certified_change_invalidates_cached_fit(
    db, client, auth_headers, profile_ready, seeded_catalog, source
):
    posting = await upsert_posting(db, source, _raw_posting(external_id="prereq-cache"))
    await apply_extract(db, posting, _extract())
    await db.commit()
    user_id = uuid.UUID(_uid(auth_headers))
    first = await get_posting_fit(db, user_id, posting)

    db.add(Certification(user_id=user_id, name="PMP certificate"))
    await db.commit()
    second = await get_posting_fit(db, user_id, posting)

    assert first["breakdown"]["prereqs"]["score"] <= 6.0
    assert second["breakdown"]["prereqs"]["score"] == 10.0, (
        "the inputs hash covers certifications — adding one recomputes"
    )
