"""The chat career-path draft flow (plan 125.4): grounded search →
missing-job proposal through the moderation queue → review-first draft.

The flow never creates a CareerPath row — the draft becomes a path only
through the user's explicit save on the /paths surface."""

from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import select

from app.ai.graphs.path_draft import build_path_draft_graph, run_path_draft_flow
from app.ai.tools import run_tool
from app.models.career_path_model import CareerPath
from app.models.enums import PathSource, PathStatus
from app.models.job_model import Job


def _graph(db):
    return build_path_draft_graph(db, InMemorySaver())


async def test_flow_grounds_a_catalog_match_and_drafts(client, db, auth_headers, seeded_catalog):
    from tests.conftest import user_id_from_headers

    result = await run_path_draft_flow(
        db,
        user_id_from_headers(auth_headers),
        "software developer",
        checkpointer=InMemorySaver(),
    )
    assert result["draft"] is not None
    draft = result["draft"]
    assert draft["job_code"] == "software-developer"
    assert len(draft["steps"]) >= 2
    kinds = {step["kind"] for step in draft["steps"]}
    assert kinds <= {"education", "job", "experience", "certification"}
    assert "moderation" not in result["note"]
    assert (
        not (await db.execute(select(CareerPath).where(CareerPath.source == PathSource.USER.value)))
        .scalars()
        .first()
    ), "the flow drafts; it never writes a user path"


async def test_flow_proposes_missing_job_through_moderation_queue(
    client, db, auth_headers, seeded_catalog
):
    from tests.conftest import user_id_from_headers

    result = await run_path_draft_flow(
        db,
        user_id_from_headers(auth_headers),
        "underwater basket weaver consultant",
        checkpointer=InMemorySaver(),
    )
    assert result["proposed_job"] is not None
    proposed = result["proposed_job"]
    row = (await db.execute(select(Job).where(Job.code == proposed["code"]))).scalars().first()
    assert row is not None
    assert row.status == PathStatus.DRAFT.value
    assert row.source == PathSource.AI.value
    assert result["draft"] is not None
    assert result["draft"]["job_code"] == proposed["code"]
    assert (
        not (await db.execute(select(CareerPath).where(CareerPath.source == PathSource.USER.value)))
        .scalars()
        .first()
    ), "the proposed job must not auto-create a path"


async def test_proposed_job_sits_in_the_admin_moderation_queue(
    client, db, auth_headers, seeded_catalog
):
    from tests.conftest import user_id_from_headers

    result = await run_path_draft_flow(
        db,
        user_id_from_headers(auth_headers),
        "quantum yoga instructor",
        checkpointer=InMemorySaver(),
    )
    code = result["proposed_job"]["code"]
    queue = (await client.get("/api/v1/admin/jobs?status=draft", headers=auth_headers)).json()
    assert any(job["code"] == code for job in queue)


async def test_create_career_path_tool_returns_the_review_draft(
    client, db, auth_headers, seeded_catalog
):
    from tests.conftest import user_id_from_headers

    result = await run_tool(
        db,
        "create_career_path",
        user_id_from_headers(auth_headers),
        {"request": "software developer"},
    )
    assert "error" not in result
    assert result["path_draft"] is not None
    assert result["path_draft"]["title"]
    assert result["note"]


async def test_my_paths_tool_lists_own_and_curated(client, db, auth_headers, seeded_catalog):
    from tests.conftest import user_id_from_headers

    path = CareerPath(
        job_id=(await db.execute(select(Job))).scalars().first().id,
        title="Mine only",
        source=PathSource.USER.value,
        status=PathStatus.ACTIVE.value,
    )
    db.add(path)
    await db.flush()
    from app.models.career_path_model import UserPathFlag

    db.add(
        UserPathFlag(
            user_id=user_id_from_headers(auth_headers),
            path_id=path.id,
            step_id=None,
            flag="pinned",
        )
    )
    await db.commit()
    result = await run_tool(db, "my_paths", user_id_from_headers(auth_headers), {})
    assert any(row["title"] == "Mine only" for row in result["my_paths"])
    assert result["curated_paths"]
