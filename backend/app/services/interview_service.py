"""Interview practice service: session lifecycle over the
model + the plan-generation agent.

Honesty guards: the plan draft is user-editable before practice starts;
the archetype path needs no postings; ownership is enforced on every
read/write (cross-user access is a 403, the chat-endpoint convention).
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, ValidationError
from app.models.enums import InterviewStatus
from app.models.interview_model import InterviewSession
from app.schemas.interview import (
    InterviewPlanPatch,
    InterviewPlan,
    InterviewSessionCreate,
)


class InterviewService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def _get_owned(
        self, user_id: uuid.UUID, session_id: uuid.UUID
    ) -> InterviewSession:
        session = await self.db.get(InterviewSession, session_id)
        if session is None or session.user_id != user_id:
            raise NotFoundError("Interview session not found")
        return session

    async def create(
        self, user_id: uuid.UUID, payload: InterviewSessionCreate
    ) -> InterviewSession:
        """Resolve the role source, generate the plan draft, persist."""
        from app.ai.agents.interview_coach import generate_interview_plan
        from app.models.job_model import Job
        from app.services.postings_service import resolve_posting

        posting = None
        job = None
        if payload.posting_ref:
            posting = await resolve_posting(self.db, payload.posting_ref)
            if posting is None:
                raise NotFoundError("Posting not found")
            role_label = posting.title
        elif payload.job_code:
            row = await self.db.execute(select(Job).where(Job.code == payload.job_code))
            job = row.scalar_one_or_none()
            if job is None:
                raise NotFoundError("Catalog job not found")
            role_label = job.title
        else:
            raise ValidationError(
                "Provide a posting_ref or a job_code for the practice role"
            )

        plan: InterviewPlan = await generate_interview_plan(
            self.db,
            user_id,
            posting=posting,
            job=job,
            kind=payload.kind,
        )
        session = InterviewSession(
            user_id=user_id,
            posting_id=posting.id if posting is not None else None,
            kind=payload.kind,
            status=InterviewStatus.PLANNED.value,
            role_label=role_label,
            plan=[item.model_dump(mode="json") for item in plan.items],
        )
        self.db.add(session)
        await self.db.commit()
        return await self.get(user_id, session.id)

    async def list_sessions(self, user_id: uuid.UUID) -> list[InterviewSession]:
        rows = await self.db.execute(
            select(InterviewSession)
            .options(selectinload(InterviewSession.posting))
            .where(InterviewSession.user_id == user_id)
            .order_by(InterviewSession.updated_at.desc())
        )
        return list(rows.scalars().all())

    async def get(self, user_id: uuid.UUID, session_id: uuid.UUID) -> InterviewSession:
        row = await self.db.execute(
            select(InterviewSession)
            .options(selectinload(InterviewSession.posting))
            .where(
                InterviewSession.id == session_id,
                InterviewSession.user_id == user_id,
            )
        )
        session = row.scalar_one_or_none()
        if session is None:
            raise NotFoundError("Interview session not found")
        return session

    async def patch_plan(
        self,
        user_id: uuid.UUID,
        session_id: uuid.UUID,
        patch: InterviewPlanPatch,
    ) -> InterviewSession:
        """User edit of the plan (add/remove/reorder). Answered questions
        can be dropped but not silently re-ordered past their rubric —
        ids are stable, so answers stay attached."""
        session = await self._get_owned(user_id, session_id)
        if session.status not in (
            InterviewStatus.PLANNED.value,
            InterviewStatus.ACTIVE.value,
        ):
            raise ValidationError("This session is no longer editable")
        items = [item.model_dump(mode="json") for item in patch.items]
        ids = [item["id"] for item in items]
        if len(ids) != len(set(ids)):
            raise ValidationError("Plan item ids must be unique")
        answered = session.answered_ids
        if not answered.issubset(set(ids)):
            raise ValidationError("Cannot remove a question that already has feedback")
        session.plan = items
        await self.db.commit()
        return await self.get(user_id, session.id)

    async def set_chat_session(
        self,
        user_id: uuid.UUID,
        session_id: uuid.UUID,
        chat_session_id: uuid.UUID,
    ) -> InterviewSession:
        """Bind the practice transcript (start flow, slice 35.2)."""
        session = await self._get_owned(user_id, session_id)
        session.chat_session_id = chat_session_id
        session.status = InterviewStatus.ACTIVE.value
        await self.db.commit()
        return await self.get(user_id, session.id)

    async def record_turn(
        self,
        user_id: uuid.UUID,
        session_id: uuid.UUID,
        *,
        question_id: str,
        rubric: dict,
    ) -> InterviewSession:
        """Append one rubric row; completes the session when the plan is
        exhausted (answer order is plan order — one row per question)."""
        session = await self._get_owned(user_id, session_id)
        if session.status == InterviewStatus.COMPLETED.value:
            raise ValidationError("This interview is already complete")
        if any(
            row.get("question_id") == question_id for row in session.rubric_scores or []
        ):
            raise ValidationError("This question was already answered")
        session.rubric_scores = [
            *(session.rubric_scores or []),
            {"question_id": question_id, **rubric},
        ]
        if session.next_question is None:
            session.status = InterviewStatus.COMPLETED.value
        await self.db.commit()
        return await self.get(user_id, session.id)

    async def generate_debrief(
        self, user_id: uuid.UUID, session_id: uuid.UUID
    ) -> InterviewSession:
        """Aggregate + narrative + resources for a completed session
        (idempotent — an existing debrief is returned untouched)."""
        from app.ai.agents.interview_coach import generate_debrief_payload

        session = await self._get_owned(user_id, session_id)
        if session.debrief:
            return await self.get(user_id, session_id)
        if session.status != InterviewStatus.COMPLETED.value:
            raise ValidationError("Finish the practice before the debrief")
        payload = await generate_debrief_payload(
            self.db,
            user_id,
            role=session.role_label,
            plan=session.plan or [],
            rubric_rows=session.rubric_scores or [],
        )
        session.debrief = payload
        await self.db.commit()
        return await self.get(user_id, session_id)

    async def retry_weak(
        self, user_id: uuid.UUID, session_id: uuid.UUID
    ) -> InterviewSession:
        """One-click weak-area retry: a fresh planned session reusing the
        source's weak questions verbatim (deterministic — no LLM call)."""
        from app.models.interview_model import InterviewSession as Model

        source = await self._get_owned(user_id, session_id)
        if source.status != InterviewStatus.COMPLETED.value or not source.debrief:
            raise ValidationError("Complete the debrief before retrying")
        weak_ids = set(source.debrief.get("weak_question_ids") or [])
        items = [item for item in source.plan or [] if item.get("id") in weak_ids]
        if not items:
            raise ValidationError("No weak areas to retry — start a new role")
        retry = Model(
            user_id=user_id,
            posting_id=source.posting_id,
            kind=source.kind,
            status=InterviewStatus.PLANNED.value,
            role_label=source.role_label,
            plan=items,
        )
        self.db.add(retry)
        await self.db.commit()
        return await self.get(user_id, retry.id)
