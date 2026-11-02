"""Plan 131 — the posting detail view contract: the plain-text
description projection (untrusted connector markup), the enriched
detail payload (facts + timestamps, detail-only description) and the
typed extract envelope with its legacy-benefits coercion."""

from app.models.experience_model import Organization
from app.schemas.posting import PostingExtractOut
from app.services.postings.extract_service import apply_extract
from app.services.postings.text import plain_text
from tests.conftest import _make_posting


def test_plain_text_drops_markup_and_script_content():
    hostile = "<p>We build <b>things</b></p><script>alert(1)</script><style>.x{}</style>"
    assert plain_text(hostile) == "We build things"


def test_plain_text_decodes_entities_and_keeps_block_breaks():
    assert plain_text("<div>Line one &amp; more</div><div>Line&nbsp;two</div>") == (
        "Line one & more\nLine two"
    )
    assert plain_text("<div><br></div>") == ""
    assert plain_text("") == ""


def test_plain_text_caps_length():
    assert len(plain_text("x" * 9000)) == 8000
    assert len(plain_text("x" * 300, limit=100)) == 100


def test_extract_benefits_accept_objects_and_legacy_strings():
    extract = PostingExtractOut.model_validate(
        {
            "skills": [],
            "benefits": [
                {"kind": "healthcare", "raw": "health cover", "confidence": 0.9},
                "old string benefit",
            ],
        }
    )
    typed, legacy = extract.benefits
    assert (typed.kind, typed.raw, typed.confidence) == ("healthcare", "health cover", 0.9)
    assert (legacy.kind, legacy.raw, legacy.confidence) == ("other", "old string benefit", 0.5)


def test_extract_envelope_types_the_lifestyle_objects():
    extract = PostingExtractOut.model_validate(
        {
            "skills": [],
            "contract_type": {
                "contract_type": "permanent",
                "evidence_quote": "permanent role",
                "confidence": 0.8,
            },
            "work_hours": {
                "pattern": "full_time",
                "hours_per_week_min": 40,
                "hours_per_week_max": 42,
                "evidence_quote": "40-42h",
                "confidence": 0.7,
            },
            "schedule_cues": [
                {"cue": "shift_work", "evidence_quote": "two shifts", "confidence": 0.6}
            ],
            "travel_required": {
                "level": "occasional",
                "days_per_month": 2,
                "evidence_quote": "some travel",
                "confidence": 0.5,
            },
            "onsite_policy": {
                "policy": "hybrid",
                "office_days_per_week": 2,
                "evidence_quote": "2 days office",
                "confidence": 0.9,
            },
            "values_cues": ["team spirit"],
        }
    )
    assert extract.contract_type.contract_type == "permanent"
    assert extract.work_hours.hours_per_week_max == 42
    assert [cue.cue for cue in extract.schedule_cues] == ["shift_work"]
    assert extract.travel_required.days_per_month == 2
    assert extract.onsite_policy.office_days_per_week == 2
    assert extract.values_cues == ["team spirit"]


def test_extract_lists_coerce_suppressed_nulls():
    extract = PostingExtractOut.model_validate(
        {
            "skills": None,
            "languages": None,
            "benefits": None,
            "responsibilities": None,
            "prerequisites": None,
            "schedule_cues": None,
            "values_cues": None,
            "field_confidence": None,
        }
    )
    assert extract.skills == []
    assert extract.languages == []
    assert extract.benefits == []
    assert extract.responsibilities == []
    assert extract.prerequisites == []
    assert extract.schedule_cues == []
    assert extract.values_cues == []
    assert extract.field_confidence == {}


