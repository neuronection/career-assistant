import json
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.agents.cv_template_designer import critique_pages, draft_template
from app.core.database import get_db
from app.core.errors import ValidationError
from app.models.enums import CvTemplateSource
from app.schemas.cv_template import (
    CvTemplateExport,
    CvTemplateOut,
    TemplateContent,
)
from app.services.cv_template_service import CvTemplateService
from app.services.deps import get_current_user

router = APIRouter(prefix="/cv/templates", tags=["cv-templates"])


class TemplateWrite(BaseModel):
    """Create (v1) or update (next version) a template package."""

    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    content: dict
    key: str | None = Field(default=None, max_length=80)


class PreviewDraftRequest(BaseModel):
    """Render an UNSAVED content package for the live editor preview."""

    content: dict


class DraftAIRequest(BaseModel):
    brief: str = Field(min_length=1, max_length=2000)
    target_role: str = Field(default="", max_length=200)
    density: str = Field(default="normal", max_length=20)
    page_budget: int = Field(default=1, ge=1, le=10)
    publish_as: str | None = Field(default=None, max_length=200)


def _validate_content(payload: dict) -> TemplateContent:
    try:
        return TemplateContent.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - pydantic surfaces as 400
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.get("", response_model=list[CvTemplateOut])
async def list_templates(
    user=Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[CvTemplateOut]:
    """Bank templates + the caller's own (latest version per key)."""
    templates = await CvTemplateService(db).list_templates(user.id)
    return [CvTemplateOut.model_validate(t) for t in templates]


@router.get("/themes")
async def list_themes(
    user=Depends(get_current_user),
) -> list[dict]:
    """Predefined color/layout themes for the template editor."""
    from app.services.cv_themes import CV_THEMES

    return [
        {
            "key": theme.key,
            "label": theme.label,
            "description": theme.description,
            "accent_color": theme.design.accent_color,
            "heading_color": theme.design.heading_color,
            "design": theme.design.model_dump(mode="json"),
        }
        for theme in CV_THEMES
    ]


@router.post("/preview-draft", response_class=HTMLResponse)
async def preview_draft(
    payload: PreviewDraftRequest,
    user=Depends(get_current_user),
) -> HTMLResponse:
    """Render an UNSAVED content package over the sample snapshot."""
    content = _validate_content(payload.content)
    from app.services.cv_template_service import CvTemplateService

    html, _metrics = CvTemplateService.preview_html_content(content)
    return HTMLResponse(html)


@router.post("", response_model=CvTemplateOut, status_code=201)
async def create_template(
    payload: TemplateWrite,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CvTemplateOut:
    """Author a new template (version 1, private)."""
    content = _validate_content(payload.content)
    template = await CvTemplateService(db).create(
        user.id,
        payload.title,
        content,
        description=payload.description,
        key=payload.key,
    )
    return CvTemplateOut.model_validate(template)


@router.post("/draft-ai", response_model=CvTemplateOut, status_code=201)
async def draft_ai_template(
    payload: DraftAIRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CvTemplateOut:
    """AI-designed template draft — stored unpublished for author review."""
    try:
        content = await draft_template(
            db,
            user.id,
            brief=payload.brief,
            target_role=payload.target_role,
            density=payload.density,
            page_budget=payload.page_budget,
        )
    except Exception as exc:  # noqa: BLE001 - AI failures surface as 503/400
        from app.core.errors import AINotConfiguredError

        if isinstance(exc, AINotConfiguredError):
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    title = payload.publish_as or payload.brief[:80]
    template = await CvTemplateService(db).create(
        user.id,
        title,
        content,
        description=f"AI draft — {payload.target_role or 'custom brief'}",
        source=CvTemplateSource.AI,
    )
    return CvTemplateOut.model_validate(template)


@router.post("/import", response_model=CvTemplateOut, status_code=201)
async def import_template(
    package: CvTemplateExport,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CvTemplateOut:
    """Import a template package (hash-verified, stored private)."""
    try:
        template = await CvTemplateService(db).import_package(user.id, package)
    except ValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return CvTemplateOut.model_validate(template)


@router.get("/{template_id}/preview", response_class=HTMLResponse)
async def preview_template(
    template_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    """Render the template with deterministic sample data."""
    service = CvTemplateService(db)
    template = await service.get_readable(template_id, user.id)
    html, _metrics = service.preview_html(template)
    return HTMLResponse(html)


@router.get("/{template_id}/export")
async def export_template(
    template_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """File-first export package (hash-verified import round trip)."""
    package = await CvTemplateService(db).export(template_id, user.id)
    return package.model_dump(mode="json")


@router.post("/{template_id}/duplicate", response_model=CvTemplateOut, status_code=201)
async def duplicate_template(
    template_id: uuid.UUID,
    payload: dict | None = None,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CvTemplateOut:
    """Copy any readable template into your own private space."""
    title = (payload or {}).get("title")
    template = await CvTemplateService(db).duplicate(template_id, user.id, title)
    return CvTemplateOut.model_validate(template)


@router.patch("/{template_id}", response_model=CvTemplateOut, status_code=201)
async def update_template(
    template_id: uuid.UUID,
    payload: TemplateWrite,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CvTemplateOut:
    """Publish edited content as the next immutable version."""
    content = _validate_content(payload.content)
    try:
        template = await CvTemplateService(db).new_version(
            template_id,
            user.id,
            content,
            title=payload.title,
            description=payload.description,
        )
    except ValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return CvTemplateOut.model_validate(template)


@router.post("/{template_id}/visual-review")
async def visual_review(
    template_id: uuid.UUID,
    page_count: int = 1,
    files: list[UploadFile] = File(default=[]),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Visual review loop: deterministic lint + optional vision critique.

    Attach printed/scanned page images (`files`) to ground the vision
    critique; without images the lint report alone drives suggestions.
    """
    service = CvTemplateService(db)
    template = await service.get_readable(template_id, user.id)
    lint = service.lint(template, max_pages=page_count)
    images = []
    for file in files[:10]:
        if (file.content_type or "") not in {"image/png", "image/jpeg"}:
            raise HTTPException(415, "Page images must be PNG or JPEG")
        images.append((file.content_type, await file.read()))
    try:
        critique = await critique_pages(
            db,
            user.id,
            template_summary=json.dumps(template.content.get("design", {})),
            lint=lint,
            max_pages=page_count,
            page_count=max(len(images), 0) or page_count,
            images=images or None,
        )
    except ValidationError:
        raise
    except Exception as exc:  # noqa: BLE001 - AI unconfigured degrades to lint
        from app.core.errors import AINotConfiguredError

        if isinstance(exc, AINotConfiguredError):
            critique = None
        else:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return {
        "lint": lint,
        "issues": critique.issues if critique else [],
        "safe_token_fixes": critique.safe_token_fixes if critique else {},
        "summary": critique.summary
        if critique
        else "Lint-only review (no vision provider).",
    }


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(
    template_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete every version of one of your templates."""
    await CvTemplateService(db).delete(template_id, user.id)
