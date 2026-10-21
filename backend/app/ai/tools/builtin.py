"""Built-in tools — the/32 chat tools, registered.

The implementations stay in ``app.ai.agents.chatbot`` (single source);
this module wraps them as registry objects so the chatbot, and later
autopilot/MCP, execute them through ``run_tool``.
"""

from typing import Literal

from pydantic import BaseModel, Field

from app.ai.tools.base import AITool, ToolContext, ToolRiskClass, ToolScope


class SearchJobsInput(BaseModel):
    """Keyword search over the published catalog.

    The query is search TERMS only (skill, role, city) — never a chat
    sentence; the model passes user prose here otherwise, and the
    server then has to heuristically un-stick it."""

    query: str = Field(min_length=1, max_length=120)
    limit: int = Field(default=8, ge=1, le=25)


class SearchPostingsInput(BaseModel):
    """Open-vacancy search over the explore vocabulary."""

    query: str = Field(default="", max_length=200)
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


class ProfileDigestInput(BaseModel):
    """User-scoped digest read; cap how many items per list."""

    limit: int = Field(default=12, ge=1, le=25)


class ReadProfileItemInput(BaseModel):
    """Open ONE profile entity's full content before proposing edits."""

    kind: Literal["experience_item", "education_item", "certification", "profile_achievement"]
    entity_id: str = Field(min_length=8, max_length=64)


class ReadProfileSectionInput(BaseModel):
    """Open ONE profile section's full JSON before proposing its edit."""

    section: Literal["basics", "academics", "work_preferences", "constraints"]


class MyApplicationsInput(BaseModel):
    """The caller's application pipeline rows (optionally one stage)."""

    stage: (
        Literal["applied", "screening", "interview", "offer", "accepted", "rejected", "withdrawn"]
        | None
    ) = None
    open_only: bool = False


class ApplicationRefInput(BaseModel):
    """One application id (from my_applications)."""

    application_id: str = Field(min_length=8, max_length=64)


class ApplicationStageInput(BaseModel):
    """Move one application to another stage (confirmation card)."""

    application_id: str = Field(min_length=8, max_length=64)
    stage: Literal[
        "applied", "screening", "interview", "offer", "accepted", "rejected", "withdrawn"
    ]
    note: str = Field(default="", max_length=2000)


class ApplicationNoteInput(BaseModel):
    """Append one note to an application timeline (confirmation card)."""

    application_id: str = Field(min_length=8, max_length=64)
    text: str = Field(min_length=1, max_length=4000)


async def _search_jobs(db, ctx: ToolContext, args: SearchJobsInput):
    from app.ai.agents.chatbot import search_jobs_tool

    return await search_jobs_tool(db, args.query, limit=args.limit)


async def _search_postings(db, ctx: ToolContext, args: SearchPostingsInput):
    from app.ai.agents.chatbot import search_postings_tool

    return await search_postings_tool(db, ctx.user_id, args.query, args.filters, n=args.n)


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


async def _my_profile_digest(db, ctx: ToolContext, args: ProfileDigestInput):
    from app.ai.agents.chatbot import my_profile_digest_tool

    assert ctx.user_id is not None, "my_profile_digest requires a user"
    return await my_profile_digest_tool(db, ctx.user_id, limit=args.limit)


async def _my_experience(db, ctx: ToolContext, args: ProfileDigestInput):
    from app.ai.agents.chatbot import my_experience_tool

    assert ctx.user_id is not None, "my_experience requires a user"
    return await my_experience_tool(db, ctx.user_id, limit=args.limit)


async def _my_skills(db, ctx: ToolContext, args: ProfileDigestInput):
    from app.ai.agents.chatbot import my_skills_tool

    assert ctx.user_id is not None, "my_skills requires a user"
    return await my_skills_tool(db, ctx.user_id, limit=args.limit)


async def _my_education(db, ctx: ToolContext, args: ProfileDigestInput):
    from app.ai.agents.chatbot import my_education_tool

    assert ctx.user_id is not None, "my_education requires a user"
    return await my_education_tool(db, ctx.user_id, limit=args.limit)


async def _read_profile_item(db, ctx: ToolContext, args: ReadProfileItemInput):
    from app.ai.agents.chatbot import read_profile_item_tool

    assert ctx.user_id is not None, "read_profile_item requires a user"
    return await read_profile_item_tool(db, ctx.user_id, args.kind, args.entity_id)


