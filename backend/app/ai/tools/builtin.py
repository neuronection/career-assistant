"""Built-in tools — the/32 chat tools, registered.

The implementations stay in ``app.ai.agents.chatbot`` (single source);
this module wraps them as registry objects so the chatbot, and later
autopilot/MCP, execute them through ``run_tool``.
"""

from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select

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


class SavedSearchesInput(BaseModel):
    """The caller's saved searches, optionally one search scope."""

    scope: Literal["catalog", "rankings", "universities", "postings"] | None = None
    limit: int = Field(default=12, ge=1, le=50)


class MarketTrendInput(BaseModel):
    """Recorded demand history for exactly one scope: a family key OR a
    catalog job (code/id) reference."""

    family_key: str | None = Field(default=None, max_length=80)
    job_ref: str | None = Field(default=None, max_length=80)
    limit: int = Field(default=12, ge=1, le=60)


class FitBreakdownInput(BaseModel):
    """One target's fit breakdown: a posting reference or a catalog job
    code/id."""

    target: str = Field(min_length=1, max_length=80)


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


class PathDraftInput(BaseModel):
    """The user's career goal in their own words; the flow grounds it."""

    request: str = Field(min_length=3, max_length=500)


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

    from app.services.growth.autopilot_service import AutopilotService

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
    from app.services.growth.autopilot_service import AutopilotService

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
    from app.services.catalog.job_service import JobService
    from app.services.catalog.matching_service import MatchingService

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
    from app.services.postings.applications_service import ApplicationService

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

    from app.services.postings.applications_service import ApplicationService

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
    from app.services.postings.applications_service import ApplicationService

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


async def _my_saved_searches(db, ctx: ToolContext, args: SavedSearchesInput):
    """The caller's saved searches — the reusable queries behind alerts
    and RSS feeds — with the search ids the feed-token scope points at."""
    from app.models.enums import SearchScope
    from app.services.postings.engagement_service import EngagementService

    assert ctx.user_id is not None, "my_saved_searches requires a user"
    scope = SearchScope(args.scope) if args.scope else None
    rows = await EngagementService(db).list_searches(ctx.user_id, scope=scope, saved=True)
    rows = rows[: args.limit]
    if not rows:
        return {
            "searches": [],
            "note": (
                "Nothing tracked yet — no saved searches. Save one from the "
                "postings search or Explore filters (Save search) to see it "
                "here; do not summarize searches that do not exist."
            ),
        }
    return {
        "searches": [
            {
                "search_id": str(row.id),
                "scope": row.scope,
                "query": row.query,
                "filters": row.filters or {},
                "result_count": row.result_count,
                "saved": row.saved,
                "created_at": row.created_at.isoformat(),
            }
            for row in rows
        ],
        "note": (
            "saved=true rows are the caller's saved searches; search_id values "
            "also scope RSS feed tokens."
        ),
    }


async def _market_trend(db, ctx: ToolContext, args: MarketTrendInput):
    """Persisted demand history for one family or catalog job, oldest
    first — thin samples are surfaced as thin, never smoothed."""
    from app.services.catalog.job_service import JobService
    from app.services.postings import market_history_service

    family = (args.family_key or "").strip()
    ref = (args.job_ref or "").strip()
    if bool(family) == bool(ref):
        return {"error": "Pass exactly one of family_key or job_ref."}
    job = None
    if ref:
        job = await JobService(db).get_by_code_or_id(ref)
        if job is None or job.status != "published":
            return {"error": f"job not found: {ref!r}"}
        scope = {"kind": "job", "key": job.code}
    else:
        scope = {"kind": "family", "key": family}
    trend = await market_history_service.trend(
        db,
        family_key=family or None,
        job_id=job.id if job is not None else None,
        limit=args.limit,
    )
    if not trend:
        return {
            "scope": scope,
            "trend": [],
            "note": (
                "No demand history recorded for this scope yet — snapshots "
                "are captured on a daily cadence. Say so instead of "
                "inventing a direction."
            ),
        }
    return {
        "scope": scope,
        "trend": trend,
        "note": (
            "One row per captured day, oldest first; thin_sample rows are too "
            "small to read as a trend. Narrate only these numbers."
        ),
    }


