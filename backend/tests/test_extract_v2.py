"""slice 1 — PostingExtract v2: contract, hours, schedule, travel,
onsite + typed benefits; lifestyle gates against constraints."""

import pytest
from pydantic import ValidationError

from tests.conftest import _make_posting, _uid

from app.ai.agents.posting_extractor import (
    ExtractBenefit,
    ExtractHours,
    ExtractScheduleCue,
    ExtractTravel,
    PostingExtract,
    extract_posting,
)
from app.services.extract_service import EXTRACT_VERSION, apply_extract
from app.services.posting_fit_service import lifestyle_gates


# ------------------------------------------------------------- schema v2


def test_v2_fields_require_evidence_and_literals():
    with pytest.raises(ValidationError):
        ExtractScheduleCue(cue="nights", evidence_quote="x", confidence=0.9)
    with pytest.raises(ValidationError):
        ExtractScheduleCue(
            cue="overtime", evidence_quote="a verbatim quote", confidence=0.9
        )
    with pytest.raises(ValidationError):
        ExtractTravel(level="sometimes", evidence_quote="a verbatim quote")
    cue = ExtractScheduleCue(
        cue="nights", evidence_quote="night shifts rotation", confidence=0.9
    )
    assert cue.cue == "nights"


def test_unset_vs_zero_distinct():
    unstated = ExtractTravel(
        level="frequent",
        days_per_month=None,
        evidence_quote="travel across EU",
        confidence=0.9,
    )
    stated = ExtractTravel(
        level="frequent",
        days_per_month=0,
        evidence_quote="travel across EU",
        confidence=0.9,
    )
    assert unstated.days_per_month is None
    assert stated.days_per_month == 0
    hybrid = ExtractHours(
        pattern="part_time",
        hours_per_week_min=None,
        hours_per_week_max=20,
        evidence_quote="part-time role",
        confidence=0.9,
    )
    assert hybrid.hours_per_week_min is None


def test_legacy_string_benefits_coerce():
    legacy = PostingExtract.model_validate(
        {"benefits": ["Private healthcare", "Meal vouchers"]}
    )
    assert [b.kind for b in legacy.benefits] == ["other", "other"]
    assert legacy.benefits[0].raw == "Private healthcare"
    typed = PostingExtract.model_validate(
        {
            "benefits": [
                {"kind": "healthcare", "raw": "Private healthcare", "confidence": 0.9}
            ]
        }
    )
    assert typed.benefits[0].kind == "healthcare"
    assert ExtractBenefit.coerce("Gym") == ExtractBenefit(
        kind="other", raw="Gym", confidence=0.5
    )


# ------------------------------------------------------------ apply path


async def test_apply_extract_v2_lifestyle_facts_and_columns(
    db, client, auth_headers, seeded_catalog, source
):
    posting = await _make_posting(db, source)
    extract = PostingExtract(
        employment_type="part_time",
        contract_type={
            "contract_type": "contract",
            "evidence_quote": "12-month contract position",
            "confidence": 0.9,
        },
        work_hours={
            "pattern": "part_time",
            "hours_per_week_min": 20,
            "hours_per_week_max": 30,
            "evidence_quote": "part-time, 20-30 hours per week",
            "confidence": 0.9,
        },
        schedule_cues=[
            ExtractScheduleCue(
                cue="shift_work",
                evidence_quote="rotating shift schedule",
                confidence=0.9,
            )
        ],
        travel_required=ExtractTravel(
            level="occasional",
            days_per_month=None,
            evidence_quote="occasional travel to client sites",
            confidence=0.9,
        ),
        benefits=[
            {"kind": "healthcare", "raw": "Private healthcare", "confidence": 0.9}
        ],
        skills=[],
    )
    await apply_extract(db, posting, extract)
    await db.commit()
    await db.refresh(posting)

    assert posting.extract_version == EXTRACT_VERSION == 2
    assert posting.employment_type == "part_time"
    facts = posting.posting_facts
    assert facts["lifestyle"]["contract_type"]["contract_type"] == "contract"
    assert facts["lifestyle"]["work_hours"]["hours_per_week_max"] == 30
    assert facts["lifestyle"]["schedule_cues"][0]["cue"] == "shift_work"
    assert facts["lifestyle"]["travel_required"]["level"] == "occasional"
    assert facts["benefits"][0]["kind"] == "healthcare"
    assert posting.needs_review is False


async def test_apply_extract_v2_suppression_keeps_gates_honest(
    db, client, auth_headers, seeded_catalog, source
):
    posting = await _make_posting(db, source)
    extract = PostingExtract(
        travel_required=ExtractTravel(
            level="frequent",
            days_per_month=None,
            evidence_quote="extensive travel",
            confidence=0.9,
        ),
        skills=[],
        field_confidence={"travel_required": 0.3},
    )
    await apply_extract(db, posting, extract)
    await db.commit()
    await db.refresh(posting)

    assert posting.extract["travel_required"] is None
    assert "lifestyle" not in (posting.posting_facts or {})
    assert posting.needs_review is True
    assert lifestyle_gates(posting, {"travel_days_per_month": 2}) == []