async def _read_profile_section(db, ctx: ToolContext, args: ReadProfileSectionInput):
    from app.ai.agents.chatbot import read_profile_section_tool

    assert ctx.user_id is not None, "read_profile_section requires a user"
    return await read_profile_section_tool(db, ctx.user_id, args.section)


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
                "gate_reasons": (item["insight"].fit_breakdown or {}).get("gates") or [],
                "dimensions": {
                    dim: round(float(entry["score"]), 1)
                    for dim, entry in (
                        (item["insight"].fit_breakdown or {}).get("dimensions") or {}
                    ).items()
                },
                "education_level": (item["job"].attributes or {}).get("education", {}).get("level"),
                "demand_outlook": (item["job"].attributes or {}).get("demand", {}).get("outlook"),
                "salary_median": (item["job"].attributes or {}).get("salary", {}).get("median"),
            }
            for item in items
        ],
        "note": (
            "Fit dimensions score 0-10 (higher = better fit for this user)."
            " Narrate the trade-offs from these numbers only."
        ),
    }


async def _my_applications(db, ctx: ToolContext, args: MyApplicationsInput):
    """The caller's application pipeline with the tracker's own ids."""
    from app.services.applications_service import ApplicationService

    assert ctx.user_id is not None, "my_applications requires a user"
    rows = await ApplicationService(db).list_applications(
        ctx.user_id, stage=args.stage, open_only=args.open_only
    )
    return {
        "applications": [
            {
                "application_id": str(application.id),
                "posting_ref": posting.ref,
                "title": posting.title,
                "org": posting.org,
                "stage": application.stage,
                "outcome": application.outcome,
                "applied_at": application.applied_at.isoformat()
                if application.applied_at
                else None,
                "deadline_at": application.deadline_at.isoformat()
                if application.deadline_at
                else None,
                "next_followup_at": application.next_followup_at.isoformat()
                if application.next_followup_at
                else None,
                "closed_at": application.closed_at.isoformat() if application.closed_at else None,
            }
            for application, posting in rows
        ],
        "note": (
            "application_id values feed my_application_timeline, and stage/note"
            " changes must go through the confirmation card tools."
        ),
    }


async def _my_application_timeline(db, ctx: ToolContext, args: ApplicationRefInput):
    """One application's full event timeline (newest first)."""
    import uuid as uuid_mod

    from app.services.applications_service import ApplicationService

    assert ctx.user_id is not None, "my_application_timeline requires a user"
    service = ApplicationService(db)
    application = await service.get(ctx.user_id, uuid_mod.UUID(args.application_id))
    events = await service.timeline(ctx.user_id, application.id)
    return {
        "application_id": str(application.id),
        "stage": application.stage,
        "outcome": application.outcome,
        "notes": application.notes,
        "events": [
            {
                "at": event.at.isoformat(),
                "kind": event.kind,
                "stage_from": event.stage_from,
                "stage_to": event.stage_to,
                "body": event.body,
                "actor": event.actor,
            }
            for event in events
        ],
    }


async def _my_deadlines(db, ctx: ToolContext, args: ProfileDigestInput):
    """Application deadlines merged with university admission deadlines."""
    from datetime import UTC, datetime

    from sqlalchemy import select

    from app.models.university_model import Department, University
    from app.services.applications_service import ApplicationService

    assert ctx.user_id is not None, "my_deadlines requires a user"
    today = datetime.now(UTC).date()
    rows = await ApplicationService(db).list_applications(ctx.user_id, open_only=True)
    deadlines = []
    for application, posting in rows:
        if application.deadline_at is None:
            continue
        deadlines.append(
            {
                "kind": "application",
                "title": posting.title,
                "org": posting.org,
                "deadline": application.deadline_at.date().isoformat(),
                "application_id": str(application.id),
            }
        )
    admissions = await db.execute(
        select(Department, University)
        .join(University, University.id == Department.university_id)
        .where(Department.application_deadline.is_not(None))
        .order_by(Department.application_deadline)
    )
    for department, university in admissions.all():
        deadline = department.application_deadline
        if deadline is None or deadline < today:
            continue
        deadlines.append(
            {
                "kind": "admission",
                "title": department.name,
                "org": university.name,
                "deadline": deadline.isoformat(),
                "degree": department.degree,
            }
        )
    deadlines.sort(key=lambda row: row["deadline"])
    return {"deadlines": deadlines[: args.limit]}


async def _set_application_stage(db, ctx: ToolContext, args: ApplicationStageInput):
    """Move one application (executes only through its confirmation card)."""
    import uuid as uuid_mod

    from app.models.enums import ApplicationActor
    from app.services.applications_service import ApplicationService

    assert ctx.user_id is not None, "set_application_stage requires a user"
    application = await ApplicationService(db).transition(
        ctx.user_id,
        uuid_mod.UUID(args.application_id),
        to_stage=args.stage,
        actor=ApplicationActor.ASSISTANT,
        body=args.note,
    )
    return {"application_id": str(application.id), "stage": application.stage}


async def _add_application_note(db, ctx: ToolContext, args: ApplicationNoteInput):
    """Append a note (executes only through its confirmation card)."""
    import uuid as uuid_mod

    from app.models.enums import ApplicationActor
    from app.services.applications_service import ApplicationService

    assert ctx.user_id is not None, "add_application_note requires a user"
    event = await ApplicationService(db).add_note(
        ctx.user_id,
        uuid_mod.UUID(args.application_id),
        args.text,
        actor=ApplicationActor.ASSISTANT,
    )
    return {"event_id": str(event.id), "kind": event.kind}


