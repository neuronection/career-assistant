"""One-shot CV generation service: validation, enqueue, run.

The API validates + enqueues (202); the job queue executes
``CvGenerateService.generate``, which drives the checkpointed LangGraph
flow (``app.ai.graphs.cv_draft``). The background-job row is the run
record — no new table; the compiled ``ai_apply`` version is the artifact
marker. Provider unconfigured → 503 at enqueue time, never a fake draft.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.checkpointer import get_checkpointer
from app.ai.providers.resolution import resolve_task_model
from app.core.errors import AINotConfiguredError, NotFoundError, ValidationError
from app.models.background_job_model import BackgroundJob
from app.models.enums import AITaskType, BackgroundJobType
from app.models.experience_model import ExperienceItem
from app.models.posting_model import JobPosting
from app.schemas.cv import CvContextSelection
from app.models.profile_entities_model import EducationItem
from app.models.user_model import Profile, UserSkill
from app.schemas.cv_generate import CvGenerateRequest
from app.services.job_worker import enqueue


async def assert_generatable(
    db: AsyncSession, user_id: UUID, request: CvGenerateRequest
) -> None:
    """Fail-fast request checks: posting/template exist + sparse guard.

    The section × source crossing itself is re-computed inside the run
    .
    """
    if request.target_posting_id is not None:
        posting = (
            (
                await db.execute(
                    select(JobPosting.id).where(
                        JobPosting.id == request.target_posting_id
                    )
                )
            )
            .scalars()
            .first()
        )
        if posting is None:
            raise NotFoundError("Posting not found")
    if request.template_id is not None:
        from app.services.cv_template_service import CvTemplateService

        await CvTemplateService(db).get_readable(request.template_id, user_id)
    content = await db.execute(
        select(ExperienceItem.id)
        .where(ExperienceItem.user_id == user_id, ExperienceItem.status == "active")
        .limit(1)
    )
    if content.scalars().first() is not None:
        return
    education = await db.execute(
        select(EducationItem.id)
        .where(EducationItem.user_id == user_id, EducationItem.status == "active")
        .limit(1)
    )
    if education.scalars().first() is not None:
        return
    skills = await db.execute(
        select(UserSkill.id).where(UserSkill.user_id == user_id).limit(1)
    )
    if skills.scalars().first() is not None:
        return
    profile = (
        (await db.execute(select(Profile).where(Profile.user_id == user_id)))
        .scalars()
        .first()
    )
    if profile and (profile.aspirations or []):
        return
    raise ValidationError(
        "Nothing to generate from yet — add experience, education, or "
        "skills to your profile first (or import your CV)"
    )


async def enqueue_generation(
    db: AsyncSession, user_id: UUID, request: CvGenerateRequest
) -> BackgroundJob:
    """Validate, check the AI config (503 when unconfigured), enqueue."""
    await assert_generatable(db, user_id, request)
    resolved = await resolve_task_model(db, AITaskType.CV_DRAFT.value, user_id)
    if resolved is None:
        raise AINotConfiguredError(
            "AI is not configured — ask an administrator to set up a provider"
        )
    return await enqueue(
        db,
        BackgroundJobType.CV_GENERATE.value,
        {"request": request.model_dump(mode="json")},
        user_id=user_id,
    )


async def enqueue_polish(
    db: AsyncSession, user_id: UUID, cv_id: UUID, *, resumed_from: str = ""
) -> BackgroundJob:
    """Queue a polish-only run over a committed CV (plan 64 §3).

    Answers 404 through the API for a foreign/missing resume and 503
    when no AI provider is configured."""
    from app.models.cv_model import CvDocument

    cv = await db.get(CvDocument, cv_id)
    if cv is None or cv.kind != "resume" or cv.user_id != user_id:
        raise NotFoundError("CV not found")
    resolved = await resolve_task_model(db, AITaskType.CV_BUILD_REVIEW.value, user_id)
    if resolved is None:
        raise AINotConfiguredError(
            "AI is not configured — ask an administrator to set up a provider"
        )
    return await enqueue(
        db,
        BackgroundJobType.CV_POLISH.value,
        {"cv_id": str(cv_id), "resumed_from": resumed_from},
        user_id=user_id,
    )


class CvGenerateService:
    """Drives one checkpointed cv_draft run (queue handler entry point)."""

    def __init__(self, db: AsyncSession, checkpointer=None):
        self.db = db
        self._checkpointer = checkpointer

    async def generate(
        self,
        user_id: UUID,
        request: CvGenerateRequest,
        *,
        run_id: UUID,
        progress=None,
        cancelled=None,
    ) -> dict:
        """Run (or resume) the flow; thread_id = job id."""
        from app.ai.graphs.cv_draft import (
            GraphDeps,
            build_cv_draft_graph,
            initial_state,
        )

        deps = GraphDeps(db=self.db, progress=progress, cancelled=cancelled)
        checkpointer = self._checkpointer
        if checkpointer is None:
            checkpointer = await get_checkpointer()
        graph = build_cv_draft_graph(deps, checkpointer)
        config = {"configurable": {"thread_id": str(run_id)}}
        final = await graph.ainvoke(
            initial_state(
                user_id=user_id,
                run_id=run_id,
                request=request.model_dump(mode="json"),
            ),
            config,
        )
        await self.db.commit()
        abort_reason = final.get("abort_reason")
        if abort_reason:
            return {
                "status": abort_reason,
                "error": final.get("error") or "",
            }
        return {"status": "completed", **(final.get("result") or {})}

    async def polish(
        self,
        user_id: UUID,
        cv_id: UUID,
        *,
        run_id: UUID,
        progress=None,
        cancelled=None,
        resumed_from: str = "",
    ) -> dict:
        """Re-enter the flow at review for a committed CV (user-directed).

        The context selection, language and page budget come from the
        document; the polish loop then runs over the committed state and
        finalize compiles a fresh `ai_apply` version carrying the updated
        trace (`run.resumed_from` links it to the earlier run)."""
        from app.ai.graphs.cv_draft import (
            GraphDeps,
            build_cv_polish_graph,
            polish_entry_state,
        )
        from app.models.cv_model import CvDocument

        cv = await self.db.get(CvDocument, cv_id)
        if cv is None or cv.kind != "resume":
            raise ValidationError("CV not found")
        request = CvGenerateRequest(
            language=cv.language or "en",
            max_pages=cv.max_pages or 1,
            target_posting_id=cv.target_posting_id,
            context=CvContextSelection.model_validate(cv.context or {}),
        )
        deps = GraphDeps(db=self.db, progress=progress, cancelled=cancelled)
        checkpointer = self._checkpointer
        if checkpointer is None:
            checkpointer = await get_checkpointer()
        graph = build_cv_polish_graph(deps, checkpointer)
        config = {"configurable": {"thread_id": str(run_id)}}
        final = await graph.ainvoke(
            polish_entry_state(
                user_id=user_id,
                run_id=run_id,
                request=request.model_dump(mode="json"),
                cv_id=cv_id,
                resumed_from=resumed_from,
            ),
            config,
        )
        await self.db.commit()
        abort_reason = final.get("abort_reason")
        if abort_reason:
            return {"status": abort_reason, "error": final.get("error") or ""}
        return {"status": "completed", **(final.get("result") or {})}