async def test_detail_survives_suppressed_extract_fields(
    db, client, auth_headers, profile_ready, seeded_catalog, source, kinds
):
    """`apply_extract` suppresses low-confidence fields to null in the
    stored extract — the wire envelope reads them as empty instead of
    failing the whole posting (the live 500 on every extracted row)."""
    from app.ai.agents.posting_extractor import PostingExtract

    posting = await _make_posting(db, source)
    await apply_extract(
        db,
        posting,
        PostingExtract(
            skills=[],
            field_confidence={
                "languages": 0.1,
                "benefits": 0.1,
                "responsibilities": 0.1,
                "schedule_cues": 0.1,
            },
        ),
    )
    await db.commit()
    await db.refresh(posting)
    assert posting.extract["languages"] is None

    response = await client.get(f"/api/v1/postings/{posting.id}", headers=auth_headers)
    assert response.status_code == 200, response.text
    extract = response.json()["extract"]
    assert extract["languages"] == []
    assert extract["benefits"] == []
    assert extract["responsibilities"] == []
    assert extract["schedule_cues"] == []
    assert set(extract["_suppressed_fields"]) == {
        "languages",
        "benefits",
        "responsibilities",
        "schedule_cues",
    }


async def test_detail_returns_description_facts_and_timestamps(
    db, client, auth_headers, profile_ready, seeded_catalog, source, kinds
):
    org = Organization(key="detailco", name="DetailCo", status="active")
    db.add(org)
    await db.flush()
    posting = await _make_posting(
        db,
        source,
        raw={"description": "<p>We need <b>programming</b>.</p><script>x()</script>"},
    )
    posting.org_id = org.id
    posting.contract_type = "permanent"
    posting.work_hours = "full_time"
    posting.hours_per_week_min = 40
    posting.hours_per_week_max = 42
    posting.travel_class = "occasional"
    posting.education_level = "bachelor"
    await db.commit()

    response = await client.get(f"/api/v1/postings/{posting.ref}", headers=auth_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["description"] == "We need programming."
    assert body["org_key"] == "detailco"
    assert body["contract_type"] == "permanent"
    assert body["work_hours"] == "full_time"
    assert body["hours_per_week_min"] == 40
    assert body["hours_per_week_max"] == 42
    assert body["travel_class"] == "occasional"
    assert body["education_level"] == "bachelor"
    assert body["created_at"] is not None
    assert body["updated_at"] is not None


async def test_detail_source_title_prefers_the_source_display_name(
    db, client, auth_headers, profile_ready, seeded_catalog, source, kinds
):
    """Plan 173: an imported source's manifest display name wins over the
    connector class title; a NULL title keeps the connector title."""
    posting = await _make_posting(db, source)
    source.title = "LinkedIn"
    await db.commit()

    response = await client.get(f"/api/v1/postings/{posting.ref}", headers=auth_headers)
    assert response.status_code == 200, response.text
    assert response.json()["source_title"] == "LinkedIn"

    source.title = None
    await db.commit()
    response = await client.get(f"/api/v1/postings/{posting.ref}", headers=auth_headers)
    assert response.status_code == 200, response.text
    assert response.json()["source_title"] == "Synthetic test connector"


async def test_detail_typed_benefits_survive_the_wire(
    db, client, auth_headers, profile_ready, seeded_catalog, source, kinds
):
    posting = await _make_posting(db, source)
    posting.extract = {
        "skills": [],
        "benefits": [
            {"kind": "healthcare", "raw": "health cover", "confidence": 0.9},
            "legacy plain string",
        ],
        "field_confidence": {},
    }
    posting.extract_version = 2
    await db.commit()

    response = await client.get(f"/api/v1/postings/{posting.id}", headers=auth_headers)
    assert response.status_code == 200, response.text
    benefits = response.json()["extract"]["benefits"]
    assert benefits == [
        {"kind": "healthcare", "raw": "health cover", "confidence": 0.9},
        {"kind": "other", "raw": "legacy plain string", "confidence": 0.5},
    ]


async def test_list_payload_omits_description(
    db, client, auth_headers, profile_ready, seeded_catalog, source, kinds
):
    posting = await _make_posting(db, source)
    listing = await client.get("/api/v1/postings", headers=auth_headers)
    assert listing.status_code == 200, listing.text
    items = listing.json()["items"]
    row = next(item for item in items if item["id"] == str(posting.id))
    assert "description" not in row
    assert row["created_at"] is not None
    detail = await client.get(f"/api/v1/postings/{posting.ref}", headers=auth_headers)
    assert "description" in detail.json()
