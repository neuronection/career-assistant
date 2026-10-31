"""Career Autopilot service: goal lifecycle + run orchestration.

The agentic work lives in the LangGraph flow (``app.ai.graphs.autopilot``);
this service owns the durable decisions around it: goal CRUD with cadence
schedules, the on-demand/scheduled run entry point,
checkpoint resume of interrupted runs, constraint learning from feedback,
pause-on-total-dismissal and the stale-goal nudge. Applying to a posting
is never automated — findings are suggestions only.
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import NotFoundError, PermissionDeniedError
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

    async def findings_by_run(self, user_id: UUID) -> list[dict]:
        """The user's runs across goals, newest first, findings attached."""
        rows = (
            (
                await self.db.execute(
                    select(AutopilotRun)
                    .join(AutopilotGoal, AutopilotGoal.id == AutopilotRun.goal_id)
                    .where(AutopilotGoal.user_id == user_id)
                    .order_by(AutopilotRun.created_at.desc())
                    .limit(30)
                )
            )
            .scalars()
            .all()
        )
        out = []
        for run in rows:
            out.append(
                {
                    **_run_out(run),
                    "goal_id": str(run.goal_id),
                    "findings": await self._findings_out(run.id),
                }
            )
        return out

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
