"""slice 2 — the feature map: declared bindings, prompt
generation, registry discipline."""

from typing import get_args

from app.ai.agents.posting_extractor import PostingExtract
from app.services.extract_service import FIELD_NAMES
from app.services.feature_map import (
    CONSUMERS,
    FEATURE_MAP,
    PROMPT_FEATURES,
    generated_feature_instructions,
)
from app.services.posting_fit_service import lifestyle_gates


def test_registry_discipline_consumers_are_closed_vocabulary():
    for key, row in FEATURE_MAP.items():
        for consumer in row.consumers:
            assert consumer in CONSUMERS, f"{key} binds unknown consumer {consumer}"


def test_every_feature_key_is_a_posting_extract_field():
    fields = set(PostingExtract.model_fields)
    unknown = set(FEATURE_MAP) - fields
    assert not unknown, f"map rows without schema fields: {sorted(unknown)}"
    unmapped_schema_fields = fields - set(FEATURE_MAP) - {"field_confidence"}
    assert not unmapped_schema_fields, (
        "schema fields without a map row drift from the prompt: "
        f"{sorted(unmapped_schema_fields)}"
    )


def test_gate_rows_match_what_lifestyle_gates_reads():
    gated = {key for key, row in FEATURE_MAP.items() if "fit_gates" in row.consumers}
    assert gated == {
        "work_hours",
        "schedule_cues",
        "travel_required",
    }, "fit_gates bindings must mirror the gate function's inputs exactly"
    assert set(FIELD_NAMES) >= gated, "gated features must be suppressible fields"


def test_generated_prompt_covers_the_whole_extractable_surface():
    instructions = generated_feature_instructions()
    assert instructions.startswith("FEATURES TO EXTRACT")
    for key in PROMPT_FEATURES:
        assert f"- {key}:" in instructions
        assert FEATURE_MAP[key].prompt_hint in instructions
    assert "values_cues" in PROMPT_FEATURES, "informational cue is still extracted"
    for row in FEATURE_MAP.values():
        assert row.extracts == bool(row.prompt_hint)
        if row.inert:
            assert not row.consumers, "inert means stored-but-unconsumed"


def test_v2_evidence_fields_all_prompted():
    for field in (
        "contract_type",
        "work_hours",
        "schedule_cues",
        "travel_required",
        "onsite_policy",
    ):
        assert field in PROMPT_FEATURES
        inner = get_args(PostingExtract.model_fields[field].annotation)[0]
        assert "evidence_quote" in inner.model_fields, (
            f"{field} carries an evidence contract in the schema"
        )


async def test_prompt_is_generated_from_the_map_and_audited(
    db, auth_headers, seeded_catalog
):
    from app.core.security import decode_access_token
    from sqlalchemy import select

    from app.ai.agents.posting_extractor import extract_posting
    from app.models.ai_model import AIGeneration

    token = auth_headers["Authorization"].split(" ", 1)[1]
    user_id = decode_access_token(token)[0]
    await extract_posting(
        db,
        user_id,
        title="Engineer",
        description="Build things. Full-time.",
        skills_raw=[],
        skill_taxonomy_keys=[],
    )
    row = (
        (
            await db.execute(
                select(AIGeneration)
                .where(AIGeneration.task_type == "posting_extract")
                .order_by(AIGeneration.created_at.desc())
                .limit(1)
            )
        )
        .scalars()
        .first()
    )
    assert row is not None
    assert "FEATURES TO EXTRACT" in row.prompt
    assert "- skills:" in row.prompt
    assert "- travel_required:" in row.prompt


async def test_values_cues_stored_inert(
    db, client, auth_headers, seeded_catalog, source
):
    from tests.conftest import _make_posting

    from app.ai.agents.posting_extractor import PostingExtract
    from app.services.extract_service import apply_extract

    posting = await _make_posting(db, source)
    extract = PostingExtract(
        values_cues=["fast-paced environment", "mission-driven"],
        skills=[],
    )
    await apply_extract(db, posting, extract)
    await db.commit()
    await db.refresh(posting)
    assert posting.posting_facts["values_cues"] == [
        "fast-paced environment",
        "mission-driven",
    ]
    assert "values_cues" not in ((posting.posting_facts or {}).get("lifestyle") or {})
    assert lifestyle_gates(posting, {"travel_days_per_month": 0}) == []


async def test_admin_can_read_the_map(client, auth_headers, seeded_catalog):
    response = await client.get(
        "/api/v1/admin/postings/feature-map", headers=auth_headers
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body["consumers"]) == set(CONSUMERS)
    keys = {row["key"] for row in body["features"]}
    assert keys == set(FEATURE_MAP)
    assert get_args(tuple) is not None
    assert "unmapped" in body
