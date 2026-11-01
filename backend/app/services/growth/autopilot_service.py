"""Career Autopilot service: goal lifecycle + run orchestration.

The agentic work lives in the LangGraph flow (``app.ai.graphs.autopilot``);
this service owns the durable decisions around it: goal CRUD with cadence
schedules, the on-demand/scheduled run entry point,
checkpoint resume of interrupted runs, constraint learning from feedback,
pause-on-total-dismissal and the stale-goal nudge. Applying to a posting
is never automated — findings are suggestions only.
"""

import base64
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID

from sqlalchemy import Integer, func, literal, select, tuple_
from sqlalchemy import cast as sa_cast
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, selectinload
from sqlalchemy.sql.elements import ColumnElement

from app.core.errors import NotFoundError, PermissionDeniedError, ValidationError
from app.models.autopilot_model import AutopilotFinding, AutopilotGoal, AutopilotRun
from app.models.enums import AutopilotFeedback, AutopilotRunStatus
from app.schemas.autopilot import (
    AutopilotBudget,
    AutopilotConstraints,
    AutopilotGoalCreate,
    AutopilotGoalUpdate,
    ProfileUsage,
)

logger = logging.getLogger(__name__)

STALE_STREAK = 3

EXECUTION_NODE_ORDER = [
    "plan",
    "search",
    "filter",
    "replan",
    "evaluate",
    "graph_sweep",
    "budget_guard",
    "curate",
    "deliver",
]


def execution_nodes() -> list[str]:
    """The compiled graph's nodes in EXECUTION order.

    Compiled-graph insertion order is not execution order (``budget_guard``
    is added second but runs late), so the run detail derives its node list
    from this sequence, filtered against the compiled set — no frontend
    copy that drifts; a future node joins through both the graph and this
    list or the set assertion in the tests fails. The deps are never
    invoked for the node set, so the session placeholder is an explicit
    cast.
    """
    from app.ai.graphs.autopilot import GraphDeps, build_autopilot_graph

    compiled = set(build_autopilot_graph(GraphDeps(db=cast(AsyncSession, None))).nodes)
    compiled -= {"__start__", "__end__"}
    ordered = [node for node in EXECUTION_NODE_ORDER if node in compiled]
    return ordered + sorted(compiled - set(EXECUTION_NODE_ORDER))


async def profile_context_preview(
    db: AsyncSession, user_id: UUID, usage: ProfileUsage, seniority: list[str]
) -> dict:
    """The caller's effective profile snapshot for a DRAFT usage block.

    What a run with these inputs would see: ``collect_profile_context``
    over the draft constraints (gated fields dropped, languages and the
    effective stage included, ``stage_source`` naming which side supplied
    the stage) plus the lifestyle constraint count. Owner-scoped: a draft
    never touches a goal row.
    """
    from app.ai.graphs.autopilot import collect_profile_context
    from app.services.deps import get_profile_for_user
    from app.services.postings.posting_fit_service import LIFESTYLE_CONSTRAINT_KEYS

    constraints = {
        "seniority": [str(value) for value in seniority],
        "profile": usage.model_dump(mode="json"),
    }
    snapshot = await collect_profile_context(db, user_id, constraints)
    profile = await get_profile_for_user(db, user_id)
    if usage.use_lifestyle:
        values = profile.constraints or {}
        snapshot["lifestyle_count"] = sum(
            1 for key in LIFESTYLE_CONSTRAINT_KEYS if values.get(key) not in (None, False)
        )
    return snapshot


def _utcnow() -> datetime:
    return datetime.now(UTC)


