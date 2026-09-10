"""CV builder service: context resolution → preview/compile.

Compile is deterministic: (template content, resolved snapshot, page
options) → rendered HTML + metrics + an immutable `cv_versions` snapshot
whose `context_resolution` traces every rendered value to its
`{source_key, item_id}`. Working-content edits are field patches
(`overrides`) applied after resolution — the profile stays the single
source of truth.
"""

from dataclasses import asdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationError
from app.models.cv_model import CvDocument, CvVersion
from app.models.cv_template_model import CvTemplate
from app.models.enums import CvVersionCreator
from app.schemas.cv import CvContextSelection
from app.schemas.cv_template import TemplateContent
from app.services.cv_context_service import CvResolution, apply_overrides, resolve
from app.services.cv_renderer import RenderMetrics, render_cv, validate_blocks
from app.services.cv_service import CvService
from app.services.cv_template_service import CvTemplateService

FALLBACK_CONTENT: dict = {
    "blocks": [
        {"kind": "header"},
        {"kind": "summary"},
        {
            "kind": "items",
            "props": {"title": "Experience", "source_key": "experience"},
        },
        {
            "kind": "items",
            "props": {"title": "Education", "source_key": "education"},
        },
        {"kind": "skills", "props": {"title": "Skills"}},
        {"kind": "languages", "props": {"title": "Languages"}},
    ]
}


