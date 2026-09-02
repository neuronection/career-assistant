"""Assessment pipeline runner: create, answer, advance, reconcile, results."""

import uuid
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import NotFoundError, ValidationError
from app.models.assessment_model import (
    AssessmentAnswer,
    AssessmentQuestion,
    AssessmentRun,
)
from app.models.enums import AssessmentKind, AssessmentStatus
from app.services.assessment.phases import (
    phase_title_for,
    resolve_phase,
)
from app.services.assessment.question_kinds import handler_for
from app.services.fit.service import FitService

DEFAULT_ORDER = [1, 2, 3, 4]
CUSTOM_ORDER = [2, 3, 4]


class AssessmentService:
    """Runs the 4-phase pipeline for one user (resumable, save-on-answer)."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_run(
        self, user_id: UUID, kind: str, context: dict | None = None
    ) -> AssessmentRun:
        if kind not in {k.value for k in AssessmentKind}:
            raise ValidationError(f"Unknown assessment kind: {kind}")
        context = context or {}
        if kind == AssessmentKind.CUSTOM.value:
            order = [
                p
                for p in (context.get("phase_order") or CUSTOM_ORDER)
                if p in CUSTOM_ORDER
            ]
            if not order:
                order = list(CUSTOM_ORDER)
            context.setdefault("source_run_id", None)
        elif kind == AssessmentKind.TEMPLATE.value:
            # Plan 37: template phases are engine slots 5+ (one per content
            # phase); the materializer reads context.template_content.
            order = [
                p
                for p in (context.get("phase_order") or [])
                if isinstance(p, int) and p >= 5
            ]
            if not order:
                raise ValidationError(
                    "A template run needs a phase_order of engine slots 5+"
                )
            if not context.get("template_content"):
                raise ValidationError("A template run needs template_content")
        else:
            order = list(DEFAULT_ORDER)
        existing = (
            (
                await self.db.execute(
                    select(AssessmentRun).where(
                        AssessmentRun.user_id == user_id,
                        AssessmentRun.status == AssessmentStatus.IN_PROGRESS.value,
                    )
                )
            )
            .scalars()
            .all()
        )
        for stale in existing:
            stale.status = AssessmentStatus.ABANDONED.value
        run = AssessmentRun(
            user_id=user_id,
            kind=kind,
            phase_order=order,
            context=context,
            current_phase=order[0],
            progress={},
        )
        self.db.add(run)
        await self.db.flush()
        await self._materialize_phase(run, run.current_phase)
        await self.db.commit()
        return await self.get_run(run.id, user_id)

    async def get_run(self, run_id: UUID, user_id: UUID) -> AssessmentRun:
        rows = await self.db.execute(
            select(AssessmentRun)
            .options(
                selectinload(AssessmentRun.questions),
                selectinload(AssessmentRun.answers),
            )
            .where(AssessmentRun.id == run_id, AssessmentRun.user_id == user_id)
        )
        run = rows.scalars().unique().first()
        if run is None:
            raise NotFoundError("Assessment run not found")
        return run

    async def history(self, user_id: UUID) -> list[AssessmentRun]:
        rows = await self.db.execute(
            select(AssessmentRun)
            .where(AssessmentRun.user_id == user_id)
            .order_by(AssessmentRun.created_at.desc())
        )
        return list(rows.scalars().all())

    async def state(self, run: AssessmentRun) -> dict:
        """Run state + the current phase's unanswered questions."""
        answered_ids = {a.question_id for a in run.answers}
        questions = [
            q
            for q in sorted(run.questions, key=lambda q: q.sort_index)
            if q.phase == run.current_phase and q.id not in answered_ids
        ]
        progress = self._progress(run)
        return {
            "id": str(run.id),
            "kind": run.kind,
            "status": run.status,
            "phase_order": run.phase_order,
            "current_phase": run.current_phase,
            "phase_title": phase_title_for(run, run.current_phase),
            "progress": progress,
            "context": run.context,
            "phase_one_form": run.current_phase == 1,
            "questions": [self._question_out(q) for q in questions],
        }

    @staticmethod
    def _question_out(question: AssessmentQuestion) -> dict:
        return {
            "id": str(question.id),
            "phase": question.phase,
            "kind": question.kind,
            "prompt": question.prompt,
            "help": question.help,
            "options": question.options or [],
            "time_split": question.time_split,
            "source": question.source,
        }

    @staticmethod
    def _progress(run: AssessmentRun) -> dict:
        progress = {}
        for phase in run.phase_order:
            questions = [q for q in run.questions if q.phase == phase]
            answered = [a for a in run.answers if _phase_of(run, a) == phase]
            progress[str(phase)] = {
                "answered": len(answered),
                "total": len(questions),
                "title": phase_title_for(run, phase),
            }
        return progress

    async def submit_answers(self, run: AssessmentRun, answers: list[dict]) -> dict:
        """Batch save-on-answer; per-kind validation + derived deltas."""
        if run.status != AssessmentStatus.IN_PROGRESS.value:
            raise ValidationError("Run is not active")
        question_map = {q.id: q for q in run.questions}
        saved = 0
        for item in answers or []:
            question_id = item.get("question_id")
            question = question_map.get(_as_uuid(question_id))
            if question is None:
                raise ValidationError(f"Unknown question: {question_id}")
            if question.phase != run.current_phase:
                raise ValidationError(
                    f"Question {question_id} is not in the current phase"
                )
            raw = item.get("answer")
            if raw is None or raw == {}:
                await self._record_skip(run, question)
                continue
            handler = handler_for(question.kind)
            validated = handler.validate(
                {"options": question.options, "time_split": question.time_split},
                raw,
            )
            derived = handler.derive(
                {"options": question.options, "time_split": question.time_split},
                validated,
            )
            existing = (
                (
                    await self.db.execute(
                        select(AssessmentAnswer).where(
                            AssessmentAnswer.run_id == run.id,
                            AssessmentAnswer.question_id == question.id,
                        )
                    )
                )
                .scalars()
                .first()
            )
            if existing is None:
                existing = AssessmentAnswer(run_id=run.id, question_id=question.id)
                self.db.add(existing)
            existing.answer = validated
            existing.derived = derived
            saved += 1
        await self.db.commit()
        return {"saved": saved}

    async def _record_skip(
        self, run: AssessmentRun, question: AssessmentQuestion
    ) -> None:
        """A skip removes any prior answer — skips contribute nothing."""
        await self.db.execute(
            delete(AssessmentAnswer).where(
                AssessmentAnswer.run_id == run.id,
                AssessmentAnswer.question_id == question.id,
            )
        )

    async def advance(self, run: AssessmentRun, user_id: UUID) -> dict:
        """Score the current phase and move to the next (or complete)."""
        if run.status != AssessmentStatus.IN_PROGRESS.value:
            raise ValidationError("Run is not active")
        phase_answers = [
            {
                "question": {"id": q.id, "time_split": q.time_split},
                "answer": self._answer_of(run, q),
            }
            for q in run.questions
            if q.phase == run.current_phase and self._answer_of(run, q) is not None
        ]
        phase = resolve_phase(run.current_phase, run.context)
        derived = await self._derived_map(run)
        derived = await phase.score(self.db, run, phase_answers, derived)
        # Phase outputs are run-scoped state (plan 23: context stores state;
        # plan-37 templates read the same slot).
        run.context = {**(run.context or {}), "derived_state": derived}

        position = run.phase_order.index(run.current_phase)
        if position + 1 < len(run.phase_order):
            run.current_phase = run.phase_order[position + 1]
            await self._materialize_phase(run, run.current_phase)
            run.progress = self._progress(run)
            await self.db.commit()
            return {"status": run.status, "current_phase": run.current_phase}

        run.status = AssessmentStatus.COMPLETED.value
        run.progress = self._progress(run)
        await self.db.commit()
        effects = await self._apply_results(run, derived)
        return {
            "status": run.status,
            "effects": effects,
        }

    async def cancel(self, run: AssessmentRun) -> dict:
        run.status = AssessmentStatus.ABANDONED.value
        await self.db.commit()
        return {"status": run.status}

    async def _derived_map(self, run: AssessmentRun) -> dict:
        merged: dict = {"skill_levels": {}, "interest_keys": []}
        stored = (run.context or {}).get("derived_state") or {}
        if stored.get("selection"):
            merged["selection"] = dict(stored["selection"])
        for answer in run.answers:
            for key, value in (answer.derived or {}).items():
                if key == "skill_levels":
                    for skill_key, level in value.items():
                        merged["skill_levels"][skill_key] = level
                elif key == "interest_keys":
                    merged["interest_keys"].extend(value)
                elif key == "selection":
                    merged.setdefault("selection", {}).update(value)
                elif key == "profile_sections":
                    merged.setdefault("profile_sections", []).extend(value)
        return merged

    def _answer_of(self, run: AssessmentRun, question) -> dict | None:
        for answer in run.answers:
            if answer.question_id == question.id:
                return answer.answer
        return None

    async def _materialize_phase(self, run: AssessmentRun, phase_number: int) -> None:
        """Questions for a phase exist exactly once per run."""
        existing = (
            await self.db.execute(
                select(AssessmentQuestion.id)
                .where(
                    AssessmentQuestion.run_id == run.id,
                    AssessmentQuestion.phase == phase_number,
                )
                .limit(1)
            )
        ).scalar()
        if existing:
            return
        phase = resolve_phase(phase_number, run.context)
        built = await phase.build_questions(self.db, run, run.context or {})
        for question in built:
            self.db.add(question)
        await self.db.flush()

    async def _apply_results(self, run: AssessmentRun, derived: dict) -> dict:
        """Completion effects: skills upsert (conflict-aware), interests,
        shortlist enqueue (fit already exists — refresh + AI rationale).

        Plan-37 template runs normalize their accumulated raw deltas
        through the template's own block first; every applied skill gains
        a `skill_evidence` row linking the run (plan-42.A ledger)."""
        from app.models.enums import BackgroundJobType
        from app.models.user_model import UserSkill
        from app.services.job_worker import enqueue

        applied_skills = 0
        conflicts = []
        selection = derived.get("selection") or {}
        band = None

        if run.kind == AssessmentKind.TEMPLATE.value and run.template_id:
            from app.services.assessment_templates import TemplateService

            compiled = await TemplateService(self.db).compile_results(run)
            band = compiled["band"]
            derived = {
                **derived,
                "skill_levels": compiled["levels"],
                "interest_keys": compiled["interest_keys"],
            }
        interest_keys = sorted(set(derived.get("interest_keys") or []))

        skill_levels = derived.get("skill_levels") or {}
        evidence_linked = run.template_id is not None
        if skill_levels:
            from app.models.taxonomy_model import Skill

            keys = list(skill_levels.keys())
            skill_rows = {
                s.key: s
                for s in (
                    await self.db.execute(select(Skill).where(Skill.key.in_(keys)))
                )
                .scalars()
                .all()
            }
            existing_rows = {
                row.skill_id: row
                for row in (
                    await self.db.execute(
                        select(UserSkill).where(UserSkill.user_id == run.user_id)
                    )
                )
                .scalars()
                .all()
            }
            for key, level in skill_levels.items():
                skill = skill_rows.get(key)
                if skill is None:
                    continue
                level = int(round(float(level)))
                existing = existing_rows.get(skill.id)
                if existing is not None:
                    if abs(existing.level - level) > 2:
                        conflicts.append(
                            {
                                "key": key,
                                "self_level": existing.level,
                                "assessed_level": level,
                            }
                        )
                        continue
                    existing.level = level
                    existing.source = "assessment"
                    applied_skills += 1
                else:
                    self.db.add(
                        UserSkill(
                            user_id=run.user_id,
                            skill_id=skill.id,
                            level=level,
                            source="assessment",
                            confidence=0.8,
                        )
                    )
                    applied_skills += 1
                if evidence_linked:
                    from app.models.experience_model import SkillEvidence
                    from datetime import datetime, timezone as tz

                    self.db.add(
                        SkillEvidence(
                            user_id=run.user_id,
                            skill_id=skill.id,
                            assessment_run_id=run.id,
                            note="template run",
                            level_value=float(level),
                            confidence=0.8,
                            claimed_at=datetime.now(tz.utc),
                        )
                    )

        if interest_keys:
            from app.services.profile_service import ProfileService

            rows = await ProfileService(self.db).interest_rows(run.user_id)
            existing_keys = {row.tag.key for row in rows}
            payload = [
                {"tag_key": row.tag.key, "weight": row.weight, "source": row.source}
                for row in rows
            ]
            for key in interest_keys:
                if key not in existing_keys:
                    payload.append({"tag_key": key, "weight": 3, "source": "ai"})
            await ProfileService(self.db)._write_interests(run.user_id, payload)

        await self.db.commit()

        queued = await enqueue(
            self.db,
            BackgroundJobType.MATCH_SCORE.value,
            {"limit": 10},
            user_id=run.user_id,
        )
        await FitService(self.db).refit_user(run.user_id)
        return {
            "applied_skills": applied_skills,
            "skill_conflicts": conflicts,
            "interest_keys": interest_keys,
            "selection": selection,
            "rationale_job_id": str(queued.id),
            "band": band,
        }

    async def results(self, run: AssessmentRun) -> dict:
        """Derived profile delta + shortlist (diffable across runs)."""
        derived = await self._derived_map(run)
        skills = sorted(derived.get("skill_levels", {}).items())
        shortlist = []
        if run.status == AssessmentStatus.COMPLETED.value:
            from app.models.matching_model import MatchInsight

            rows = await self.db.execute(
                select(MatchInsight.job_id, MatchInsight.fit_score)
                .where(
                    MatchInsight.user_id == run.user_id,
                    MatchInsight.fit_score.is_not(None),
                )
                .order_by(MatchInsight.fit_score.desc())
                .limit(10)
            )
            shortlist = [
                {"job_id": str(job_id), "fit_score": float(score)}
                for job_id, score in rows.all()
            ]
        return {
            "run_id": str(run.id),
            "kind": run.kind,
            "status": run.status,
            "skill_levels": [{"key": k, "level": v} for k, v in skills],
            "interest_keys": sorted(set(derived.get("interest_keys") or [])),
            "selection": derived.get("selection") or {},
            "shortlist": shortlist,
        }

    async def assist(self, run: AssessmentRun, question_id: str) -> str:
        """Per-question helper reusing the quick-assist agent (audited)."""
        from app.ai.agents.chatbot import quick_assist

        question = next((q for q in run.questions if str(q.id) == question_id), None)
        if question is None:
            raise NotFoundError("Question not found in this run")
        reply = await quick_assist(
            self.db,
            run.user_id,
            question=f"{question.prompt}\n\n{question.help or ''}",
            page="assessment",
            job_code=None,
            profile_summary="",
        )
        return reply.answer


def _as_uuid(value) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None


def _phase_of(run: AssessmentRun, answer: AssessmentAnswer) -> int | None:
    for question in run.questions:
        if question.id == answer.question_id:
            return question.phase
    return None