async def _my_fit_breakdown(db, ctx: ToolContext, args: FitBreakdownInput):
    """The deterministic dimensions behind ONE fit score, resolved over
    the live posting first and the catalog archetype second."""
    from app.services.catalog.job_service import JobService
    from app.services.catalog.matching_service import MatchingService
    from app.services.postings.posting_fit_service import get_posting_fit
    from app.services.postings.postings_service import resolve_posting

    assert ctx.user_id is not None, "my_fit_breakdown requires a user"
    posting = await resolve_posting(db, args.target)
    if posting is not None:
        computed = await get_posting_fit(db, ctx.user_id, posting)
        return {
            "target": {
                "kind": "posting",
                "ref": posting.ref,
                "title": posting.title,
                "org": posting.org,
            },
            "score": computed["score"],
            "estimate": bool(computed.get("estimate")),
            "gated": bool(computed.get("gates")),
            "gate_reasons": computed.get("gates") or [],
            "dimensions": {
                key: {
                    "score": round(float(entry.get("score") or 0), 1),
                    "detail": entry.get("detail") or "",
                }
                for key, entry in (computed.get("breakdown") or {}).items()
            },
            "note": (
                "Dimensions score 0-10 (higher = better). estimate=true means "
                "the posting has not been deep-extracted and the score is the "
                "mapped archetype fallback."
            ),
        }
    job = await JobService(db).get_by_code_or_id(args.target)
    if job is None or job.status != "published":
        return {
            "error": (
                f"No posting or catalog job matched {args.target!r}. Use a "
                "posting reference from search_postings or a job code from "
                "search_jobs."
            )
        }
    service = MatchingService(db)
    profile = await service.profile_for(ctx.user_id)
    item = (await service.compare(profile, job_ids=[job.id]))[0]
    breakdown = item["insight"].fit_breakdown or {}
    from app.models.enums import LabelEntityKind
    from app.models.user_model import User
    from app.services.catalog.label_overlay_service import LabelOverlayService
    from app.services.locale_service import effective_locale

    owner = (await db.execute(select(User).where(User.id == ctx.user_id))).scalars().first()
    locale = await effective_locale(db, owner)
    overlay_title = await LabelOverlayService(db).resolve_one(
        LabelEntityKind.JOB, job.id, "label", job.title, locale
    )
    return {
        "target": {"kind": "catalog_job", "code": job.code, "title": overlay_title},
        "score": round(float(item["fit_score"]), 1),
        "estimate": False,
        "gated": bool(breakdown.get("gates")),
        "gate_reasons": breakdown.get("gates") or [],
        "dimensions": {
            dim: {
                "score": round(float(entry.get("score") or 0), 1),
                "detail": entry.get("detail") or "",
            }
            for dim, entry in (breakdown.get("dimensions") or {}).items()
        },
        "note": (
            "Dimensions score 0-10 (higher = better fit for this user). "
            "Narrate the trade-offs from these numbers only."
        ),
    }


async def _set_application_stage(db, ctx: ToolContext, args: ApplicationStageInput):
    """Move one application (executes only through its confirmation card)."""
    import uuid as uuid_mod

    from app.models.enums import ApplicationActor
    from app.services.postings.applications_service import ApplicationService

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
    from app.services.postings.applications_service import ApplicationService

    assert ctx.user_id is not None, "add_application_note requires a user"
    event = await ApplicationService(db).add_note(
        ctx.user_id,
        uuid_mod.UUID(args.application_id),
        args.text,
        actor=ApplicationActor.ASSISTANT,
    )
    return {"event_id": str(event.id), "kind": event.kind}


async def _create_career_path(db, ctx: ToolContext, args: PathDraftInput):
    """Grounded draft flow: search → (missing-job proposal) → structured
    draft. Returns the REVIEW payload — the path exists only after the
    user saves it."""
    from app.ai.graphs.path_draft import run_path_draft_flow

    assert ctx.user_id is not None, "create_career_path requires a user"
    payload = await run_path_draft_flow(db, ctx.user_id, args.request)
    draft = payload.get("draft")
    return {
        "path_draft": draft,
        "proposed_job": payload.get("proposed_job"),
        "candidates": payload.get("candidates") or [],
        "note": payload.get("note") or (payload.get("error") or "No draft was produced."),
    }


