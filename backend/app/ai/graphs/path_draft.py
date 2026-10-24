"""Chat career-path draft flow — a checkpointed LangGraph StateGraph.

``resolve_target`` (deterministic) grounds the request against the
published catalog through the same ``search_jobs`` tool the model uses;
``propose_missing`` (only when nothing matched) drafts ONE missing job
through the existing ``job_generate`` agent and parks it in the catalog
moderation queue as ``status=draft`` — never an active job;
``draft_path`` (LLM, audited) writes the structured route draft; and
``finalize`` assembles the review payload. Nothing here mutates a user's
paths: the draft rides the turn metadata and becomes a path only when
the user reviews and saves it (review-first law).

Checkpointer: thread_id = ``path_draft:{user_id}`` per ADR-0008; the
flow is one-shot with no mid-flow interrupts.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

MAX_CANDIDATES = 5

MATCH_NOTE = (
    "Grounded against the published catalog; the draft references the matched destination job."
)
PROPOSED_NOTE = (
    "No catalog job matched, so a missing-job draft was proposed through "
    "the catalog moderation queue — it becomes visible once a curator "
    "approves it."
)


class PathDraftState(TypedDict, total=False):
    """JSON-safe flow state (the checkpointer serializes this)."""

    request: str
    user_id: str
    candidates: list[dict]
    target_job: dict | None
    proposed_job: dict | None
    draft: dict | None
    note: str
    error: str
    payload: dict


def build_path_draft_graph(db: AsyncSession, checkpointer: Any | None = None):
    """Compile resolve_target → propose_missing → draft_path → finalize."""
    from app.ai.agents.chatbot import search_jobs_tool
    from app.ai.agents.job_generator import generate_jobs
    from app.ai.agents.path_drafter import draft_chat_path
    from app.schemas.job import JobCreate, JobSkillIn
    from app.services.catalog.job_service import JobService
    from app.services.catalog.taxonomy_service import TaxonomyService

    async def resolve_target(state: PathDraftState) -> dict:
        request = state["request"]
        try:
            rows = await search_jobs_tool(db, request, limit=MAX_CANDIDATES)
        except Exception:
            logger.warning("path_draft: search grounding failed", exc_info=True)
            rows = []
        candidates = [
            {
                "code": row.get("code"),
                "title": row.get("title"),
                "family": row.get("family") or row.get("family_key") or "",
            }
            for row in rows
            if isinstance(row, dict) and row.get("code")
        ]
        target = candidates[0] if candidates else None
        return {"candidates": candidates, "target_job": target}

    async def propose_missing(state: PathDraftState) -> dict:
        if state.get("target_job") is not None:
            return {}
        request = state["request"]
        user_id = uuid.UUID(state["user_id"])
        job_service = JobService(db)
        try:
            families = await job_service.families()
            skill_keys = [skill.key for skill in await TaxonomyService(db).skills(status="active")]
            draft_set = await generate_jobs(
                db,
                user_id,
                mode="prompt",
                prompt=request,
                count=1,
                family_keys=[family.key for family in families],
                skill_keys=skill_keys,
            )
            job_draft = draft_set.drafts[0]
        except Exception:
            logger.warning("path_draft: missing-job proposal failed", exc_info=True)
            return {
                "note": (
                    "No catalog job matched and the missing-job proposal "
                    "failed — try naming the job you have in mind."
                )
            }
        from app.models.user_model import User

        user = (await db.execute(select(User).where(User.id == user_id))).scalars().first()
        family_by_key = {family.key: family for family in families}
        if job_draft.family_key not in family_by_key:
            return {"note": "The proposed job named an unknown family — nothing was created."}

        job = await JobService(db).create(
            JobCreate(
                code=job_draft.code,
                title=job_draft.title,
                family_key=job_draft.family_key,
                short_description=job_draft.short_description,
                interest_keys=job_draft.interest_keys,
                skills=[
                    JobSkillIn(skill_key=link.skill_key, importance=link.importance)
                    for link in job_draft.skills
                ],
            ),
            user,
            source="ai",
            status="draft",
        )
        return {
            "proposed_job": {
                "code": job.code,
                "title": job.title,
                "status": job.status,
            },
            "target_job": {"code": job.code, "title": job.title, "family": job_draft.family_key},
            "note": PROPOSED_NOTE,
        }

    async def draft_path(state: PathDraftState) -> dict:
        target = state.get("target_job")
        if target is None:
            return {}
        user_id = uuid.UUID(state["user_id"])
        job_service = JobService(db)
        job = await job_service.get_by_code_or_id(target["code"])
        if job is None:
            return {"error": "the resolved job disappeared — try again"}
        from app.models.enums import LabelEntityKind
        from app.models.user_model import User
        from app.services.catalog.label_overlay_service import LabelOverlayService
        from app.services.locale_service import effective_locale

        owner = (await db.execute(select(User).where(User.id == user_id))).scalars().first()
        title = job.title
        if owner is not None:
            overlay = await LabelOverlayService(db).resolve_one(
                LabelEntityKind.JOB, job.id, "label", job.title, await effective_locale(db, owner)
            )
            title = overlay or title
        try:
            draft = await draft_chat_path(
                db,
                user_id,
                request=state["request"],
                job_snapshot=JobService.job_snapshot(job) | {"title": title},
                family_keys=[family.key for family in await job_service.families()],
                skill_keys=[
                    skill.key for skill in await TaxonomyService(db).skills(status="active")
                ],
            )
        except Exception:
            logger.warning("path_draft: drafting failed", exc_info=True)
            return {"error": "the draft step failed — try again in a moment"}
        return {
            "draft": {
                "title": draft.title,
                "description": draft.description,
                "steps": [step.model_dump(mode="json") for step in draft.steps],
                "job_code": job.code,
                "job_title": title,
            },
            "note": state.get("note") or MATCH_NOTE,
        }

    def route_after_missing(state: PathDraftState) -> str:
        if state.get("draft") is not None:
            return "finalize"
        return "draft_path"

    async def finalize(state: PathDraftState) -> dict:
        payload: dict = {
            "draft": state.get("draft"),
            "candidates": state.get("candidates") or [],
            "proposed_job": state.get("proposed_job"),
            "note": state.get("note") or "",
        }
        if state.get("error"):
            payload["error"] = state["error"]
        return {"payload": payload}

    builder = StateGraph(PathDraftState)
    builder.add_node("resolve_target", resolve_target)
    builder.add_node("propose_missing", propose_missing)
    builder.add_node("draft_path", draft_path)
    builder.add_node("finalize", finalize)
    builder.add_edge(START, "resolve_target")
    builder.add_edge("resolve_target", "propose_missing")
    builder.add_conditional_edges(
        "propose_missing",
        route_after_missing,
        {"draft_path": "draft_path", "finalize": "finalize"},
    )
    builder.add_edge("draft_path", "finalize")
    builder.add_edge("finalize", END)
    return builder.compile(checkpointer=checkpointer)


async def run_path_draft_flow(
    db: AsyncSession,
    user_id: uuid.UUID,
    request: str,
    *,
    checkpointer: Any | None = None,
) -> dict:
    """One-shot draft flow run (tool entry point); returns the review
    payload — a draft, never an active path. Tests pass an
    ``InMemorySaver``; production resolves the app checkpointer."""
    from app.ai.checkpointer import get_checkpointer

    graph = build_path_draft_graph(db, checkpointer or await get_checkpointer())
    config = {"configurable": {"thread_id": f"path_draft:{user_id}"}}
    final = await graph.ainvoke({"request": request, "user_id": str(user_id)}, config=config)
    return final.get("payload") or {
        "draft": None,
        "candidates": [],
        "proposed_job": None,
        "note": "No draft was produced — try naming the job you have in mind.",
    }
