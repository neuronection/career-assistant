"""Plan 212 S1.1 — the evidence-first posting gap report.

One shared deterministic computation (`services/postings/gap_service.py`)
feeds the CV tailor coverage and the posting gap surface. These tests pin
the matrix (met/partial/missing, unresolved labels, quote presence, level
edges), the API contract on `GET /postings/{ref}/gap` + `PostingDetailOut.gap`,
and the "no headline percentage" law: the response has no score field.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from app.ai.agents.posting_extractor import ExtractSkill, PostingExtract
from app.models.experience_model import SkillEvidence
from app.models.taxonomy_model import Skill
from app.models.user_model import UserSkill
from app.schemas.posting import (
    PostingExtractSkillOut,
    PostingGapEvidenceOut,
)
from app.services.postings.gap_service import (
    build_gap_rows,
    gap_status,
    group_gap_rows,
    skill_labels,
    skill_levels,
)
from tests.conftest import _make_posting, _uid, session_headers

# ----------------------------------------------------------------- unit


def test_gap_status_matrix():
    assert gap_status(4, 6) == "met"
    assert gap_status(4, 4) == "met"
    assert gap_status(4, 3) == "partial"
    assert gap_status(4, 1) == "partial"
    assert gap_status(4, None) == "missing"
    # Defensive edges: a level of 0 is no level, a requirement without a
    # usable bar is met by any recorded level.
    assert gap_status(4, 0) == "missing"
    assert gap_status(None, 3) == "met"
    assert gap_status(0, 3) == "met"


def _extract_skills() -> list[PostingExtractSkillOut]:
    return [
        PostingExtractSkillOut(
            skill_key="sql",
            raw_label="SQL",
            required_level=4,
            priority="must_have",
            evidence_quote="solid SQL required",
            confidence=0.9,
        ),
        PostingExtractSkillOut(
            skill_key="python",
            raw_label="Python",
            required_level=6,
            priority="must_have",
            evidence_quote="strong Python",
            confidence=0.9,
        ),
        PostingExtractSkillOut(
            skill_key=None,
            raw_label="Vibe coding",
            required_level=2,
            priority="nice_to_have",
            evidence_quote="vibe coding a plus",
            confidence=0.8,
        ),
    ]


def test_build_gap_rows_matrix_unresolved_label_stays():
    rows = build_gap_rows(
        _extract_skills(),
        levels={"sql": 6, "python": 3},
        labels={"sql": "SQL", "python": "Python"},
        evidence={"sql": [PostingGapEvidenceOut(source="experience", label="Acme internship")]},
    )
    by_key = {row.raw_label: row for row in rows}
    assert by_key["SQL"].status == "met" and by_key["SQL"].user_level == 6
    assert by_key["SQL"].evidence_quote == "solid SQL required"
    assert by_key["SQL"].user_evidence[0].source == "experience"
    # Below the bar: partial, still quoted.
    assert by_key["Python"].status == "partial" and by_key["Python"].user_level == 3
    # The unresolved label keeps its row — never dropped silently — with
    # no key, no resolved label, no quote and no user evidence.
    unresolved = by_key["Vibe coding"]
    assert unresolved.skill_key is None and unresolved.label is None
    assert unresolved.evidence_quote == "" and unresolved.user_evidence == []
    assert unresolved.status == "missing" and unresolved.priority == "nice_to_have"


def test_group_gap_rows_priorities():
    rows = build_gap_rows(
        _extract_skills(),
        levels={},
        labels={},
        evidence={},
    )
    grouped = group_gap_rows(rows)
    assert [row.raw_label for row in grouped.must_have] == ["SQL", "Python"]
    assert [row.raw_label for row in grouped.nice_to_have] == ["Vibe coding"]
    assert grouped.bonus == []


def test_coverage_matrix_carries_evidence():
    from app.schemas.posting import PostingExtractOut
    from app.services.cv.cv_suggestion_service import tailor_coverage

    extract = PostingExtractOut(skills=_extract_skills())
    coverage = tailor_coverage(
        extract,
        levels={"sql": 6, "python": 3},
        labels={"sql": "SQL", "python": "Python"},
        evidence={"sql": [PostingGapEvidenceOut(source="assessment")]},
    )
    covered = {entry.skill_key: entry for entry in coverage.covered}
    assert covered["sql"].status == "met" and covered["sql"].label == "SQL"
    assert covered["sql"].evidence_quote == "solid SQL required"
    assert covered["sql"].raw_label == "SQL"
    assert covered["sql"].kind == "skill"
    assert covered["sql"].required_level == 4
    assert covered["sql"].user_evidence[0].source == "assessment"
    # A recorded level below the bar is covered-listed but honestly partial.
    assert covered["python"].status == "partial"
    # No recorded level → missing, no evidence claimed.
    assert [entry.skill_key for entry in coverage.missing] == []
    missing_only = tailor_coverage(extract, levels={}, labels={}, evidence={})
    assert {entry.skill_key for entry in missing_only.missing} == {"sql", "python"}
    assert all(entry.status == "missing" for entry in missing_only.missing)
    # Unresolved labels are the gap report's rows, not coverage's.
    assert all(entry.skill_key for entry in coverage.covered + coverage.missing)


# ------------------------------------------------------------ API contract


async def _experience(client, headers) -> dict:
    created = await client.post(
        "/api/v1/me/experience",
        json={
            "title": "Data intern",
            "kind": "internship",
            "org_name": "Acme Cloud",
            "start": "2025-01-01",
            "end": "2025-12-31",
            "hours_per_week": 20,
            "description": "Queried things.",
            "skills": [],
            "achievements": [],
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    return created.json()


async def _extracted_posting(db, source, unresolved_label="vibe coding"):
    """A posting whose extract resolves one label onto a seeded skill and
    leaves one label unresolved (the never-dropped row)."""
    skill_row = (await db.execute(select(Skill).limit(1))).scalars().first()
    assert skill_row is not None
    posting = await _make_posting(db, source, external_id=f"gap-{uuid.uuid4().hex[:8]}")
    from app.services.postings.extract_service import apply_extract

    await apply_extract(
        db,
        posting,
        PostingExtract(
            title_norm="Junior Data Analyst",
            skills=[
                ExtractSkill(
                    raw_label=skill_row.label,
                    required_level=4,
                    priority="must_have",
                    evidence_quote="solid SQL required",
                    confidence=0.9,
                ),
                ExtractSkill(
                    raw_label=unresolved_label,
                    required_level=2,
                    priority="nice_to_have",
                    evidence_quote="vibe coding a plus",
                    confidence=0.8,
                ),
            ],
        ),
    )
    await db.commit()
    await db.refresh(posting)
    return posting, skill_row


async def test_gap_endpoint_groups_and_carries_evidence(
    db, client, auth_headers, profile_ready, seeded_catalog, source, kinds
):
    user_id = _uid(auth_headers)
    item = await _experience(client, auth_headers)
    posting, skill_row = await _extracted_posting(db, source)
    db.add(UserSkill(user_id=user_id, skill_id=skill_row.id, level=6, source="self_report"))
    db.add(
        SkillEvidence(
            user_id=user_id,
            skill_id=skill_row.id,
            experience_item_id=uuid.UUID(item["id"]),
            note="derived from experience",
            level_value=6.0,
            claimed_at=datetime.now(UTC),
        )
    )
    await db.commit()

    response = await client.get(f"/api/v1/postings/{posting.ref}/gap", headers=auth_headers)
    assert response.status_code == 200, response.text
    gap = response.json()
    # No headline percentage, no score — the report is rows only.
    assert set(gap) == {"must_have", "nice_to_have", "bonus"}
    must = gap["must_have"]
    assert len(must) == 1
    row = must[0]
    assert row["skill_key"] == skill_row.key
    assert row["label"] == skill_row.label
    assert row["raw_label"] == skill_row.label
    assert row["required_level"] == 4
    assert row["user_level"] == 6
    assert row["status"] == "met"
    assert row["kind"] == "skill"
    assert row["evidence_quote"] == "solid SQL required"
    assert row["user_evidence"] == [
        {"source": "experience", "label": "Data intern"},
    ]
    unresolved = gap["nice_to_have"][0]
    assert unresolved["raw_label"] == "vibe coding"
    assert unresolved["skill_key"] is None and unresolved["label"] is None
    assert unresolved["evidence_quote"] == "" and unresolved["user_evidence"] == []
    assert unresolved["status"] == "missing"


async def test_gap_endpoint_reflects_partial_and_absent_levels(
    db, client, auth_headers, profile_ready, seeded_catalog, source, kinds
):
    user_id = _uid(auth_headers)
    posting, skill_row = await _extracted_posting(db, source, unresolved_label="go")
    db.add(UserSkill(user_id=user_id, skill_id=skill_row.id, level=3))
    await db.commit()

    response = await client.get(f"/api/v1/postings/{posting.ref}/gap", headers=auth_headers)
    assert response.status_code == 200, response.text
    row = response.json()["must_have"][0]
    assert row["status"] == "partial" and row["user_level"] == 3
    assert row["user_evidence"] == [], "self_report levels claim no ledger evidence"

    # A user with no levels at all sees the same row as missing.
    other = await client.post(
        "/api/v1/auth/register",
        json={
            "email": f"{uuid.uuid4().hex[:10]}@example.com",
            "password": "Str0ngPass!23",
            "full_name": "Other",
        },
    )
    headers = session_headers(other)
    theirs = await client.get(f"/api/v1/postings/{posting.ref}/gap", headers=headers)
    assert theirs.status_code == 200, theirs.text
    assert theirs.json()["must_have"][0]["status"] == "missing"
    assert theirs.json()["must_have"][0]["user_level"] is None


async def test_gap_endpoint_null_without_extract(
    db, client, auth_headers, profile_ready, seeded_catalog, source, kinds
):
    posting = await _make_posting(db, source, external_id=f"gap-none-{uuid.uuid4().hex[:6]}")
    response = await client.get(f"/api/v1/postings/{posting.ref}/gap", headers=auth_headers)
    assert response.status_code == 200, response.text
    assert response.json() is None


async def test_gap_endpoint_unknown_ref_404(client, auth_headers, profile_ready, seeded_catalog):
    response = await client.get("/api/v1/postings/NOPE0000/gap", headers=auth_headers)
    assert response.status_code == 404


async def test_detail_embeds_the_gap(
    db, client, auth_headers, profile_ready, seeded_catalog, source, kinds
):
    posting, skill_row = await _extracted_posting(db, source)
    response = await client.get(f"/api/v1/postings/{posting.ref}", headers=auth_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    gap = body["gap"]
    assert gap is not None
    assert {row["raw_label"] for row in gap["must_have"] + gap["nice_to_have"]} == {
        skill_row.label,
        "vibe coding",
    }
    # The match score stays where it was — untouched by the gap report.
    assert set(gap) == {"must_have", "nice_to_have", "bonus"}

    bare = await _make_posting(db, source, external_id=f"gap-bare-{uuid.uuid4().hex[:6]}")
    response = await client.get(f"/api/v1/postings/{bare.ref}", headers=auth_headers)
    assert response.status_code == 200, response.text
    assert response.json()["gap"] is None


async def test_tailor_coverage_ships_status_and_evidence(
    client, auth_headers, profile_ready, seeded_catalog, db, source
):
    """The tailor coverage is the same computation: every row carries
    status, quote and evidence refs on the wire."""
    skill_row = (await db.execute(select(Skill).limit(1))).scalars().first()
    user_id = _uid(auth_headers)
    db.add(UserSkill(user_id=user_id, skill_id=skill_row.id, level=6))
    await db.commit()
    await _experience(client, auth_headers)
    cv = (await client.post("/api/v1/cv", json={"title": "Tailor CV"}, headers=auth_headers)).json()
    posting, _skill = await _extracted_posting(db, source, unresolved_label="go")
    response = await client.post(
        f"/api/v1/cv/{cv['id']}/ai/tailor",
        json={"posting_id": str(posting.id)},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    coverage = response.json()["coverage"]
    covered = next(entry for entry in coverage["covered"] if entry["skill_key"] == skill_row.key)
    assert covered["status"] == "met"
    assert covered["required_level"] == 4
    assert covered["evidence_quote"] == "solid SQL required"
    assert covered["raw_label"] == skill_row.label
    assert covered["user_evidence"] == []


# --------------------------------------------------------- loader bounds


async def test_skill_levels_and_labels_are_key_bounded(
    db, auth_headers, profile_ready, seeded_catalog
):
    user_id = _uid(auth_headers)
    rows = (await db.execute(select(Skill).limit(2))).scalars().all()
    first, second = rows[0], rows[1]
    db.add(UserSkill(user_id=user_id, skill_id=first.id, level=5))
    db.add(UserSkill(user_id=user_id, skill_id=second.id, level=2, derive_enabled=False))
    await db.commit()
    levels = await skill_levels(db, user_id, [first.key, second.key])
    assert levels == {first.key: 5}, "derive_enabled=False rows stay out"
    labels = await skill_labels(db, [first.key])
    assert labels == {first.key: first.label}
    assert await skill_levels(db, user_id, []) == {}
