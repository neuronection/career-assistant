"""Assessment pipeline endpoints (Phase 23)."""

from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.errors import AINotConfiguredError, DomainError
from app.services.assessment.runner import AssessmentService
from app.services.deps import get_current_user

router = APIRouter(prefix="/assessments", tags=["assessments"])


class CreateRunIn(BaseModel):
    kind: str = "full"
    context: dict = Field(default_factory=dict)


class AnswersIn(BaseModel):
    answers: list[dict] = Field(default_factory=list, max_length=30)


class AssistIn(BaseModel):
    question_id: str


@router.post("", status_code=201)
async def create_run(
    body: CreateRunIn = Body(default=CreateRunIn()),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Start a run (kind: onboarding | full | custom + context)."""
    service = AssessmentService(db)
    run = await service.create_run(user.id, body.kind, body.context)
    return await service.state(run)


@router.get("")
async def history(
    user=Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[dict]:
    """The caller's runs, newest first."""
    runs = await AssessmentService(db).history(user.id)
    return [
        {
            "id": str(r.id),
            "kind": r.kind,
            "status": r.status,
            "current_phase": r.current_phase,
            "phase_order": r.phase_order,
            "created_at": r.created_at.isoformat(),
        }
        for r in runs
    ]


@router.get("/{run_id}")
async def get_state(
    run_id: UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """State, progress and the current phase's questions."""
    service = AssessmentService(db)
    run = await service.get_run(run_id, user.id)
    return await service.state(run)


@router.post("/{run_id}/answers")
async def submit_answers(
    run_id: UUID,
    body: AnswersIn,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Batch save-on-answer (skips pass null/{} answers)."""
    service = AssessmentService(db)
    run = await service.get_run(run_id, user.id)
    try:
        return await service.submit_answers(run, body.answers)
    except DomainError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.post("/{run_id}/advance")
async def advance(
    run_id: UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Score the current phase; on the last phase, complete + apply results."""
    service = AssessmentService(db)
    run = await service.get_run(run_id, user.id)
    try:
        return await service.advance(run, user.id)
    except DomainError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.post("/{run_id}/cancel")
async def cancel(
    run_id: UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Abandon a run (history keeps it; outputs are not applied)."""
    service = AssessmentService(db)
    run = await service.get_run(run_id, user.id)
    return await service.cancel(run)


@router.post("/{run_id}/assist")
async def assist(
    run_id: UUID,
    body: AssistIn,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Ask AI about a specific question (audited, rate-limited like assist)."""
    service = AssessmentService(db)
    run = await service.get_run(run_id, user.id)
    try:
        answer = await service.assist(run, body.question_id)
    except AINotConfiguredError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except DomainError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return {"answer": answer}


@router.get("/{run_id}/results")
async def results(
    run_id: UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Derived profile delta + shortlist (diffable across runs)."""
    service = AssessmentService(db)
    run = await service.get_run(run_id, user.id)
    return await service.results(run)


# ------------------------------------------------ template library (plan 37)


class TemplateIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    content: dict
    visibility: str = "private"
    audience_stages: list[str] = Field(default_factory=list, max_length=6)
    language: str = "en"


class TemplateUpdateIn(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    content: dict | None = None
    visibility: str | None = None
    status: str | None = None


class TemplateDraftAiIn(BaseModel):
    brief: dict = Field(default_factory=dict)
    extend: bool = False


class TemplateImportIn(BaseModel):
    package: dict


def _template_out(t) -> dict:
    return {
        "id": str(t.id),
        "key": t.key,
        "version": t.version,
        "title": t.title,
        "description": t.description,
        "source": t.source,
        "visibility": t.visibility,
        "status": t.status,
        "audience_stages": t.audience_stages,
        "language": t.language,
        "ref": t.ref,
        "content_hash": t.content_hash,
        "is_bank": t.author_key == "bank",
        "created_at": t.created_at.isoformat(),
    }


@router.get("/templates")
async def list_templates(
    source: str | None = None,
    language: str | None = None,
    audience_stage: str | None = None,
    ref: str | None = None,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Mine + bank + unlisted-by-ref (filters: source/language/audience)."""
    from app.services.assessment_templates import TemplateService

    rows = await TemplateService(db).list_templates(
        user.id,
        source=source,
        language=language,
        audience_stage=audience_stage,
        ref=ref,
    )
    return [_template_out(t) for t in rows]


@router.post("/templates", status_code=201)
async def create_template(
    body: TemplateIn,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Author a template (validated like any write; author review before
    publish — drafts start private)."""
    from app.schemas.assessment_template import TemplateContent
    from app.services.assessment_templates import TemplateService

    content = TemplateContent.model_validate(body.content)
    template = await TemplateService(db).create_template(
        user.id,
        title=body.title,
        description=body.description,
        content=content,
        visibility=body.visibility,
        audience_stages=body.audience_stages,
        language=body.language,
    )
    return _template_out(template)


@router.get("/templates/{template_id}")
async def get_template(
    template_id: UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """One template (includes content for author preview)."""
    from app.services.assessment_templates import TemplateService

    template = await TemplateService(db).get_template(template_id, user.id)
    out = _template_out(template)
    out["content"] = template.content
    return out


@router.patch("/templates/{template_id}")
async def update_template(
    template_id: UUID,
    body: TemplateUpdateIn,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Edit = publish a NEW immutable version (42.B); status transitions
    travel through PATCH {status} (draft → published → retired)."""
    from app.schemas.assessment_template import TemplateContent
    from app.services.assessment_templates import TemplateService

    service = TemplateService(db)
    if body.status == "published":
        await service.publish(user.id, template_id)
    has_edits = any(
        value is not None for key, value in body.model_dump().items() if key != "status"
    )
    if has_edits:
        content = TemplateContent.model_validate(body.content) if body.content else None
        template = await service.new_version(
            user.id,
            template_id,
            title=body.title,
            description=body.description,
            content=content,
            visibility=body.visibility,
        )
        return _template_out(template)
    template = await service.get_template(template_id, user.id, require_owner=True)
    return _template_out(template)


@router.post("/templates/draft-ai")
async def draft_template_ai_new(
    body: TemplateDraftAiIn,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """AI draft of a NEW template from a brief — output is a DRAFT for
    author review; nothing is saved until the author commits it."""
    return await _draft_ai(db, user.id, body, extend_of=None)


@router.post("/templates/{template_id}/draft-ai")
async def draft_template_ai_extend(
    template_id: UUID,
    body: TemplateDraftAiIn,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """AI EXTEND of an existing template — grounded on its taxonomy keys;
    still review-first."""
    from app.services.assessment_templates import TemplateService

    extend_of = None
    if body.extend:
        extend_of = (
            await TemplateService(db).get_template(template_id, user.id)
        ).content
    return await _draft_ai(db, user.id, body, extend_of=extend_of)


async def _draft_ai(
    db: AsyncSession, user_id, body: TemplateDraftAiIn, *, extend_of
) -> dict:
    from sqlalchemy import select

    from app.ai.agents.assessment_designer import generate_template_draft
    from app.models.taxonomy_model import Skill

    skill_rows = (
        (await db.execute(select(Skill.key).where(Skill.status == "active").limit(200)))
        .scalars()
        .all()
    )
    content = await generate_template_draft(
        db,
        user_id,
        brief=body.brief,
        skill_keys=list(skill_rows),
        extend_of=extend_of,
    )
    return {"content": content.model_dump(mode="json"), "status": "draft_review"}


@router.post("/templates/{template_id}/run")
async def run_template(
    template_id: UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Start a template run (compiles onto the plan-23 engine)."""
    from app.services.assessment.runner import AssessmentService
    from app.services.assessment_templates import TemplateService

    run = await TemplateService(db).start_run(user.id, template_id)
    return await AssessmentService(db).state(run)


@router.get("/templates/{template_id}/export")
async def export_template(
    template_id: UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Export package {schema_version, metadata, content, content_hash}."""
    from app.services.assessment_templates import TemplateService

    return await TemplateService(db).export_template(user.id, template_id)


@router.post("/templates/import", status_code=201)
async def import_template(
    body: TemplateImportIn,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Import a package; unknown skill keys auto-propose (plan-21
    lifecycle) and the report lists them — hard-rejecting would make
    shared templates unusable across instances."""
    from app.services.assessment_templates import TemplateService

    template, resolution = await TemplateService(db).import_template(
        user.id, body.package
    )
    out = _template_out(template)
    out["import_report"] = resolution
    return out