class AutopilotService:
    def __init__(self, db: AsyncSession, checkpointer=None):
        self.db = db
        self._checkpointer = checkpointer

    # -------------------------------------------------------------- goals

    async def create_goal(self, user_id: UUID, data: AutopilotGoalCreate) -> AutopilotGoal:
        """Create a goal; an optional cadence attaches a schedule."""
        from app.services.scheduler import triggers as trigger_registry
        from app.services.scheduler.runner import SchedulerService

        if data.cadence is not None:
            trigger_registry.resolve_trigger(data.cadence)
        goal = AutopilotGoal(
            user_id=user_id,
            goal_text=data.goal_text.strip(),
            constraints=data.constraints.model_dump(mode="json"),
            budget=data.budget.model_dump(mode="json", exclude_none=True),
            cadence=data.cadence,
        )
        self.db.add(goal)
        await self.db.flush()
        if data.cadence is not None:
            await SchedulerService(self.db).set_autopilot_schedule(user_id, goal.id, data.cadence)
        await self.db.commit()
        await self.db.refresh(goal)
        return goal

    async def _require_goal(self, user_id: UUID, goal_id: UUID) -> AutopilotGoal:
        if isinstance(user_id, str):
            user_id = UUID(user_id)
        goal = await self.db.get(AutopilotGoal, goal_id)
        if goal is None:
            raise NotFoundError("Autopilot goal not found")
        if goal.user_id != user_id:
            raise PermissionDeniedError("Not your goal")
        return goal

    async def update_goal(
        self, user_id: UUID, goal_id: UUID, data: AutopilotGoalUpdate
    ) -> AutopilotGoal:
        """Patch text/constraints/budget/status; cadence changes re-wire
        the schedule (removal detaches it)."""
        from app.services.scheduler.runner import SchedulerService

        goal = await self._require_goal(user_id, goal_id)
        payload = data.model_dump(exclude_none=True, exclude={"cadence", "remove_cadence"})
        if "constraints" in payload:
            constraints = AutopilotConstraints.model_validate(payload.pop("constraints"))
            goal.constraints = constraints.model_dump(mode="json")
        if "budget" in payload:
            goal.budget = AutopilotBudget.model_validate(payload.pop("budget")).model_dump(
                mode="json", exclude_none=True
            )
        for field, value in payload.items():
            setattr(goal, field, value)
        if data.remove_cadence:
            await SchedulerService(self.db).set_autopilot_schedule(user_id, goal.id, None)
        elif data.cadence is not None:
            await SchedulerService(self.db).set_autopilot_schedule(user_id, goal.id, data.cadence)
        await self.db.commit()
        await self.db.refresh(goal)
        return goal

    async def delete_goal(self, user_id: UUID, goal_id: UUID) -> None:
        """Delete a goal with its runs/findings and cadence schedule."""
        from app.models.enums import ScheduleKind
        from app.models.schedule_model import Schedule

        goal = await self._require_goal(user_id, goal_id)
        rows = await self.db.execute(
            select(Schedule).where(
                Schedule.kind == ScheduleKind.USER_AUTOPILOT.value,
                Schedule.owner_user_id == user_id,
            )
        )
        for schedule in rows.scalars().all():
            if schedule.payload.get("goal_id") == str(goal_id):
                await self.db.delete(schedule)
        await self.db.flush()
        await self.db.delete(goal)
        await self.db.commit()

    async def list_goals(self, user_id: UUID) -> list[dict]:
        """Goals with last-run outcome + open finding counts."""
        goals = (
            (
                await self.db.execute(
                    select(AutopilotGoal)
                    .where(AutopilotGoal.user_id == user_id)
                    .order_by(AutopilotGoal.created_at.desc())
                )
            )
            .scalars()
            .all()
        )
        out = []
        for goal in goals:
            out.append(
                {
                    **_goal_out(goal),
                    "last_run": await self._last_run_out(goal.id),
                    "open_findings": await self._open_finding_count(goal.id),
                }
            )
        return out

    async def get_goal_detail(self, user_id: UUID, goal_id: UUID) -> dict:
        goal = await self._require_goal(user_id, goal_id)
        return {
            **_goal_out(goal),
            "last_run": await self._last_run_out(goal.id),
            "open_findings": await self._open_finding_count(goal.id),
            "runs": await self.runs(user_id, goal_id),
        }

    async def runs(self, user_id: UUID, goal_id: UUID) -> list[dict]:
        """A goal's run history including the searches_executed timeline
        (the "what I searched & why" transparency view, amendment)."""
        await self._require_goal(user_id, goal_id)
        rows = (
            (
                await self.db.execute(
                    select(AutopilotRun)
                    .where(AutopilotRun.goal_id == goal_id)
                    .order_by(AutopilotRun.created_at.desc())
                    .limit(30)
                )
            )
            .scalars()
            .all()
        )
        out = []
        for run in rows:
            findings = await self._findings_out(run.id)
            out.append({**_run_out(run), "findings": findings})
        return out

    # ----------------------------------------------------------- findings

    async def findings_feed(
        self,
        user_id: UUID,
        *,
        goal_id: UUID | None = None,
        run_id: UUID | None = None,
        state: str = "open",
        latest_per_posting: bool = True,
        sort: str = "newest",
        limit: int = 20,
        cursor: str | None = None,
        min_score: float | None = None,
        coverage_min: int | None = None,
        org: str | None = None,
        source: str | None = None,
        seniority: str | None = None,
        remote: bool = False,
        posted_within: str | None = None,
        hide_applied: bool = False,
    ) -> dict:
        """The flat findings feed: one row per (latest) evaluation.

        Ownership rides the run → goal join (`goal.user_id == caller`);
        the applied badge derives from the caller's `applications` row —
        never a stored flag. `latest_per_posting` keeps only each
        posting's newest evaluation (row-value comparison on
        ``(created_at, id)``, stable on both dialects); the state filter
        applies to the surviving row, so a dismissed newest evaluation
        hides the posting under the default `open`. Cursors are opaque
        `(sort_key, id)` keyset markers per sort — score ties are
        guaranteed (Numeric(4,2)), so a single-key cursor would loop;
        the keyset runs over the deduped row's own ``(sort_key, id)``, so
        a re-rank between pages (a newer evaluation displacing the
        cursor row) is accepted drift, never a loop or a repeat. The
        posting axes (org/source/seniority/remote/posted_within) filter
        through the posting join; `posted_within` reuses the shared
        effective-posted window clause.
        """
        from app.models.application_model import Application
        from app.models.posting_model import JobPosting, JobSource

        if sort not in ("newest", "score"):
            raise ValidationError("sort must be newest|score")
        if state not in ("open", "dismissed", "all"):
            raise ValidationError("state must be open|dismissed|all")

        conditions = _feed_conditions(
            self.db,
            goal_id=goal_id,
            run_id=run_id,
            state=state,
            min_score=min_score,
            coverage_min=coverage_min,
            org=org,
            source=source,
            seniority=seniority,
            remote=remote,
            posted_within=posted_within,
        )
        if latest_per_posting:
            sibling = aliased(AutopilotFinding)
            newer = (
                select(sibling.id)
                .where(
                    sibling.posting_id == AutopilotFinding.posting_id,
                    tuple_(sibling.created_at, sibling.id)
                    > tuple_(AutopilotFinding.created_at, AutopilotFinding.id),
                )
                .exists()
            )
        if cursor:
            cursor_sort, key, after_id = _decode_feed_cursor(cursor)
            if cursor_sort != sort:
                raise ValidationError("Cursor does not match the requested sort")
        else:
            key, after_id = None, None

        order_col = AutopilotFinding.created_at if sort == "newest" else AutopilotFinding.score
        query = (
            select(
                AutopilotFinding,
                JobPosting,
                AutopilotRun,
                AutopilotGoal,
                Application,
                JobSource.key,
            )
            .join(AutopilotRun, AutopilotRun.id == AutopilotFinding.run_id)
            .join(AutopilotGoal, AutopilotGoal.id == AutopilotRun.goal_id)
            .join(JobPosting, JobPosting.id == AutopilotFinding.posting_id)
            .join(JobSource, JobSource.id == JobPosting.source_id)
            .outerjoin(
                Application,
                (Application.posting_id == AutopilotFinding.posting_id)
                & (Application.user_id == user_id),
            )
            .where(AutopilotGoal.user_id == user_id, *conditions)
        )
        if hide_applied:
            query = query.where(Application.id.is_(None))
        if latest_per_posting:
            query = query.where(~newer)
        if key is not None:
            query = query.where(
                tuple_(order_col, AutopilotFinding.id)
                < tuple_(
                    literal(key, type_=order_col.type),
                    literal(after_id, type_=AutopilotFinding.id.type),
                )
            )
        query = query.order_by(order_col.desc(), AutopilotFinding.id.desc()).limit(limit)
        rows = (await self.db.execute(query)).all()

        items = []
        for finding, posting, run, goal, application, source_key in rows:
            evidence = finding.evidence or {}
            breakdown = evidence.get("breakdown") or {}
            items.append(
                {
                    "id": str(finding.id),
                    "score": float(finding.score),
                    "why": finding.why,
                    "quotes": evidence.get("quotes") or [],
                    "must_coverage": evidence.get("must_coverage"),
                    "disabled_dims": sum(
                        1
                        for part in breakdown.values()
                        if isinstance(part, dict) and part.get("disabled")
                    ),
                    "dismissed_at": finding.dismissed_at,
                    "feedback": finding.feedback,
                    "created_at": finding.created_at,
                    "run_id": str(run.id),
                    "run_status": run.status,
                    "goal_id": str(goal.id),
                    "goal_text": goal.goal_text,
                    "applied": application is not None,
                    "posting": {
                        "id": str(posting.id),
                        "ref": posting.ref,
                        "title": posting.title,
                        "org": posting.org,
                        "url": posting.url,
                        "location": posting.location or {},
                        "salary": _salary_out(posting),
                        "posted_at": posting.posted_at,
                        "remote": posting.onsite_policy,
                        "status": posting.status,
                        "expires_at": posting.expires_at,
                        "source": source_key,
                        "extracted": posting.extract_version is not None,
                        "seniority": posting.seniority,
                    },
                }
            )
        next_cursor = None
        if len(items) == limit:
            last_finding = rows[-1][0]
            last_key = last_finding.created_at if sort == "newest" else float(last_finding.score)
            next_cursor = _encode_feed_cursor(sort, last_key, last_finding.id)
        return {
            "items": items,
            "next_cursor": next_cursor,
            "facets": await self.feed_facets(
                user_id,
                goal_id=goal_id,
                state=state,
                min_score=min_score,
                coverage_min=coverage_min,
                org=org,
                source=source,
                seniority=seniority,
                remote=remote,
                posted_within=posted_within,
                latest_per_posting=latest_per_posting,
            ),
        }

    async def feed_facets(
        self,
        user_id: UUID,
        *,
        goal_id: UUID | None = None,
        state: str = "open",
        min_score: float | None = None,
        coverage_min: int | None = None,
        org: str | None = None,
        source: str | None = None,
        seniority: str | None = None,
        remote: bool = False,
        posted_within: str | None = None,
        latest_per_posting: bool = True,
    ) -> dict:
        """Self-excluding facet counts over the active filter set (the
        explore pattern): each dimension recounts without its own filter,
        so a value's count never drops to zero because it is selected.
        One grouped query per dimension; sized for a personal dataset."""
        from app.models.posting_model import JobPosting, JobSource

        async def grouped(skip: set[str], group: Any) -> dict[Any, int]:
            conditions = _feed_conditions(
                self.db,
                goal_id=None if "goal" in skip else goal_id,
                run_id=None,
                state=None if "state" in skip else state,
                min_score=min_score,
                coverage_min=coverage_min,
                org=org,
                source=None if "source" in skip else source,
                seniority=None if "seniority" in skip else seniority,
                remote=remote,
                posted_within=posted_within,
            )
            query = (
                select(group, func.count(AutopilotFinding.id))
                .select_from(AutopilotFinding)
                .join(AutopilotRun, AutopilotRun.id == AutopilotFinding.run_id)
                .join(AutopilotGoal, AutopilotGoal.id == AutopilotRun.goal_id)
                .join(JobPosting, JobPosting.id == AutopilotFinding.posting_id)
                .join(JobSource, JobSource.id == JobPosting.source_id)
                .where(AutopilotGoal.user_id == user_id, *conditions)
            )
            if latest_per_posting:
                sibling = aliased(AutopilotFinding)
                newer = (
                    select(sibling.id)
                    .where(
                        sibling.posting_id == AutopilotFinding.posting_id,
                        tuple_(sibling.created_at, sibling.id)
                        > tuple_(AutopilotFinding.created_at, AutopilotFinding.id),
                    )
                    .exists()
                )
                query = query.where(~newer)
            rows = (await self.db.execute(query.group_by(group))).all()
            return {row[0]: int(row[1]) for row in rows}

        open_counts = await grouped({"state"}, AutopilotFinding.dismissed_at.is_(None))
        goal_counts = await grouped({"goal"}, AutopilotGoal.id)
        source_counts = await grouped({"source"}, JobSource.key)
        seniority_counts = await grouped({"seniority"}, JobPosting.seniority)
        return {
            "goal": {str(key): count for key, count in goal_counts.items()},
            "source": dict(source_counts),
            "seniority": {
                str(key): count for key, count in seniority_counts.items() if key is not None
            },
            "state": {
                "open": int(open_counts.get(True, 0)),
                "dismissed": int(open_counts.get(False, 0)),
            },
        }

    async def dismiss_run_findings(self, user_id: UUID, run_id: UUID) -> dict:
        """Bulk-dismiss every OPEN finding of one run (plan 175 S4).

        Ownership rides the run → goal join: a foreign and a missing run
        answer the same 404 (the run_detail rule). One audit-visible
        action — constraint learning is NOT triggered (feedback is an
        intentional, per-finding signal; decision log), the `feedback`
        column is untouched.
        """
        run = (
            (
                await self.db.execute(
                    select(AutopilotRun)
                    .join(AutopilotGoal, AutopilotGoal.id == AutopilotRun.goal_id)
                    .where(AutopilotRun.id == run_id, AutopilotGoal.user_id == user_id)
                )
            )
            .scalars()
            .first()
        )
        if run is None:
            raise NotFoundError("Autopilot run not found")
        rows = (
            (
                await self.db.execute(
                    select(AutopilotFinding).where(
                        AutopilotFinding.run_id == run.id,
                        AutopilotFinding.dismissed_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        dismissed_at = _utcnow()
        for finding in rows:
            finding.dismissed_at = dismissed_at
        await self.db.commit()
        return {"dismissed": len(rows)}

    async def runs_rail(self, user_id: UUID, limit: int = 20) -> list[dict]:
        """The runs rail, cross-goal, newest first.

        One row per run: status, spend and the two counts the rail renders
        — live (undismissed) findings and the Σ `examined` over the run's
        searches-executed timeline. The timeline itself stays on
        `run_detail`; the rail never ships it.
        """
        rows = (
            await self.db.execute(
                select(AutopilotRun, AutopilotGoal)
                .join(AutopilotGoal, AutopilotGoal.id == AutopilotRun.goal_id)
                .where(AutopilotGoal.user_id == user_id)
                .order_by(AutopilotRun.created_at.desc())
                .limit(limit)
            )
        ).all()
        run_ids = [run.id for run, _goal in rows]
        live: dict[UUID, int] = {}
        if run_ids:
            counts = await self.db.execute(
                select(AutopilotFinding.run_id, func.count())
                .where(
                    AutopilotFinding.run_id.in_(run_ids),
                    AutopilotFinding.dismissed_at.is_(None),
                )
                .group_by(AutopilotFinding.run_id)
            )
            live = dict(counts.all())
        return [
            {
                "id": str(run.id),
                "goal_id": str(goal.id),
                "goal_text": goal.goal_text,
                "status": run.status,
                "created_at": run.created_at,
                "finished_at": run.finished_at,
                "tokens_used": run.tokens_used,
                "findings_count": live.get(run.id, 0),
                "examined_sum": sum(
                    int(entry.get("examined") or 0)
                    for entry in (run.searches_executed or [])
                    if isinstance(entry, dict)
                ),
            }
            for run, goal in rows
        ]

    async def _findings_out(self, run_id: UUID) -> list[dict]:
        from app.models.posting_model import JobPosting

        rows = (
            await self.db.execute(
                select(AutopilotFinding, JobPosting)
                .join(JobPosting, JobPosting.id == AutopilotFinding.posting_id)
                .where(AutopilotFinding.run_id == run_id)
                .order_by(AutopilotFinding.score.desc())
            )
        ).all()
        return [
            {
                "id": str(finding.id),
                "posting_id": str(posting.id),
                "ref": posting.ref,
                "title": posting.title,
                "org": posting.org,
                "url": posting.url,
                "score": float(finding.score),
                "why": finding.why,
                "evidence": finding.evidence or {},
                "feedback": finding.feedback,
                "dismissed_at": finding.dismissed_at,
                "created_at": finding.created_at,
            }
            for finding, posting in rows
        ]

    async def _require_finding(
        self, user_id: UUID, finding_id: UUID
    ) -> tuple[AutopilotFinding, AutopilotGoal]:
        finding = await self.db.get(
            AutopilotFinding,
            finding_id,
            options=(selectinload(AutopilotFinding.posting),),
        )
        if finding is None:
            raise NotFoundError("Finding not found")
        run = await self.db.get(AutopilotRun, finding.run_id)
        goal = await self.db.get(AutopilotGoal, run.goal_id) if run else None
        if run is None or goal is None or goal.user_id != user_id:
            raise PermissionDeniedError("Not your finding")
        return finding, goal

    async def feedback(self, user_id: UUID, finding_id: UUID, kind: str) -> dict:
        """Apply feedback, learn constraints (shown back explicitly), and
        pause the goal when every finding of its latest run is dismissed."""
        feedback = AutopilotFeedback(kind)
        finding, goal = await self._require_finding(user_id, finding_id)
        finding.feedback = feedback.value
        learned: list[str] = []
        if feedback is AutopilotFeedback.HIDE_LIKE_THIS:
            finding.dismissed_at = _utcnow()
            learned = await self._learn_terms(finding, avoid=True)
            constraints = dict(goal.constraints or {})
            terms = list(constraints.get("never_terms") or [])
            for term in learned:
                if term not in terms:
                    terms.append(term)
            constraints["never_terms"] = terms[:20]
            must = [t for t in constraints.get("must_terms") or [] if t not in learned]
            constraints["must_terms"] = must
            goal.constraints = constraints
        else:
            finding.dismissed_at = None
            learned = await self._learn_terms(finding, avoid=False)
            constraints = dict(goal.constraints or {})
            terms = list(constraints.get("must_terms") or [])
            for term in learned:
                if term not in terms:
                    terms.append(term)
            constraints["must_terms"] = terms[:10]
            never = [t for t in constraints.get("never_terms") or [] if t not in learned]
            constraints["never_terms"] = never
            goal.constraints = constraints
        paused = False
        if feedback is AutopilotFeedback.HIDE_LIKE_THIS:
            paused = await self._pause_when_all_dismissed(goal)
        await self.db.commit()
        return {
            "finding_id": str(finding.id),
            "feedback": feedback.value,
            "learned_terms": learned,
            "constraints": goal.constraints,
            "goal_paused": paused,
        }

    async def _learn_terms(self, finding: AutopilotFinding, *, avoid: bool) -> list[str]:
        """Terms to add to the goal's constraints from one posting.

        "hide like this" learns the org + top skill keys (concrete, visible
        terms the filter/planner nodes act on); "more like this" learns the
        skill keys. Skills come from the canonical posting_skills join (the
        extract JSONB is only a hint); the API echoes everything learned so
        the user stays in control and can remove any term.
        """
        from app.models.posting_model import PostingSkill
        from app.models.taxonomy_model import Skill

        posting = finding.posting
        skills: list[str] = []
        for skill in (posting.extract or {}).get("skills") or []:
            if isinstance(skill, dict):
                key = str(skill.get("key") or skill.get("skill_key") or "").strip()
                if key:
                    skills.append(key.casefold()[:60])
            if len(skills) >= 2:
                break
        if not skills:
            rows = await self.db.execute(
                select(Skill.key)
                .join(PostingSkill, PostingSkill.skill_id == Skill.id)
                .where(PostingSkill.posting_id == posting.id)
                .order_by(PostingSkill.priority.desc())
                .limit(2)
            )
            skills = [str(key).strip().casefold()[:60] for key in rows.scalars().all()]
        if avoid and posting.org:
            return [posting.org.strip().casefold()[:60], *skills][:3]
        return skills

    async def _pause_when_all_dismissed(self, goal: AutopilotGoal) -> bool:
        """Guardrail: every finding of the newest finding-bearing run
        dismissed → pause the goal and nudge toward refinement."""
        rows = (
            (
                await self.db.execute(
                    select(AutopilotRun.id)
                    .where(
                        AutopilotRun.goal_id == goal.id,
                        AutopilotRun.status.in_(
                            [
                                AutopilotRunStatus.COMPLETED.value,
                                AutopilotRunStatus.BUDGET_ABORTED.value,
                            ]
                        ),
                    )
                    .order_by(AutopilotRun.created_at.desc())
                    .limit(5)
                )
            )
            .scalars()
            .all()
        )
        for run_id in rows:
            findings = (
                await self.db.execute(
                    select(AutopilotFinding.id, AutopilotFinding.dismissed_at).where(
                        AutopilotFinding.run_id == run_id
                    )
                )
            ).all()
            if not findings:
                continue
            if all(dismissed_at is not None for _id, dismissed_at in findings):
                if goal.status == "active":
                    goal.status = "paused"
                    await self._emit_stale_nudge(goal, paused=True)
                return True
            return False
        return False

    async def _emit_stale_nudge(
        self, goal: AutopilotGoal, *, paused: bool = False, streak: int = STALE_STREAK
    ) -> None:
        from app.services.notification_service import NotificationService

        title = (
            "Autopilot paused — refine your goal"
            if paused
            else "Your autopilot goal keeps coming up empty"
        )
        body = (
            "You dismissed every suggestion. Adjust the goal's constraints "
            "(never/must terms, salary, filters) and re-enable it."
            if paused
            else f"{streak} runs without a single finding — refine the "
            "goal text or relax its constraints."
        )
        await NotificationService(self.db).emit(
            "autopilot_goal_stale",
            [goal.user_id],
            title=title,
            body=body,
            payload={"goal_id": str(goal.id), "link": "/autopilot"},
            source_ref={"goal_id": str(goal.id)},
            dedup_key=(
                f"autopilot-stale:{goal.id}:paused"
                if paused
                else f"autopilot-stale:{goal.id}:{streak}"
            ),
        )

    # --------------------------------------------------------------- runs

    async def run_goal(
        self,
        goal_id: UUID,
        user_id: UUID,
        *,
        progress=None,
        cancelled=None,
    ) -> dict:
        """Run (or resume) a goal through the checkpointed graph.

        Scheduled executions arrive from the queue; the API calls
        the same path on demand. A crashed run (still ``running``, with a
        checkpoint) resumes from its last completed node instead of
        restarting. Always commits before returning so ``ai_generations``
        audit rows survive the request session.
        """
        from app.ai.checkpointer import get_checkpointer
        from app.ai.graphs.autopilot import (
            GraphDeps,
            build_autopilot_graph,
            collect_profile_context,
            initial_state,
        )
        from app.schemas.autopilot import ProfileUsage
        from app.services.postings.posting_fit_service import FitOverrides

        goal = await self._require_goal(user_id, goal_id)
        if goal.status != "active":
            return {"skipped": "goal is paused", "goal_id": str(goal.id)}

        run = await self._stale_running_run(goal.id)
        resume = run is not None
        if not resume:
            run = AutopilotRun(goal_id=goal.id, status=AutopilotRunStatus.RUNNING.value)
            self.db.add(run)
        await self.db.commit()
        await self.db.refresh(run)
        run_key = str(run.id) if run is not None else ""

        constraints = goal.constraints or {}
        cooldown_days = int(constraints.get("cooldown_days", 7) or 0)
        fit_overrides = FitOverrides.from_profile_usage(
            ProfileUsage.model_validate(constraints.get("profile") or {}),
            [str(value) for value in constraints.get("seniority") or []],
        )
        deps = GraphDeps(
            db=self.db,
            progress=progress,
            cancelled=cancelled,
            cooldown_ids=await self._cooldown_ids(goal.id, cooldown_days, exclude_run=run.id),
            fit_overrides=fit_overrides,
        )
        checkpointer = self._checkpointer
        if checkpointer is None:
            checkpointer = await get_checkpointer()
        graph = build_autopilot_graph(deps, checkpointer)
        config = {"configurable": {"thread_id": str(run.id)}}
        from app.ai.tracing import sink

        with (
            sink().span(
                "autopilot.run",
                {"run_id": run_key, "goal_id": str(goal.id)},
            ),
            sink().run_scope(run_key, str(goal.id)),
        ):
            try:
                if resume:
                    final = await graph.ainvoke(None, config)
                else:
                    final = await graph.ainvoke(
                        initial_state(
                            user_id=user_id,
                            goal_id=goal.id,
                            run_id=run.id,
                            goal_text=goal.goal_text,
                            constraints=constraints,
                            budget=goal.budget or {},
                            top_n=int(constraints.get("top_n") or 5),
                            cooldown_days=cooldown_days or None,
                            profile_context=await collect_profile_context(
                                self.db, user_id, constraints
                            ),
                        ),
                        config,
                    )
            except Exception as exc:
                await self._persist_failed_run(graph, config, run, exc)
                raise
        await self.db.commit()
        await self.db.refresh(run)
        await self._maybe_stale_nudge(goal)
        await self.db.commit()
        return {
            "run_id": str(run.id),
            "goal_id": str(goal.id),
            "status": run.status,
            "findings": final.get("findings") or [],
            "searches": final.get("searches") or [],
            "resumed": resume,
        }

    async def _persist_failed_run(
        self, graph, config, run: AutopilotRun | None, exc: Exception
    ) -> None:
        """Persist a run that died mid-graph, then let the exception fly.

        The trace is read from the checkpointer's last completed superstep
        (the raising node contributes no step); the run row is re-fetched
        on the rolled-back session under the run id captured before the
        invoke, so the durable steps, the ``failed`` status and the error
        commit even though the request session's uncommitted audit rows
        cannot.
        """
        run_id = run.id if run is not None else None
        await self.db.rollback()
        steps: list = []
        try:
            snapshot = await graph.aget_state(config)
            steps = list((snapshot.values or {}).get("trace_steps") or [])
        except Exception:
            logger.warning("autopilot failed-run trace recovery failed", exc_info=True)
        if run_id is None:
            return
        row = await self.db.get(AutopilotRun, run_id)
        if row is None:
            return
        row.run_steps = steps
        row.status = AutopilotRunStatus.FAILED.value
        row.error = f"{type(exc).__name__}: {exc}"[:1000]
        row.finished_at = _utcnow()
        await self.db.commit()

    async def _run_ai_calls(self, run_id: UUID) -> list[dict]:
        """The run's audited gateway calls, metadata only — never prompt or
        output text (those stay in the admin detail modal, ADR-0044 §4)."""
        from app.models.ai_model import AIGeneration

        rows = (
            (
                await self.db.execute(
                    select(AIGeneration)
                    .where(AIGeneration.run_id == run_id)
                    .order_by(AIGeneration.created_at.asc())
                )
            )
            .scalars()
            .all()
        )
        return [
            {
                "id": str(row.id),
                "task_type": row.task_type,
                "run_stage": row.run_stage,
                "provider": row.provider,
                "model": row.model,
                "status": row.status,
                "tokens_in": row.tokens_in,
                "tokens_out": row.tokens_out,
                "latency_ms": row.latency_ms,
                "prompt_version": row.prompt_version,
            }
            for row in rows
        ]

    async def run_detail(self, user_id: UUID, run_id: UUID) -> dict:
        """One run, fully inspectable: trace steps, graph nodes, AI calls
        and findings — addressed by id so runs beyond the 30-row listing
        resolve (ADR-0044 §9).

        Owner-scoped product detail, not an admin facet view: a foreign or
        missing run answer the SAME 404, the payload carries no prompt or
        output text, and there are no ledger-wide filters or export.
        """
        if isinstance(user_id, str):
            user_id = UUID(user_id)
        row = (
            (
                await self.db.execute(
                    select(AutopilotRun)
                    .join(AutopilotGoal, AutopilotGoal.id == AutopilotRun.goal_id)
                    .where(AutopilotRun.id == run_id, AutopilotGoal.user_id == user_id)
                )
            )
            .scalars()
            .first()
        )
        if row is None:
            raise NotFoundError("Autopilot run not found")
        goal = await self.db.get(AutopilotGoal, row.goal_id)
        return {
            "run": {
                **_run_out(row),
                "goal_id": str(row.goal_id),
                "goal_text": goal.goal_text if goal is not None else "",
            },
            "steps": list(row.run_steps or []),
            "nodes": execution_nodes(),
            "ai_calls": await self._run_ai_calls(row.id),
            "findings": await self._findings_out(row.id),
            "timeline": list(row.searches_executed or []),
            "trace_available": bool(row.run_steps),
        }

    async def _stale_running_run(self, goal_id: UUID) -> AutopilotRun | None:
        """A `running` row left behind by a dead worker (crash resume)."""
        rows = await self.db.execute(
            select(AutopilotRun)
            .where(
                AutopilotRun.goal_id == goal_id,
                AutopilotRun.status == AutopilotRunStatus.RUNNING.value,
            )
            .order_by(AutopilotRun.created_at.desc())
            .limit(1)
        )
        return rows.scalars().first()

    async def _cooldown_ids(self, goal_id: UUID, cooldown_days: int, *, exclude_run) -> set[str]:
        """Posting ids this goal already surfaced inside the cooldown
        window — a surfaced posting isn't re-surfaced for N days."""
        if not cooldown_days:
            return set()
        cutoff_dt = _utcnow() - timedelta(days=cooldown_days)
        rows = await self.db.execute(
            select(AutopilotFinding.posting_id)
            .join(AutopilotRun, AutopilotRun.id == AutopilotFinding.run_id)
            .where(
                AutopilotRun.goal_id == goal_id,
                AutopilotRun.id != exclude_run,
                AutopilotFinding.created_at >= cutoff_dt,
            )
        )
        return {str(pid) for pid in rows.scalars().all()}

    async def _maybe_stale_nudge(self, goal: AutopilotGoal) -> None:
        """Nudge after N consecutive zero-finding runs (pausing stays
        manual — the inverse of pause-on-dismissal)."""
        run_ids = (
            (
                await self.db.execute(
                    select(AutopilotRun.id)
                    .where(
                        AutopilotRun.goal_id == goal.id,
                        AutopilotRun.status.in_(
                            [
                                AutopilotRunStatus.COMPLETED.value,
                                AutopilotRunStatus.BUDGET_ABORTED.value,
                            ]
                        ),
                    )
                    .order_by(AutopilotRun.created_at.desc())
                    .limit(STALE_STREAK)
                )
            )
            .scalars()
            .all()
        )
        if len(run_ids) < STALE_STREAK:
            return
        for run_id in run_ids:
            count = len(await self._findings_out(run_id))
            if count:
                return
        await self._emit_stale_nudge(goal, streak=len(run_ids))

    # ------------------------------------------------------------- output

    async def _last_run_out(self, goal_id: UUID) -> dict | None:
        rows = await self.db.execute(
            select(AutopilotRun)
            .where(AutopilotRun.goal_id == goal_id)
            .order_by(AutopilotRun.created_at.desc())
            .limit(1)
        )
        run = rows.scalars().first()
        return _run_out(run) if run is not None else None

    async def _open_finding_count(self, goal_id: UUID) -> int:
        rows = await self.db.execute(
            select(AutopilotFinding.id)
            .join(AutopilotRun, AutopilotRun.id == AutopilotFinding.run_id)
            .where(
                AutopilotRun.goal_id == goal_id,
                AutopilotFinding.dismissed_at.is_(None),
            )
        )
        return len(rows.scalars().all())


def _goal_out(goal: AutopilotGoal) -> dict:
    return {
        "id": str(goal.id),
        "goal_text": goal.goal_text,
        "constraints": goal.constraints or {},
        "budget": goal.budget or {},
        "cadence": goal.cadence,
        "status": goal.status,
        "last_run_at": goal.last_run_at,
        "created_at": goal.created_at,
        "updated_at": goal.updated_at,
    }


def _run_out(run: AutopilotRun) -> dict:
    return {
        "id": str(run.id),
        "status": run.status,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "tokens_used": run.tokens_used,
        "searches_executed": run.searches_executed or [],
        "error": run.error,
        "created_at": run.created_at,
    }


def _salary_out(posting) -> dict | None:
    if posting.salary_min is None and posting.salary_max is None:
        return None
    return {
        "currency": posting.salary_currency,
        "min": float(posting.salary_min) if posting.salary_min is not None else None,
        "max": float(posting.salary_max) if posting.salary_max is not None else None,
        "period": posting.salary_period,
    }


def _coverage_hits_clause(db: AsyncSession) -> ColumnElement:
    """The finding's must-coverage hits as an integer, dialect-split
    (``->``/``->>`` on Postgres, ``json_extract`` on SQLite). Findings
    without a must_coverage block yield NULL — they never match a
    ``coverage_min``."""
    if db.get_bind().dialect.name == "sqlite":
        return sa_cast(
            func.json_extract(AutopilotFinding.evidence, "$.must_coverage.hits"), Integer
        )
    return sa_cast(AutopilotFinding.evidence.op("->")("must_coverage").op("->>")("hits"), Integer)


def _feed_conditions(
    db: AsyncSession,
    *,
    goal_id: UUID | None,
    run_id: UUID | None,
    state: str | None,
    min_score: float | None,
    coverage_min: int | None,
    org: str | None,
    source: str | None,
    seniority: str | None,
    remote: bool,
    posted_within: str | None,
) -> list[Any]:
    """The feed's WHERE clauses; the facet pass re-invokes it with one
    dimension nulled (self-excluding counts, the explore pattern)."""
    from app.models.posting_model import JobPosting, JobSource
    from app.services.analytics.time_buckets import POSTED_WINDOWS, window_clause

    conditions: list[Any] = []
    if goal_id is not None:
        conditions.append(AutopilotRun.goal_id == goal_id)
    if run_id is not None:
        conditions.append(AutopilotFinding.run_id == run_id)
    if state == "open":
        conditions.append(AutopilotFinding.dismissed_at.is_(None))
    elif state == "dismissed":
        conditions.append(AutopilotFinding.dismissed_at.is_not(None))
    if min_score is not None:
        conditions.append(AutopilotFinding.score >= min_score)
    if coverage_min is not None:
        conditions.append(_coverage_hits_clause(db) >= coverage_min)
    if org:
        conditions.append(JobPosting.org.ilike(f"%{org}%"))
    if source:
        conditions.append(JobSource.key == source)
    if seniority:
        conditions.append(JobPosting.seniority == seniority)
    if remote:
        conditions.append(JobPosting.onsite_policy == "remote")
    if posted_within:
        if posted_within not in POSTED_WINDOWS:
            raise ValidationError("posted_within must be one of: " + ", ".join(POSTED_WINDOWS))
        conditions.append(window_clause(posted_within, _utcnow()))
    return conditions


def _encode_feed_cursor(sort: str, key: datetime | float, finding_id: UUID) -> str:
    payload = {
        "s": sort,
        "k": key.isoformat() if isinstance(key, datetime) else key,
        "id": str(finding_id),
    }
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()


def _decode_feed_cursor(cursor: str) -> tuple[str, datetime | float, UUID]:
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor.encode()))
        key = payload["k"]
        if isinstance(key, str):
            key = datetime.fromisoformat(key)
        return payload["s"], key, UUID(payload["id"])
    except Exception as exc:
        raise ValidationError("Invalid pagination cursor") from exc