# ---------------------------------------------------------------- gates


async def test_lifestyle_gate_rules(db, source):
    posting = await _make_posting(db, source)
    posting.posting_facts = {
        "lifestyle": {
            "travel_required": {
                "level": "frequent",
                "days_per_month": 15,
                "evidence_quote": "q",
            },
            "schedule_cues": [{"cue": "on_call", "evidence_quote": "q"}],
            "work_hours": {
                "pattern": "full_time",
                "hours_per_week_min": 40,
                "evidence_quote": "q",
            },
        }
    }
    gates = lifestyle_gates(
        posting,
        {
            "travel_days_per_month": 10,
            "shift_tolerance": "none",
            "hours_available_per_week": 20,
        },
    )
    assert gates == ["travel", "shift", "hours"]

    lenient = lifestyle_gates(
        posting,
        {
            "travel_days_per_month": 20,
            "shift_tolerance": "occasional",
            "hours_available_per_week": 40,
        },
    )
    assert lenient == []

    unstated_frequent = posting
    unstated_frequent.posting_facts = {
        "lifestyle": {"travel_required": {"level": "frequent", "days_per_month": None}}
    }
    assert lifestyle_gates(unstated_frequent, {"travel_days_per_month": 5}) == [
        "travel"
    ]
    assert lifestyle_gates(unstated_frequent, {"travel_days_per_month": 15}) == []
    assert lifestyle_gates(unstated_frequent, {}) == []
    no_constraints = lifestyle_gates(posting, None)
    assert no_constraints == []


# --------------------------------------------------- mock extraction v2


async def test_mock_extracts_v2_cues(db, auth_headers, seeded_catalog):
    result = await extract_posting(
        db,
        _uid(auth_headers),
        title="Support Engineer",
        description=(
            "This is a full-time contract position with rotating shift "
            "schedule and on-call duties. Frequent travel to client sites. "
            "We offer private health insurance and a learning budget."
        ),
        skills_raw=[],
        skill_taxonomy_keys=[],
    )
    assert result.contract_type and result.contract_type.contract_type == "contract"
    assert result.work_hours and result.work_hours.pattern == "full_time"
    cues = {cue.cue for cue in result.schedule_cues}
    assert {"shift_work", "on_call"} <= cues
    assert result.travel_required and result.travel_required.level == "frequent"
    kinds = {benefit.kind for benefit in result.benefits}
    assert {"healthcare", "learning"} <= kinds


# ------------------------------------------------------- surfacing (API)


async def test_gates_surface_on_posting_detail(
    client, auth_headers, profile_ready, seeded_catalog, db, source
):
    await client.put(
        "/api/v1/profile",
        json={
            "constraints": {
                "physical_conditions": [],
                "willing_to_relocate": True,
                "shift_tolerance": "none",
            }
        },
        headers=auth_headers,
    )
    posting = await _make_posting(db, source)
    posting.extract_version = EXTRACT_VERSION
    posting.posting_facts = {
        "lifestyle": {
            "schedule_cues": [
                {"cue": "weekends", "evidence_quote": "weekend rotations"}
            ]
        }
    }
    db.add(posting)
    await db.commit()

    detail = (
        await client.get(f"/api/v1/postings/{posting.ref}", headers=auth_headers)
    ).json()
    assert "shift" in (detail["match"]["gates"] or [])

    other = await client.get(
        "/api/v1/postings",
        headers=auth_headers,
    )
    assert other.status_code == 200


async def test_constraint_change_invalidates_cached_gates(
    client, auth_headers, profile_ready, seeded_catalog, db, source
):
    posting = await _make_posting(db, source)
    posting.extract_version = EXTRACT_VERSION
    posting.posting_facts = {
        "lifestyle": {"travel_required": {"level": "frequent", "days_per_month": 15}}
    }
    db.add(posting)
    await db.commit()

    before = (
        await client.get(f"/api/v1/postings/{posting.ref}", headers=auth_headers)
    ).json()["match"]["gates"]
    assert before == []

    await client.put(
        "/api/v1/profile",
        json={
            "constraints": {
                "physical_conditions": [],
                "willing_to_relocate": True,
                "travel_days_per_month": 5,
            }
        },
        headers=auth_headers,
    )
    after = (
        await client.get(f"/api/v1/postings/{posting.ref}", headers=auth_headers)
    ).json()["match"]["gates"]
    assert after == ["travel"]
