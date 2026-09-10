"""Built-in tools — the/32 chat tools, registered.

The implementations stay in ``app.ai.agents.chatbot`` (single source);
this module wraps them as registry objects so the chatbot, and later
autopilot/MCP, execute them through ``run_tool``.
"""

from pydantic import BaseModel, Field

from app.ai.tools.base import AITool, ToolContext, ToolScope


class SearchJobsInput(BaseModel):
    """Keyword search over the published catalog."""

    query: str = Field(min_length=1)
    limit: int = Field(default=8, ge=1, le=25)


class SearchPostingsInput(BaseModel):
    """Open-vacancy search over the explore vocabulary."""

    query: str = ""
    filters: dict = Field(default_factory=dict)
    n: int = Field(default=5, ge=1, le=25)


class PostingRefInput(BaseModel):
    """A short posting reference (8-char Crockford token)."""

    ref: str = Field(min_length=1)


class NotificationActionInput(BaseModel):
    """Inbox summary request or conversational mute request."""

    message: str = Field(min_length=1)


class AutopilotGoalRefInput(BaseModel):
    """A goal id (run) or empty summary request."""

    ref: str = Field(default="", max_length=64)


class CompareJobsInput(BaseModel):
    """2-4 catalog jobs (ids or code slugs) to put side by side."""

    refs: list[str] = Field(min_length=2, max_length=4)


async def _search_jobs(db, ctx: ToolContext, args: SearchJobsInput):
    from app.ai.agents.chatbot import search_jobs_tool

    return await search_jobs_tool(db, args.query, limit=args.limit)


async def _search_postings(db, ctx: ToolContext, args: SearchPostingsInput):
    from app.ai.agents.chatbot import search_postings_tool

    return await search_postings_tool(
        db, ctx.user_id, args.query, args.filters, n=args.n
    )


async def _get_posting(db, ctx: ToolContext, args: PostingRefInput):
    from app.ai.agents.chatbot import get_posting_tool

    return await get_posting_tool(db, args.ref)


async def _similar_postings(db, ctx: ToolContext, args: PostingRefInput):
    from app.ai.agents.chatbot import similar_postings_tool

    return await similar_postings_tool(db, args.ref)


async def _my_notifications(db, ctx: ToolContext, args: NotificationActionInput):
    from app.ai.agents.chatbot import my_notifications_tool

    return await my_notifications_tool(db, ctx.user_id, args.message)


async def _run_autopilot(db, ctx: ToolContext, args: AutopilotGoalRefInput):
    """On-demand run of one of the caller's goals (findings only — never
    an application; applying stays a user click)."""
    from uuid import UUID

    from app.services.autopilot_service import AutopilotService

    try:
        goal_id = UUID(args.ref)
    except ValueError:
        return {"error": f"invalid goal reference: {args.ref!r}"}
    assert ctx.user_id is not None, "run_autopilot requires a user"
    result = await AutopilotService(db).run_goal(goal_id, ctx.user_id)
    if "skipped" in result:
        return {"error": result["skipped"]}
    return {
        "run_id": result["run_id"],
        "status": result["status"],
        "findings": [
            {
                "ref": f.get("ref"),
                "title": f.get("title"),
                "org": f.get("org"),
                "score": f.get("score"),
                "why": f.get("why"),
            }
            for f in result["findings"]
        ],
        "note": "These are suggestions — open the Autopilot page to review and apply.",
    }


async def _my_autopilot(db, ctx: ToolContext, args: AutopilotGoalRefInput):
    """The caller's goals + open findings summary."""
    from app.services.autopilot_service import AutopilotService

    assert ctx.user_id is not None, "my_autopilot requires a user"
    service = AutopilotService(db)
    goals = await service.list_goals(ctx.user_id)
    return {
        "goals": [
            {
                "id": str(g["id"]),
                "goal_text": g["goal_text"],
                "status": g["status"],
                "open_findings": g["open_findings"],
                "last_run": g["last_run"],
                "constraints": g["constraints"],
            }
            for g in goals
        ]
    }


