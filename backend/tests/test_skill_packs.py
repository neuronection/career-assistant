"""— agent skill packs: resolution, gateway injection +
audit pinning, bank seeds, API surface."""

from uuid import UUID

from sqlalchemy import select

from tests.conftest import _uid

from app.ai.gateway import ainvoke_structured
from app.models.ai_model import AIGeneration
from app.models.enums import AITaskType
from app.models.skill_pack_model import AISkillPack
from app.schemas.interview import InterviewTurn
from app.seeds.skill_packs import BANK_PACKS, seed_skill_packs


async def test_seed_is_idempotent_and_versioned(
    client, auth_headers, profile_ready, seeded_catalog, db
):
    added = await seed_skill_packs(db)
    assert added == len(BANK_PACKS)
    again = await seed_skill_packs(db)
    assert again == 0

    # Changing a bank pack's instructions bumps the version instead of
    # editing in place (versions are immutable rows, 37 discipline).
    rows = (
        (
            await db.execute(
                select(AISkillPack).where(
                    AISkillPack.author_key == "bank",
                    AISkillPack.key == "interview-prep-style",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1 and rows[0].version == 1
    rows[0].instructions = "Changed — this is now a different edition."
    await db.commit()
    bumped = await seed_skill_packs(db)
    assert bumped == 1
    versions = (
        (
            await db.execute(
                select(AISkillPack.version).where(
                    AISkillPack.author_key == "bank",
                    AISkillPack.key == "interview-prep-style",
                )
            )
        )
        .scalars()
        .all()
    )
    assert sorted(versions) == [1, 2]


async def test_resolution_prefers_latest_published(
    client, auth_headers, profile_ready, seeded_catalog, db
):
    from app.ai.packs import resolve_pack

    assert await seed_skill_packs(db) == len(BANK_PACKS)
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
    client, auth_headers, profile_ready, seeded_catalog, db
):
    """A task WITH a bank pack gets pack_key/pack_version pinned on its
    audit row; a task without one keeps the columns null."""
    await seed_skill_packs(db)
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
                select(AIGeneration).where(
                    AIGeneration.task_type == AITaskType.ASSIST.value
                )
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
    client, auth_headers, profile_ready, seeded_catalog, db
):
    """compose_system overlays the pack onto the code prompt — real
    providers receive it; the mock path (prompt-built) records which
    pack governed via the audit columns instead."""
    from app.ai.packs import compose_system, resolve_pack

    await seed_skill_packs(db)
    pack = await resolve_pack(db, AITaskType.INTERVIEW_TURN.value)
    composed = compose_system("Base system prompt.", pack)
    assert composed.startswith("Base system prompt.")
    assert "SKILL PACK — Interview coaching style guide (v1):" in composed
    assert "STAR" in composed
    assert compose_system("Base system prompt.", None) == "Base system prompt."


async def test_skill_packs_api_lists_published_bank_packs(
    client, auth_headers, profile_ready, seeded_catalog, db
):
    await seed_skill_packs(db)
    response = await client.get("/api/v1/ai/skill-packs", headers=auth_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    keys = {p["key"] for p in body}
    assert keys == {p["key"] for p in BANK_PACKS}
    tasks = {p["task"] for p in body}
    assert AITaskType.INTERVIEW_TURN.value in tasks