BUILTIN_TOOLS: list[AITool] = [
    AITool(
        key="search_jobs",
        title="Search catalog jobs",
        description=(
            "Keyword search over the published job catalog. The query is "
            "SHORT search terms (skill, role, city) — never a chat "
            "sentence."
        ),
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
            " per-posting fit). The query — if any — holds short search "
            "terms, never a chat sentence."
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
    AITool(
        key="my_profile_digest",
        title="My profile overview",
        description=(
            "Counts + basics + languages of the user's profile (grounding"
            " for chat-proposed profile edits)."
        ),
        input_model=ProfileDigestInput,
        handler=_my_profile_digest,
        scope=ToolScope.READ,
        cost_hint="cheap",
        requires_user=True,
    ),
    AITool(
        key="my_experience",
        title="My experience items",
        description=(
            "The user's work/project/internship/volunteer items with ids —"
            " grounding for experience edit proposals."
        ),
        input_model=ProfileDigestInput,
        handler=_my_experience,
        scope=ToolScope.READ,
        cost_hint="cheap",
        requires_user=True,
    ),
    AITool(
        key="my_skills",
        title="My skills",
        description=(
            "The user's claimed skills with row ids and levels — grounding"
            " for skill edit proposals."
        ),
        input_model=ProfileDigestInput,
        handler=_my_skills,
        scope=ToolScope.READ,
        cost_hint="cheap",
        requires_user=True,
    ),
    AITool(
        key="my_education",
        title="My education & credentials",
        description=(
            "Education, certifications and achievements with ids —"
            " grounding for those edit proposals."
        ),
        input_model=ProfileDigestInput,
        handler=_my_education,
        scope=ToolScope.READ,
        cost_hint="cheap",
        requires_user=True,
    ),
    AITool(
        key="read_profile_item",
        title="Open one profile item",
        description=(
            "Full current content of ONE experience item / education"
            " entry / certification / achievement (ids from the digests)."
            " REQUIRED before proposing any update or delete to it —"
            " edits to items you have not opened are discarded."
        ),
        input_model=ReadProfileItemInput,
        handler=_read_profile_item,
        scope=ToolScope.READ,
        cost_hint="cheap",
        requires_user=True,
    ),
    AITool(
        key="read_profile_section",
        title="Open one profile section",
        description=(
            "Full current JSON of one profile section (basics, academics,"
            " work_preferences, constraints). REQUIRED before proposing an"
            " update to it — unread sections cannot be edited."
        ),
        input_model=ReadProfileSectionInput,
        handler=_read_profile_section,
        scope=ToolScope.READ,
        cost_hint="cheap",
        requires_user=True,
    ),
    AITool(
        key="my_applications",
        title="My applications",
        description=(
            "The user's application pipeline (one row per posting) with"
            " application_id, stage, dates and the next follow-up. Optionally"
            " filter by stage; pass open_only for active applications."
        ),
        input_model=MyApplicationsInput,
        handler=_my_applications,
        scope=ToolScope.READ,
        cost_hint="cheap",
        requires_user=True,
    ),
    AITool(
        key="my_application_timeline",
        title="One application's timeline",
        description=(
            "Full event history of ONE application (newest first) with its"
            " current stage and rolling notes. Read this before proposing a"
            " stage change or note."
        ),
        input_model=ApplicationRefInput,
        handler=_my_application_timeline,
        scope=ToolScope.READ,
        cost_hint="cheap",
        requires_user=True,
    ),
    AITool(
        key="my_deadlines",
        title="My deadlines",
        description=(
            "Application deadlines merged with upcoming university admission"
            " deadlines, sorted by date."
        ),
        input_model=ProfileDigestInput,
        handler=_my_deadlines,
        scope=ToolScope.READ,
        cost_hint="cheap",
        requires_user=True,
    ),
    AITool(
        key="set_application_stage",
        title="Move an application's stage",
        description=(
            "Move ONE application to another pipeline stage. The user must"
            " approve a confirmation card before anything runs; read the"
            " application timeline first."
        ),
        input_model=ApplicationStageInput,
        handler=_set_application_stage,
        scope=ToolScope.WRITE,
        risk_class=ToolRiskClass.DESTRUCTIVE,
        cost_hint="cheap",
        requires_user=True,
    ),
    AITool(
        key="add_application_note",
        title="Add an application note",
        description=(
            "Append one note to an application's timeline. The user must"
            " approve a confirmation card before anything runs."
        ),
        input_model=ApplicationNoteInput,
        handler=_add_application_note,
        scope=ToolScope.WRITE,
        risk_class=ToolRiskClass.DESTRUCTIVE,
        cost_hint="cheap",
        requires_user=True,
    ),
]
