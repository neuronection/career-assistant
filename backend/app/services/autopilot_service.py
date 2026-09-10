"""Career Autopilot service: goal lifecycle + run orchestration.

The agentic work lives in the LangGraph flow (``app.ai.graphs.autopilot``);
this service owns the durable decisions around it: goal CRUD with cadence
schedules, the on-demand/scheduled run entry point,
checkpoint resume of interrupted runs, constraint learning from feedback,
pause-on-total-dismissal and the stale-goal nudge. Applying to a posting
is never automated — findings are suggestions only.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
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
)

logger = logging.getLogger(__name__)

STALE_STREAK = 3


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AutopilotService:
    def __init__(self, db: AsyncSession, checkpointer=None):
        self.db = db
        self._checkpointer = checkpointer

    # -------------------------------------------------------------- goals

    async def create_goal(
        self, user_id: UUID, data: AutopilotGoalCreate
    ) -> AutopilotGoal:
        """Create a goal; an optional cadence attaches a schedule."""
        from app.services.scheduler.runner import SchedulerService
        from app.services.scheduler import triggers as trigger_registry

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
            await SchedulerService(self.db).set_autopilot_schedule(
                user_id, goal.id, data.cadence
            )
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
        payload = data.model_dump(
            exclude_none=True, exclude={"cadence", "remove_cadence"}
        )
        if "constraints" in payload:
            constraints = AutopilotConstraints.model_validate(
                payload.pop("constraints")
            )
            goal.constraints = constraints.model_dump(mode="json")
        if "budget" in payload:
            goal.budget = AutopilotBudget.model_validate(
                payload.pop("budget")
            ).model_dump(mode="json", exclude_none=True)
        for field, value in payload.items():
            setattr(goal, field, value)
        if data.remove_cadence:
            await SchedulerService(self.db).set_autopilot_schedule(
                user_id, goal.id, None
            )
        elif data.cadence is not None:
            await SchedulerService(self.db).set_autopilot_schedule(
                user_id, goal.id, data.cadence
            )
        await self.db.commit()
        await self.db.refresh(goal)
        return goal

    async def delete_goal(self, user_id: UUID, goal_id: UUID) -> None:
        """Delete a goal with its runs/findings and cadence schedule."""
        from app.models.schedule_model import Schedule
        from app.models.enums import ScheduleKind

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
            never = [
                t for t in constraints.get("never_terms") or [] if t not in learned
            ]
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

    async def _learn_terms(
        self, finding: AutopilotFinding, *, avoid: bool
    ) -> list[str]:
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
            initial_state,
        )

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

        constraints = goal.constraints or {}
        cooldown_days = int(constraints.get("cooldown_days", 7) or 0)
        deps = GraphDeps(
            db=self.db,
            progress=progress,
            cancelled=cancelled,
            cooldown_ids=await self._cooldown_ids(
                goal.id, cooldown_days, exclude_run=run.id
            ),
        )
        checkpointer = self._checkpointer
        if checkpointer is None:
            checkpointer = await get_checkpointer()
        graph = build_autopilot_graph(deps, checkpointer)
        config = {"configurable": {"thread_id": str(run.id)}}
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
                ),
                config,
            )
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

    async def _stale_running_run(self, goal_id: UUID) -> Optional[AutopilotRun]:
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

    async def _cooldown_ids(
        self, goal_id: UUID, cooldown_days: int, *, exclude_run
    ) -> set[str]:
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

    async def _last_run_out(self, goal_id: UUID) -> Optional[dict]:
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