async def _compare_jobs(db, ctx: ToolContext, args: CompareJobsInput):
    """Grounded side-by-side fit comparison — deterministic
    layer only; the model narrates, never invents, the numbers."""
    from app.services.job_service import JobService
    from app.services.matching_service import MatchingService

    job_service = JobService(db)
    job_ids = []
    for ref in args.refs:
        job = await job_service.get_by_code_or_id(ref)
        if job is None or job.status != "published":
            return {"error": f"job not found: {ref!r}"}
        job_ids.append(job.id)
    assert ctx.user_id is not None, "compare_jobs requires a user"
    profile = await MatchingService(db).profile_for(ctx.user_id)
    items = await MatchingService(db).compare(profile, job_ids=job_ids)
    return {
        "comparison": [
            {
                "code": item["job"].code,
                "title": item["job"].title,
                "fit_score": round(item["fit_score"], 1),
                "gated": bool((item["insight"].fit_breakdown or {}).get("gates")),
                "gate_reasons": (item["insight"].fit_breakdown or {}).get("gates")
                or [],
                "dimensions": {
                    dim: round(float(entry["score"]), 1)
                    for dim, entry in (
                        (item["insight"].fit_breakdown or {}).get("dimensions") or {}
                    ).items()
                },
                "education_level": (item["job"].attributes or {})
                .get("education", {})
                .get("level"),
                "demand_outlook": (item["job"].attributes or {})
                .get("demand", {})
                .get("outlook"),
                "salary_median": (item["job"].attributes or {})
                .get("salary", {})
                .get("median"),
            }
            for item in items
        ],
        "note": (
            "Fit dimensions score 0-10 (higher = better fit for this user)."
            " Narrate the trade-offs from these numbers only."
        ),
    }


BUILTIN_TOOLS: list[AITool] = [
    AITool(
        key="search_jobs",
        title="Search catalog jobs",
        description="Keyword search over the published job catalog.",
        input_model=SearchJobsInput,
        handler=_search_jobs,
        scope=ToolScope.READ,
        cost_hint="cheap",
    ),
    AITool(
        key="search_postings",
        title="Search open postings",
        description=(
            "Search live vacancies from connected boards (explore filters,"
            " per-posting fit)."
        ),
        input_model=SearchPostingsInput,
        handler=_search_postings,
        scope=ToolScope.READ,
        cost_hint="cheap",
        requires_user=True,
    ),
    AITool(
        key="get_posting",
        title="Posting details",
        description="Structured summary of one posting by short reference.",
        input_model=PostingRefInput,
        handler=_get_posting,
        scope=ToolScope.READ,
        cost_hint="cheap",
    ),
    AITool(
        key="similar_postings",
        title="Similar postings",
        description="Skill-overlap neighbours of one posting.",
        input_model=PostingRefInput,
        handler=_similar_postings,
        scope=ToolScope.READ,
        cost_hint="cheap",
    ),
    AITool(
        key="my_notifications",
        title="My notifications",
        description="Inbox summary or mute-a-kind conversational action.",
        input_model=NotificationActionInput,
        handler=_my_notifications,
        scope=ToolScope.WRITE,
        cost_hint="cheap",
        requires_user=True,
    ),
    AITool(
        key="run_autopilot",
        title="Run an autopilot goal",
        description=(
            "Run one of the user's career goals now; returns the curated"
            " shortlist (suggestions only — never applies)."
        ),
        input_model=AutopilotGoalRefInput,
        handler=_run_autopilot,
        scope=ToolScope.READ,
        cost_hint="expensive",
        requires_user=True,
    ),
    AITool(
        key="my_autopilot",
        title="My autopilot goals",
        description="Summarize the user's autopilot goals and open findings.",
        input_model=AutopilotGoalRefInput,
        handler=_my_autopilot,
        scope=ToolScope.READ,
        cost_hint="cheap",
        requires_user=True,
    ),
    AITool(
        key="compare_jobs",
        title="Compare catalog jobs",
        description=(
            "Side-by-side fit comparison of 2-4 catalog jobs (ids or code"
            " slugs): per-dimension fit, gates, education, demand, salary."
        ),
        input_model=CompareJobsInput,
        handler=_compare_jobs,
        scope=ToolScope.READ,
        cost_hint="cheap",
        requires_user=True,
    ),
]
