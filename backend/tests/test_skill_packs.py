"""— agent skill packs: resolution, gateway injection +
audit pinning, the reference-bank packs, API surface."""

from uuid import UUID

from sqlalchemy import select

from app.ai.gateway import ainvoke_structured
from app.models.ai_model import AIGeneration
from app.models.enums import AITaskType
from app.models.skill_pack_model import AISkillPack
from app.schemas.interview import InterviewTurn
from app.services.seeds.applier import SeedApplyService
from app.services.seeds.provider_service import ProviderService
from tests.conftest import _uid
from tests.seed_pack_fixture import bank_items


async def _publish_all(db, fixture) -> None:
    service = ProviderService(db, packs=fixture.store)
    for item in bank_items("skill_packs"):
        await service.publish_skill_pack(fixture.source.id, item["seed_key"], actor="test")


async def test_bank_skill_packs_apply_as_drafts_and_a_reapply_is_a_noop(db, fixture_banks):
    rows = (await db.execute(select(AISkillPack))).scalars().all()
    assert len(rows) == len(bank_items("skill_packs"))
    assert {row.status for row in rows} == {"draft"}
    assert {row.version for row in rows} == {1}
    assert {row.author_key for row in rows} == {"bank"}

    again = await SeedApplyService(db, packs=fixture_banks.store, side_effects=False).apply(
        fixture_banks.source, fixture_banks.version
    )
    assert again.status == "noop"


async def test_resolution_prefers_latest_published(
    client, auth_headers, profile_ready, fixture_banks, db
):
    from app.ai.packs import resolve_pack

    await _publish_all(db, fixture_banks)
    pack = await resolve_pack(db, AITaskType.INTERVIEW_TURN.value)
    assert pack is not None
    assert pack.key == "interview-prep-style"
    assert pack.version == 1
    assert await resolve_pack(db, "no_such_task") is None

    db.add(
        AISkillPack(
            key="interview-prep-style",
            version=2,
            title="Interview coaching style guide",
            task=AITaskType.INTERVIEW_TURN.value,
            instructions="v2 instructions",
            status="published",
            author_user_id=None,
            author_key="bank",
            content_hash="x",
        )
    )
    await db.commit()
    pack2 = await resolve_pack(db, AITaskType.INTERVIEW_TURN.value)
    assert pack2.version == 2

    db.add(
        AISkillPack(
            key="interview-prep-style",
            version=3,
            title="Interview coaching style guide",
            task=AITaskType.INTERVIEW_TURN.value,
            instructions="v3 draft",
            status="draft",
            author_user_id=None,
            author_key="bank",
            content_hash="x",
        )
    )
    await db.commit()
    assert (await resolve_pack(db, AITaskType.INTERVIEW_TURN.value)).version == 2


async def test_gateway_pins_pack_on_audit_rows(
    client, auth_headers, profile_ready, fixture_banks, db
):
    """A task WITH a reference pack gets pack_key/pack_version pinned on its
    audit row; a task without one keeps the columns null."""
    await _publish_all(db, fixture_banks)
    user_id = UUID(_uid(auth_headers))

    class Probe(BaseModel := __import__("pydantic").BaseModel):
        answer: str

    await ainvoke_structured(
        db,
        AITaskType.ASSIST,
        Probe,
        "You answer briefly.",
        'TASK: probe\n\nCONTEXT_JSON: {"task": "probe"}',
        user_id,
    )
    await ainvoke_structured(
        db,
        AITaskType.INTERVIEW_TURN,
        InterviewTurn,
        "Coach the answer.",
        'CONTEXT_JSON: {"question": {"id": "q1"}, "answer": "x", '
        '"experience": [], "is_last": true}',
        user_id,
    )

    assist = (
        (
            await db.execute(
                select(AIGeneration).where(AIGeneration.task_type == AITaskType.ASSIST.value)
            )
        )
        .scalars()
        .one()
    )
    assert assist.pack_key is None and assist.pack_version is None

    turn = (
        (
            await db.execute(
                select(AIGeneration).where(
                    AIGeneration.task_type == AITaskType.INTERVIEW_TURN.value
                )
            )
        )
        .scalars()
        .one()
    )
    assert turn.pack_key == "interview-prep-style"
    assert turn.pack_version == 1


async def test_pack_content_reaches_the_model_path(
    client, auth_headers, profile_ready, fixture_banks, db
):
    """compose_system overlays the pack onto the code prompt — real
    providers receive it; the mock path (prompt-built) records which
    pack governed via the audit columns instead."""
    from app.ai.packs import compose_system, resolve_pack

    await _publish_all(db, fixture_banks)
    pack = await resolve_pack(db, AITaskType.INTERVIEW_TURN.value)
    composed = compose_system("Base system prompt.", pack)
    assert composed.startswith("Base system prompt.")
    assert "SKILL PACK — Interview coaching style guide (v1):" in composed
    assert "STAR" in composed
    assert compose_system("Base system prompt.", None) == "Base system prompt."


async def test_skill_packs_api_lists_published_bank_packs(
    client, auth_headers, profile_ready, fixture_banks, db
):
    await _publish_all(db, fixture_banks)
    response = await client.get("/api/v1/ai/skill-packs", headers=auth_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    keys = {p["key"] for p in body}
    assert keys == {p["key"] for p in bank_items("skill_packs")}
    tasks = {p["task"] for p in body}
    assert AITaskType.INTERVIEW_TURN.value in tasks