async def _my_paths(db, ctx: ToolContext, args: ProfileDigestInput):
    """The caller's paths (registry projection, read-only)."""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.models.career_path_model import CareerPath, UserPathFlag
    from app.models.enums import PathSource, PathStatus

    assert ctx.user_id is not None, "my_paths requires a user"
    owned = select(UserPathFlag.path_id).where(
        UserPathFlag.user_id == ctx.user_id,
        UserPathFlag.step_id.is_(None),
    )
    rows = (
        (
            await db.execute(
                select(CareerPath)
                .options(selectinload(CareerPath.steps), selectinload(CareerPath.job))
                .where(
                    CareerPath.status == PathStatus.PUBLISHED.value,
                    CareerPath.source != PathSource.USER.value,
                )
                .order_by(CareerPath.created_at.desc())
                .limit(args.limit)
            )
        )
        .scalars()
        .all()
    )
    own = (
        (
            await db.execute(
                select(CareerPath)
                .options(selectinload(CareerPath.steps), selectinload(CareerPath.job))
                .where(CareerPath.source == PathSource.USER.value, CareerPath.id.in_(owned))
                .order_by(CareerPath.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return {
        "my_paths": [
            {
                "id": str(path.id),
                "title": path.title,
                "status": path.status,
                "source": path.source,
                "target_job": path.job.code if path.job else None,
                "steps": len(path.steps),
                "flag": "pinned",
            }
            for path in own
        ],
        "curated_paths": [
            {
                "id": str(path.id),
                "title": path.title,
                "target_job": path.job.code if path.job else None,
                "steps": len(path.steps),
            }
            for path in rows
        ],
        "note": (
            "Draft paths must be reviewed and activated on the /paths page "
            "— never describe a draft as active."
        ),
    }


BUILTIN_TOOLS: list[AITool] = [
    AITool(
        key="create_career_path",
        title="Draft a career path",
        description=(
            "Draft ONE career path to a goal the user describes ('I want to "
            "become a data scientist'). Grounded against the catalog; a "
            "missing job is proposed through the moderation queue. The "
            "result is a REVIEW DRAFT — the user saves it to their paths "
            "after reading it; nothing is activated."
        ),
        input_model=PathDraftInput,
        handler=_create_career_path,
        scope=ToolScope.READ,
        cost_hint="expensive",
        requires_user=True,
    ),
    AITool(
        key="my_paths",
        title="My career paths",
        description=(
            "The user's own paths (drafts included) plus the curated "
            "catalog routes — a read-only overview."
        ),
        input_model=ProfileDigestInput,
        handler=_my_paths,
        scope=ToolScope.READ,
        cost_hint="cheap",
        requires_user=True,
    ),
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
            "terms, never a chat sentence. `skill_expand` widens a skill "
            "filter over the curated graph: off (exact), down (subtree + "
            "synonyms), related (also related_to/part_of)."
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
        key="my_saved_searches",
        title="My saved searches",
        description=(
            "The user's saved searches (scope, query, filters, result count)"
            " with their search ids. Empty means nothing is tracked yet — say"
            " so and point at the Save search action; never invent a search."
        ),
        input_model=SavedSearchesInput,
        handler=_my_saved_searches,
        scope=ToolScope.READ,
        cost_hint="cheap",
        requires_user=True,
    ),
    AITool(
        key="market_trend",
        title="Market demand trend",
        description=(
            "Recorded demand history (capture date, sample size, thin-sample"
            " flag, salary band, posting months) for ONE family key or ONE"
            " catalog job. Empty history is reported honestly."
        ),
        input_model=MarketTrendInput,
        handler=_market_trend,
        scope=ToolScope.READ,
        cost_hint="cheap",
    ),
    AITool(
        key="my_fit_breakdown",
        title="One fit score's breakdown",
        description=(
            "The deterministic fit dimensions and gate reasons behind ONE"
            " posting reference or catalog job code — the numbers the model"
            " must narrate instead of guessing."
        ),
        input_model=FitBreakdownInput,
        handler=_my_fit_breakdown,
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
