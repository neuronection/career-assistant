"""Plan 69.1: synth-aware generation — the `collect` reuse stage applies
the prefer-mode overlay before drafting, the run result + version trace
record `synth_applied`, and off mode stays byte-compat.

Service parity: `match_for_user` / `apply_to_items` (the generation
entry points) follow the same deterministic precedence as their `cv`-
taking wrappers, including the posting-scoped > generic rule.
"""

import uuid
from datetime import date
from uuid import UUID

from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import select

from app.models.cv_model import CvDocument, CvVersion
from app.schemas.cv_generate import CvGenerateRequest
from app.services.cv_generate_service import CvGenerateService
from app.services.cv_synth_service import CvSynthService

from tests.conftest import _uid


async def _make_item(
    db, headers, description: str = "Built QA tooling", *, kind: str = "internship"
):
    from app.models.experience_model import ExperienceItem

    item = ExperienceItem(
        user_id=UUID(_uid(headers)),
        kind=kind,
        title="Backend Intern",
        org_name="Sample Corp",
        start=date(2024, 6, 1),
        end=date(2024, 9, 1),
        description=description,
        status="active",
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


async def _active_variant(client, auth_headers, db, item):
    row = (
        await client.post(
            "/api/v1/cv/synth/generate",
            json={
                "refs": [{"source_key": "experience", "item_id": str(item.id)}],
                "action": "summarize",
            },
            headers=auth_headers,
        )
    ).json()["items"][0]
    await client.patch(
        f"/api/v1/cv/synth/{row['id']}",
        json={"status": "active"},
        headers=auth_headers,
    )
    return row


async def _generate(db, headers, *, synth_mode="off", target_posting_id=None):
    service = CvGenerateService(db, checkpointer=InMemorySaver())
    result = await service.generate(
        UUID(_uid(headers)),
        CvGenerateRequest(
            language="en",
            target_posting_id=target_posting_id,
            context={
                "mode": "all",
                "include": [],
                "exclude": [],
                "synth_mode": synth_mode,
            },
        ),
        run_id=uuid.uuid4(),
    )
    await db.commit()
    return result


async def _last_version(db, cv_id) -> CvVersion:
    return (
        (
            await db.execute(
                select(CvVersion)
                .where(CvVersion.cv_document_id == cv_id)
                .order_by(CvVersion.version.desc())
            )
        )
        .scalars()
        .first()
    )


async def test_prefer_mode_reuses_active_variant(
    client, auth_headers, profile_ready, seeded_catalog, db
):
    item = await _make_item(db, auth_headers)
    variant = await _active_variant(client, auth_headers, db, item)
    result = await _generate(db, auth_headers, synth_mode="prefer")
    assert result["status"] == "completed", result
    ref_key = f"experience:{item.id}"
    assert result["synth_applied"].get(ref_key) == variant["id"], result
    assert result["synth_proposed"] == []

    cv = await db.get(CvDocument, UUID(result["cv_id"]))
    assert cv.context["synth_mode"] == "prefer", "prefer mode is sticky"
    override = cv.working_content["overrides"].get(ref_key) or {}
    assert override.get("description") == variant["payload"]["description"], (
        "the draft grounds on the variant text, not the profile text"
    )
    assert override.get("description") != "Built QA tooling"

    trace = (await _last_version(db, cv.id)).context_resolution or {}
    assert trace.get("synth_applied", {}).get(ref_key), (
        "the ai_apply compile records the reuse in context_resolution"
    )


async def test_off_mode_ignores_variant(
    client, auth_headers, profile_ready, seeded_catalog, db
):
    item = await _make_item(db, auth_headers)
    await _active_variant(client, auth_headers, db, item)
    result = await _generate(db, auth_headers, synth_mode="off")
    assert result["status"] == "completed"
    assert result["synth_applied"] == {}
    cv = await db.get(CvDocument, UUID(result["cv_id"]))
    override = cv.working_content["overrides"].get(f"experience:{item.id}") or {}
    assert override.get("description") == "Built QA tooling", (
        "off mode drafts from verbatim profile text"
    )


async def test_match_for_user_parity_with_match_for_cv(client, db, auth_headers):
    item = await _make_item(db, auth_headers)
    variant = await _active_variant(client, auth_headers, db, item)
    uid = UUID(_uid(auth_headers))
    service = CvSynthService(db)
    refs = [("experience", str(item.id))]

    by_cv = await service.match_for_cv(
        type(
            "CvShim",
            (),
            {
                "user_id": uid,
                "language": "en",
                "target_posting_id": None,
            },
        )(),
        refs=refs,
    )
    by_user = await service.match_for_user(uid, "en", None, refs=refs)
    assert set(by_user) == set(by_cv), "generation entry point matches builder"
    assert by_user[refs[0]].id == UUID(variant["id"])

    assert await service.match_for_user(uid, "de", None, refs=refs) == {}, (
        "language must equal the match context"
    )

    other_posting = uuid.uuid4()
    scoped = await service.match_for_user(uid, "en", other_posting, refs=refs)
    assert set(scoped) == set(by_user), "generic rows apply to any posting"


async def test_apply_to_items_returns_empty_outside_prefer(client, db, auth_headers):
    item = await _make_item(db, auth_headers)
    await _active_variant(client, auth_headers, db, item)
    from app.services.cv_context_service import resolve

    uid = UUID(_uid(auth_headers))
    from app.schemas.cv import CvContextSelection

    resolution = await resolve(db, uid, CvContextSelection())
    service = CvSynthService(db)
    assert await service.apply_to_items(uid, "en", None, resolution, "off") == {}
    description = await service.apply_to_items(uid, "en", None, resolution, "prefer")
    assert f"experience:{item.id}" in description


# ------------------------------------------------------------ 69.2 proposals


def _structure_for(item_id: str, extra_proposals: list[dict] | None = None) -> dict:
    return {
        "sections": [
            {"kind": "summary", "rationale": ""},
            {"kind": "experience", "item_ids": [item_id], "rationale": ""},
        ],
        "synth_proposals": [
            {"source_key": "experience", "item_id": item_id, "action": "restyle"},
            *(extra_proposals or []),
        ],
    }


async def _generate_with_plan(
    db, auth_headers, monkeypatch, structure: dict, *, synth_mode: str = "off"
):
    import app.ai.graphs.cv_draft as graph_module
    from app.ai.schemas import CvDraftStructure

    async def planned(*args, **kwargs):
        return CvDraftStructure.model_validate(structure)

    monkeypatch.setattr(graph_module, "plan_structure", planned)
    return await _generate(db, auth_headers, synth_mode=synth_mode)


async def test_plan_proposals_ground_gap_variants(
    client, auth_headers, profile_ready, seeded_catalog, db, monkeypatch
):
    from app.models.ai_model import AIGeneration
    from app.models.cv_synth_model import CvSynthItem

    item = await _make_item(db, auth_headers)
    result = await _generate_with_plan(
        db, auth_headers, monkeypatch, _structure_for(str(item.id))
    )
    assert result["status"] == "completed", result
    assert len(result["synth_proposed"]) == 1
    record = result["synth_proposed"][0]
    assert record["source_key"] == "experience"
    assert record["item_id"] == str(item.id)
    assert record["action"] == "restyle"

    variant = await db.get(CvSynthItem, UUID(record["synth_item_id"]))
    assert variant is not None
    assert variant.status == "draft", "draft-then-approve is preserved"

    cv = await db.get(CvDocument, UUID(result["cv_id"]))
    override = cv.working_content["overrides"].get(f"experience:{item.id}") or {}
    assert override.get("description") == variant.payload["description"], (
        "the draft grounds on the gap variant's text"
    )
    audited = (
        (
            await db.execute(
                select(AIGeneration).where(AIGeneration.task_type == "cv_synth")
            )
        )
        .scalars()
        .all()
    )
    assert audited, "the gap grounding is audited under CV_SYNTH"
    assert all(row.run_id is not None for row in audited)


async def test_proposal_clamps_drop_ungroundable_rows(
    client, auth_headers, profile_ready, seeded_catalog, db, monkeypatch
):
    item = await _make_item(db, auth_headers)
    extra = await _make_item(db, auth_headers, description="Second role")
    result = await _generate_with_plan(
        db,
        auth_headers,
        monkeypatch,
        _structure_for(
            str(item.id),
            extra_proposals=[
                {
                    "source_key": "experience",
                    "item_id": str(extra.id),
                    "action": "posting_fit",
                },
                {"source_key": "skills", "item_id": "s1", "action": "detail"},
                {"source_key": "experience", "item_id": "ghost", "action": "detail"},
            ],
        ),
    )
    assert result["status"] == "completed"
    assert [(row["item_id"], row["action"]) for row in result["synth_proposed"]] == [
        (str(item.id), "restyle")
    ], "posting_fit needs a saved posting; skills/ghost/bad action are dropped"


async def test_proposal_failure_falls_back_to_source_text(
    client, auth_headers, profile_ready, seeded_catalog, db, monkeypatch
):
    from app.services.cv_synth_service import CvSynthService

    item = await _make_item(db, auth_headers)

    async def broken(*args, **kwargs):
        raise RuntimeError("synth provider down")

    monkeypatch.setattr(CvSynthService, "generate", broken)
    result = await _generate_with_plan(
        db, auth_headers, monkeypatch, _structure_for(str(item.id))
    )
    assert result["status"] == "completed"
    assert result["synth_proposed"] == []
    assert any("Variant grounding skipped" in warning for warning in result["warnings"])
    cv = await db.get(CvDocument, UUID(result["cv_id"]))
    override = cv.working_content["overrides"].get(f"experience:{item.id}") or {}
    assert override.get("description") == "Built QA tooling", (
        "failed grounding keeps the profile text"
    )


# ------------------------------------------------- 69.2 clamp rules (unit)


def _unit_state(*, applied: dict | None = None) -> dict:
    return {
        "request": {},
        "plan": {"sections": [{"kind": "experience", "item_ids": ["i-1", "i-2"]}]},
        "context": {
            "available": ["experience"],
            "items": [
                {
                    "item_id": "i-1",
                    "source_key": "experience",
                    "payload": {"description": "Built things"},
                },
                {
                    "item_id": "i-2",
                    "source_key": "experience",
                    "payload": {"description": "More things"},
                },
            ],
        },
        "synth_applied": applied or {},
    }


def _unit_proposals(*rows):
    from app.ai.schemas import CvDraftStructure

    return CvDraftStructure.model_validate(
        {
            "sections": [{"kind": "experience", "item_ids": ["i-1", "i-2"]}],
            "synth_proposals": rows,
        }
    )


def test_clamp_proposals_rules_unit():
    from app.ai.graphs.cv_draft import _clamp_proposals

    class _FakeProposal:
        def __init__(self, source_key, item_id, action):
            self.source_key = source_key
            self.item_id = item_id
            self.action = action

    class _FakeStructure:
        def __init__(self, rows):
            self.synth_proposals = rows

    def proposal(item_id, action="restyle", source_key="experience"):
        return _FakeProposal(source_key=source_key, item_id=item_id, action=action)

    clamped = _clamp_proposals(
        _FakeStructure(
            [
                proposal("i-1"),
                proposal("i-2", action="explode"),
                proposal("ghost"),
                proposal("i-2", action="detail"),
                proposal("i-1", action="detail"),
                proposal("s1", source_key="skills"),
            ]
        ),
        _unit_state(),
    )
    assert [(entry["item_id"], entry["action"]) for entry in clamped] == [
        ("i-1", "restyle"),
        ("i-2", "detail"),
    ], "deduped per ref, planned + description-bearing items only"

    assert (
        _clamp_proposals(
            _FakeStructure([proposal("i-1", action="posting_fit")]),
            _unit_state(),
            plan={"sections": [{"kind": "experience", "item_ids": ["i-1"]}]},
        )
        == []
    ), "posting_fit needs a saved target posting"

    applied = {"experience:i-1": "variant-id"}
    clamped_applied = _clamp_proposals(
        _FakeStructure([proposal("i-1"), proposal("i-2")]),
        _unit_state(applied=applied),
        plan={"sections": [{"kind": "experience", "item_ids": ["i-1", "i-2"]}]},
    )
    assert [entry["item_id"] for entry in clamped_applied] == ["i-2"], (
        "refs already reused from the library are never re-tailored"
    )

    clamped_budget = _clamp_proposals(
        _FakeStructure([proposal(f"i-{n}") for n in range(1, 6)]),
        {
            **_unit_state(),
            "context": {
                "available": ["experience"],
                "items": [
                    {
                        "item_id": f"i-{n}",
                        "source_key": "experience",
                        "payload": {"description": f"Role {n}"},
                    }
                    for n in range(1, 6)
                ],
            },
            "plan": {
                "sections": [
                    {"kind": "experience", "item_ids": [f"i-{n}" for n in range(1, 6)]}
                ]
            },
        },
    )
    assert len(clamped_budget) == 3, "proposals are bounded per run (MAX=3)"


# ------------------------------------------------------------ 70 source split


async def test_generate_splits_experience_family_into_three_sections(
    client, auth_headers, profile_ready, seeded_catalog, db
):
    """Plan 70: jobs/internships/freelance, projects and volunteering each
    get their own items block with their own source key."""
    work = await _make_item(db, auth_headers, kind="internship")
    project = await _make_item(
        db, auth_headers, kind="project", description="Shipped a campus app"
    )
    volunteer = await _make_item(
        db, auth_headers, kind="volunteer", description="Organized food drives"
    )
    result = await _generate(db, auth_headers)
    assert result["status"] == "completed", result

    cv = await db.get(CvDocument, UUID(result["cv_id"]))
    blocks = cv.working_content["blocks"]
    items_blocks = [block for block in blocks if block.get("kind") == "items"]
    by_source = {block["props"]["source_key"]: block["props"] for block in items_blocks}
    assert by_source["experience"]["title"] == "Work Experience"
    assert by_source["projects"]["title"] == "Projects"
    assert by_source["volunteer"]["title"] == "Volunteering"

    overrides = cv.working_content["overrides"]
    assert f"experience:{work.id}" in overrides
    assert f"projects:{project.id}" in overrides
    assert f"volunteer:{volunteer.id}" in overrides


async def test_generate_sections_request_can_drop_the_split(
    client, auth_headers, profile_ready, seeded_catalog, db
):
    work = await _make_item(db, auth_headers, kind="internship")
    project = await _make_item(
        db, auth_headers, kind="project", description="Shipped a campus app"
    )
    service = CvGenerateService(db, checkpointer=InMemorySaver())
    result = await service.generate(
        UUID(_uid(auth_headers)),
        CvGenerateRequest(
            language="en",
            sections=["experience", "summary"],
            context={"mode": "all", "include": [], "exclude": []},
        ),
        run_id=uuid.uuid4(),
    )
    await db.commit()
    assert result["status"] == "completed", result
    cv = await db.get(CvDocument, UUID(result["cv_id"]))
    sources = {
        block["props"]["source_key"]
        for block in cv.working_content["blocks"]
        if block.get("kind") == "items"
    }
    assert sources == {"experience"}
    overrides = cv.working_content["overrides"]
    assert f"experience:{work.id}" in overrides
    assert f"projects:{project.id}" not in overrides


async def test_synth_reuse_matches_rekeyed_project_items(
    client, auth_headers, profile_ready, seeded_catalog, db
):
    """Variants keyed on the post-split source key apply during generate."""
    project = await _make_item(
        db, auth_headers, kind="project", description="Shipped a campus app"
    )
    row = (
        await client.post(
            "/api/v1/cv/synth/generate",
            json={
                "refs": [{"source_key": "projects", "item_id": str(project.id)}],
                "action": "summarize",
            },
            headers=auth_headers,
        )
    ).json()["items"][0]
    await client.patch(
        f"/api/v1/cv/synth/{row['id']}",
        json={"status": "active"},
        headers=auth_headers,
    )
    result = await _generate(db, auth_headers, synth_mode="prefer")
    assert result["status"] == "completed", result
    assert result["synth_applied"].get(f"projects:{project.id}") == row["id"], result
    cv = await db.get(CvDocument, UUID(result["cv_id"]))
    override = cv.working_content["overrides"].get(f"projects:{project.id}") or {}
    assert override.get("description") == row["payload"]["description"]


async def test_sections_max_length_accepts_ten_kinds():
    import pytest
    from pydantic import ValidationError

    from app.schemas.cv_generate import GENERATABLE_KINDS

    assert CvGenerateRequest(sections=list(GENERATABLE_KINDS))
    with pytest.raises(ValidationError):
        CvGenerateRequest(sections=["summary"] * 11)
