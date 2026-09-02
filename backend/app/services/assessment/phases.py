"""Phase pipeline registry (Phase 23).

Each phase is a small class: `build_questions(run, ctx)` produces the
phase's question batch and `score(run, answers)` folds answered deltas
into run-level derived state. The shared runner (runner.py) walks
`run.phase_order` — plan-37 templates compile onto these phases.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.assessment_model import AssessmentQuestion
from app.models.enums import QuestionSource

if TYPE_CHECKING:
    from app.models.assessment_model import AssessmentRun

# Soft anti-fatigue cap: question batches never exceed this.
MAX_QUESTIONS_PER_PHASE = 15

PHASE_IDS = (1, 2, 3, 4)
PHASE_TITLES = {
    1: "Profile foundation",
    2: "Standardized scenarios",
    3: "AI scenarios",
    4: "Personalized selection",
}


class Phase:
    """Contract: phase_number, build_questions(run, ctx), score(run, answers)."""

    phase_number: int = 0

    async def build_questions(
        self, db: AsyncSession, run: "AssessmentRun", ctx: dict
    ) -> list[AssessmentQuestion]:
        raise NotImplementedError

    async def score(
        self,
        db: AsyncSession,
        run: "AssessmentRun",
        answers: list[dict],
        derived: dict,
    ) -> dict:
        return derived


class ProfileFoundation(Phase):
    """Phase 1 — form reuse of the onboarding sections; no engine questions.

    The wizard renders the existing profile forms; advancing past this
    phase just records completion (the sections were written via the
    normal profile endpoints).
    """

    phase_number = 1

    async def build_questions(
        self, db: AsyncSession, run: "AssessmentRun", ctx: dict
    ) -> list[AssessmentQuestion]:
        return []

    async def score(
        self,
        db: AsyncSession,
        run: "AssessmentRun",
        answers: list[dict],
        derived: dict,
    ) -> dict:
        derived.setdefault("profile_sections", []).append("basics")
        return derived


class StandardScenarios(Phase):
    """Phase 2 — seeded bank: scenario MCQs + time allocations + rankings.

    Bank rows carry `audience_stages` (Phase 25); empty targets every
    stage, so a student sees campus scenarios and a returner sees
    re-entry ones from the same bank.
    """

    phase_number = 2

    async def build_questions(
        self, db: AsyncSession, run: "AssessmentRun", ctx: dict
    ) -> list[AssessmentQuestion]:
        from app.services.stages_service import stage_for_user

        stage, _source = await stage_for_user(db, run.user_id)
        rows = (
            (
                await db.execute(
                    select(AssessmentQuestion)
                    .where(
                        AssessmentQuestion.run_id.is_(None),
                        AssessmentQuestion.phase == self.phase_number,
                        AssessmentQuestion.status == "active",
                    )
                    .order_by(AssessmentQuestion.sort_index)
                )
            )
            .scalars()
            .all()
        )
        eligible = [
            q
            for q in rows
            if not q.audience_stages or stage.value in (q.audience_stages or [])
        ][:MAX_QUESTIONS_PER_PHASE]
        return [_clone_for_run(db, run, q) for q in eligible]


class AIScenarios(Phase):
    """Phase 3 — the assessment_designer agent drafts personalized questions.

    Output is pydantic-validated onto taxonomy keys; if generation fails
    structurally twice the phase degrades to extra bank questions (the
    run never breaks because the model had a bad day).
    """

    phase_number = 3

    async def build_questions(
        self, db: AsyncSession, run: "AssessmentRun", ctx: dict
    ) -> list[AssessmentQuestion]:
        from app.ai.agents.assessment_designer import generate_question_set
        from app.services.profile_service import ProfileService
        from app.services.taxonomy_service import TaxonomyService

        profile = await ProfileService(db).get(run.user_id)
        snapshot = await ProfileService(db).snapshot(profile)
        top_families = await _top_families(db, run.user_id)
        skills = await TaxonomyService(db).skills(status="active")
        skill_keys = [s.key for s in skills]
        from app.services.stages_service import stage_for_user

        stage, _source = await stage_for_user(db, run.user_id)

        try:
            question_set = await generate_question_set(
                db,
                run.user_id,
                snapshot,
                top_families,
                skill_keys,
                stage=stage.value,
            )
        except Exception:  # noqa: BLE001 — degrade, never break the run
            return await _bank_fallback(db, run, stage)

        items = question_set.model_dump(mode="json").get("questions") or []
        active_keys = set(skill_keys)
        created: list[AssessmentQuestion] = []
        for index, item in enumerate(items[:10]):
            options = []
            for option in item.get("options") or []:
                scores = option.get("scores") or {}
                clean_scores: dict = {
                    "skill_levels": {
                        key: value
                        for key, value in (scores.get("skill_levels") or {}).items()
                        if key in active_keys
                    },
                    "interest_keys": list(scores.get("interest_keys") or []),
                }
                options.append(
                    {
                        "id": f"o{len(options) + 1}",
                        "label": option.get("label") or "",
                        "detail": option.get("detail") or "",
                        "scores": clean_scores,
                    }
                )
            if len(options) < 2:
                continue
            question = AssessmentQuestion(
                run_id=run.id,
                phase=self.phase_number,
                kind="scenario_mcq",
                prompt=item.get("prompt") or "",
                help=item.get("help") or "",
                options=options,
                source=QuestionSource.AI.value,
                sort_index=index,
            )
            db.add(question)
            created.append(question)
        if not created:
            return await _bank_fallback(db, run)
        await db.flush()
        return created


class TemplateQuestions(Phase):
    """Plan-37 phases — template content materialized as ordinary
    questions. Engine phase numbers 5+ map to template phase index n−5;
    scoring rides the shared kind handlers exactly like phase 2."""

    def __init__(self, template_index: int):
        self.template_index = template_index
        self.phase_number = 5 + template_index

    def _questions(self, ctx: dict) -> list[dict]:
        content = (ctx or {}).get("template_content") or {}
        phases = content.get("phases") or []
        if self.template_index >= len(phases):
            return []
        return phases[self.template_index].get("questions") or []

    async def build_questions(
        self, db: AsyncSession, run: "AssessmentRun", ctx: dict
    ) -> list[AssessmentQuestion]:
        from app.models.enums import QuestionSource

        created: list[AssessmentQuestion] = []
        for index, spec in enumerate(self._questions(ctx)[:MAX_QUESTIONS_PER_PHASE]):
            config = {
                key: spec[key]
                for key in (
                    "statements",
                    "min_select",
                    "max_select",
                    "numeric_min",
                    "numeric_max",
                    "numeric_unit",
                    "skill_key",
                    "per_unit",
                    "cap",
                    "constraint_key",
                )
                if spec.get(key) is not None
            }
            question = AssessmentQuestion(
                run_id=run.id,
                phase=self.phase_number,
                kind=spec.get("kind") or "scenario_mcq",
                prompt=spec.get("prompt") or "",
                help=spec.get("help") or "",
                options=spec.get("options") or [],
                time_split=config,
                source=QuestionSource.BANK.value,
                sort_index=index,
            )
            db.add(question)
            created.append(question)
        if created:
            await db.flush()
        return created

    def phase_title(self, ctx: dict) -> str:
        titles = (ctx or {}).get("phase_titles") or {}
        return titles.get(str(self.phase_number)) or "Template phase"


def resolve_phase(phase_number: int, ctx: dict | None = None) -> Phase:
    """Registry lookup; plan-37 template phases (5+) compile on demand."""
    if phase_number in PHASE_REGISTRY:
        return PHASE_REGISTRY[phase_number]()
    if phase_number >= 5:
        return TemplateQuestions(phase_number - 5)
    raise KeyError(f"unknown phase: {phase_number}")


def phase_title_for(run: "AssessmentRun", phase_number: int) -> str:
    """Title lookup: engine phases by number, template phases by context."""
    if phase_number >= 5:
        titles = (run.context or {}).get("phase_titles") or {}
        return titles.get(str(phase_number), "Template phase")
    return PHASE_TITLES.get(phase_number, "")


class PersonalizedSelection(Phase):
    """Phase 4 — user picks categories + specific jobs to target."""

    phase_number = 4

    async def build_questions(
        self, db: AsyncSession, run: "AssessmentRun", ctx: dict
    ) -> list[AssessmentQuestion]:
        from app.services.job_service import JobService

        job_service = JobService(db)
        jobs, _ = await job_service.list_jobs(page_size=200)
        questions: list[AssessmentQuestion] = []

        options = [
            {
                "id": f"job:{job.code}",
                "label": job.title,
                "detail": job.short_description,
                "scores": {
                    "interest_keys": [link.tag.key for link in job.tag_links][:3]
                },
            }
            for job in jobs[:12]
        ]
        questions.append(
            AssessmentQuestion(
                run_id=run.id,
                phase=self.phase_number,
                kind="time_allocation",
                prompt="How would you split 100 points of curiosity across these job types?",
                help="Slide each row; the total must be exactly 100 — or skip.",
                options=options,
                time_split={"style": "allocation"},
                source=QuestionSource.BANK.value,
                sort_index=0,
            )
        )
        for job in jobs[:5]:
            questions.append(
                AssessmentQuestion(
                    run_id=run.id,
                    phase=self.phase_number,
                    kind="slider",
                    prompt=f"How drawn do you feel to a career as a {job.title}?",
                    help="1 = not at all, 10 = this is the dream",
                    options=[],
                    time_split={
                        "skill_key": "",
                        "job_code": job.code,
                        "interest_keys": [link.tag.key for link in job.tag_links][:3],
                    },
                    source=QuestionSource.BANK.value,
                    sort_index=len(questions),
                )
            )
        return questions

    async def score(
        self,
        db: AsyncSession,
        run: "AssessmentRun",
        answers: list[dict],
        derived: dict,
    ) -> dict:
        selection = derived.setdefault("selection", {})
        for item in answers:
            question = item.get("question") or {}
            job_code = (question.get("time_split") or {}).get("job_code")
            if not job_code:
                continue
            value = (item.get("answer") or {}).get("value")
            if value is None:
                continue
            selection[job_code] = int(value)
        return derived


def _clone_for_run(
    db: AsyncSession, run: "AssessmentRun", question: AssessmentQuestion
) -> AssessmentQuestion:
    """Materialize a bank question as a run-scoped copy (answers need a run)."""
    clone = AssessmentQuestion(
        run_id=run.id,
        phase=question.phase,
        kind=question.kind,
        prompt=question.prompt,
        help=question.help,
        options=question.options,
        time_split=question.time_split,
        audience_stages=question.audience_stages,
        source=question.source,
        sort_index=question.sort_index,
    )
    db.add(clone)
    return clone


async def _bank_fallback(db: AsyncSession, run: "AssessmentRun", stage=None) -> list:
    from app.models.enums import CareerStage

    if isinstance(stage, str):
        stage = CareerStage(stage)
    rows = (
        (
            await db.execute(
                select(AssessmentQuestion)
                .where(
                    AssessmentQuestion.run_id.is_(None),
                    AssessmentQuestion.status == "active",
                )
                .order_by(AssessmentQuestion.sort_index)
                .limit(12)
            )
        )
        .scalars()
        .all()
    )
    if stage is not None:
        rows = [
            q
            for q in rows
            if not q.audience_stages or stage.value in (q.audience_stages or [])
        ]
    clones = []
    for index, question in enumerate(rows[:6]):
        clone = _clone_for_run(db, run, question)
        clone.phase = 3
        clone.sort_index = index
        clones.append(clone)
    await db.flush()
    return clones


async def _top_families(db: AsyncSession, user_id, limit: int = 5) -> list[str]:
    """Top job families by stored fit — feeds AI personalization."""
    from sqlalchemy import func

    from app.models.matching_model import MatchInsight

    rows = await db.execute(
        select(MatchInsight.job_id)
        .where(
            MatchInsight.user_id == user_id,
            MatchInsight.fit_score.is_not(None),
        )
        .order_by(MatchInsight.fit_score.desc())
        .limit(limit * 4)
    )
    job_ids = [row[0] for row in rows.all()]
    if not job_ids:
        return []
    from app.models.job_model import Job, JobFamily

    family_rows = await db.execute(
        select(JobFamily.key, func.count(Job.id))
        .join(Job, Job.family_id == JobFamily.id)
        .where(Job.id.in_(job_ids))
        .group_by(JobFamily.key)
        .order_by(func.count(Job.id).desc())
        .limit(limit)
    )
    return [row[0] for row in family_rows.all()]


PHASE_REGISTRY: dict[int, type[Phase]] = {
    1: ProfileFoundation,
    2: StandardScenarios,
    3: AIScenarios,
    4: PersonalizedSelection,
}


def phases_for_order(order: list[int]) -> list[Any]:
    return [PHASE_REGISTRY[number]() for number in order]