class CvBuilderService:
    """Preview / compile / restore / duplicate over one user's CVs."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.cvs = CvService(db)

    async def resolution(self, cv: CvDocument) -> CvResolution:
        """Resolve the CV's stored selection (default: include everything)."""
        selection = (
            CvContextSelection.model_validate(cv.context)
            if cv.context
            else CvContextSelection()
        )
        return await resolve(
            self.db, cv.user_id, selection, photo_document_id=cv.photo_document_id
        )

    async def template_row(self, cv: CvDocument) -> CvTemplate | None:
        """The template row a CV renders with (explicit → canonical bank).

        The fresh-CV default is pinned to the bank's `ats-classic` entry
        by key: `ORDER BY title` is collation-dependent (the 41b.2 dev-db
        image switch silently flipped the pick), so the default must not
        ride string sorting.
        """
        if cv.template_id is not None:
            return await CvTemplateService(self.db).get_readable(
                cv.template_id, cv.user_id
            )
        rows = await self.db.execute(
            select(CvTemplate)
            .where(CvTemplate.author_key == "bank")
            .order_by(
                CvTemplate.key != "ats-classic",
                CvTemplate.title.asc(),
                CvTemplate.version.desc(),
            )
        )
        return rows.scalars().first()

    async def template_content(
        self, cv: CvDocument
    ) -> tuple[TemplateContent, str | None]:
        """The template package a CV renders with.

        Returns the content and the resolved template id (None for the
        built-in fallback used on fresh installs without bank seeds).
        """
        template = await self.template_row(cv)
        if template is not None:
            return TemplateContent.model_validate(template.content), str(template.id)
        return TemplateContent.model_validate(FALLBACK_CONTENT), None

    async def render_state(
        self, cv: CvDocument
    ) -> tuple[str, dict, CvResolution, RenderMetrics]:
        """Render the CV's current state: html, version payload, resolution."""
        resolution = await self.resolution(cv)
        template_content, template_id = await self.template_content(cv)
        working = cv.working_content or {}
        blocks = working.get("blocks") or template_content.blocks
        validate_blocks(blocks)
        render_input = template_content.model_copy(update={"blocks": blocks})
        snapshot = apply_overrides(
            resolution.snapshot,
            resolution.snapshot_index,
            working.get("overrides") or {},
        )
        result = render_cv(
            render_input, snapshot, page_size=cv.page_size, max_pages=cv.max_pages
        )
        payload = {
            "template_id": template_id,
            "blocks": blocks,
            "design": template_content.design.model_dump(mode="json"),
            "pages": template_content.pages.model_dump(mode="json"),
            "snapshot": snapshot,
            "snapshot_index": resolution.snapshot_index,
        }
        return result.html, payload, resolution, result.metrics

    async def preview(
        self, cv: CvDocument
    ) -> tuple[str, dict, CvResolution, list[dict]]:
        """Render the current state WITHOUT creating a version."""
        html, payload, resolution, metrics = await self.render_state(cv)
        return html, asdict(metrics), resolution, payload["blocks"]

    async def compile(
        self,
        cv: CvDocument,
        created_by: CvVersionCreator = CvVersionCreator.USER_SAVE,
    ) -> tuple[CvVersion, str, dict]:
        """Snapshot the current state as the next immutable version."""
        html, payload, resolution, metrics = await self.render_state(cv)
        if not resolution.items and not (cv.working_content or {}).get("overrides"):
            raise ValidationError(
                "Nothing to compile: the context selection resolves no items"
            )
        version = await self.cvs.create_version(
            cv.id,
            cv.user_id,
            payload,
            created_by,
            context_resolution={
                "resolved_at": resolution.resolved_at.isoformat(),
                "items": resolution.item_refs(),
            },
        )
        return version, html, asdict(metrics)

    async def render_version(self, cv: CvDocument, version: CvVersion) -> str:
        """Render an immutable snapshot exactly as it was compiled."""
        content = version.content or {}
        template_content = TemplateContent.model_validate(
            {
                "blocks": content.get("blocks") or FALLBACK_CONTENT["blocks"],
                "design": content.get("design") or {},
                "pages": content.get("pages") or {},
            }
        )
        result = render_cv(
            template_content,
            content.get("snapshot") or {},
            page_size=cv.page_size,
            max_pages=cv.max_pages,
        )
        return result.html

    async def restore(self, cv: CvDocument, version: CvVersion) -> CvDocument:
        """Copy a version's blocks forward into the working state."""
        blocks = (version.content or {}).get("blocks")
        if not blocks:
            raise ValidationError("Version carries no blocks")
        validate_blocks(blocks)
        cv.working_content = {"blocks": blocks, "overrides": {}}
        self.db.add(cv)
        await self.db.commit()
        await self.db.refresh(cv)
        return cv

    async def duplicate(self, cv: CvDocument) -> CvDocument:
        """Copy the CV (metadata + working state); versions stay behind."""
        copy = CvDocument(
            user_id=cv.user_id,
            title=cv.title[:193] + " (copy)",
            kind=cv.kind,
            target_posting_id=cv.target_posting_id,
            template_id=cv.template_id,
            language=cv.language,
            page_size=cv.page_size,
            max_pages=cv.max_pages,
            status="draft",
            working_content=dict(cv.working_content or {}),
            context=dict(cv.context or {}),
            source_document_id=cv.source_document_id,
        )
        self.db.add(copy)
        await self.db.commit()
        await self.db.refresh(copy)
        return copy

    async def context_status(self, cv: CvDocument) -> dict:
        """Diff the current resolution against the latest compiled baseline."""
        rows = await self.db.execute(
            select(CvVersion)
            .where(CvVersion.cv_document_id == cv.id)
            .order_by(CvVersion.version.desc())
            .limit(1)
        )
        latest = rows.scalars().first()
        resolution = await self.resolution(cv)
        current = {
            (ref["source_key"], ref["item_id"]): ref for ref in resolution.item_refs()
        }
        if latest is None:
            return {
                "has_baseline": False,
                "stale": False,
                "changed": [],
                "added": [],
                "removed": [],
            }
        baseline = {
            (item["source_key"], item["item_id"]): item
            for item in (latest.context_resolution or {}).get("items") or []
        }
        changed, added, removed = [], [], []
        for key, ref in current.items():
            base = baseline.get(key)
            if base is None:
                added.append(ref)
            elif base.get("updated_at") != ref["updated_at"]:
                changed.append(ref)
        for key, ref in baseline.items():
            if key not in current:
                removed.append(ref)
        return {
            "has_baseline": True,
            "stale": bool(changed or added or removed),
            "changed": changed,
            "added": added,
            "removed": removed,
        }
