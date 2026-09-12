"""CV template service: authoring, versioning, import/export,
AI drafts, and the visual-review loop — mirroring's discipline.

Versions are immutable rows; an edit publishes version n+1. Exports carry
the canonical content hash; imports verify it, validate against the block
registry (unknown kinds are rejected with a report), and store as
private/imported. AI outputs are drafts until the author publishes them.
"""

import re
import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, ValidationError
from app.models.cv_template_model import CvTemplate
from app.models.enums import (
    CvTemplateSource,
    CvTemplateStatus,
    CvTemplateVisibility,
)
from app.schemas.cv_template import CvTemplateExport, TemplateContent
from app.services.cv_blocks import validate_blocks
from app.services.cv_renderer import render_cv
from app.services.engagement_service import canonical_hash

TEMPLATE_SCHEMA_VERSION = 1


def slugify_key(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "").strip().lower()).strip("-")
    return slug[:78] or f"cv-template-{uuid.uuid4().hex[:8]}"


def _author_key(user) -> str:
    """'bank' for system rows; the user id string otherwise."""
    return str(user.id) if getattr(user, "id", None) else "bank"


class CvTemplateService:
    """CRUD + immutable versions + validation + AI + visual review."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ------------------------------------------------------------ queries

    async def list_templates(self, user_id: uuid.UUID) -> list[CvTemplate]:
        """Bank + the caller's own templates (public stays unreachable)."""
        rows = await self.db.execute(
            select(CvTemplate)
            .where(
                or_(
                    CvTemplate.author_key == "bank",
                    CvTemplate.author_user_id == user_id,
                )
            )
            .order_by(CvTemplate.key, CvTemplate.version.desc())
        )
        return self._latest_per_key(list(rows.scalars().all()))

    @staticmethod
    def _latest_per_key(templates: list[CvTemplate]) -> list[CvTemplate]:
        """One row per (author_key, key): the highest version."""
        latest: dict[tuple[str, str], CvTemplate] = {}
        for template in templates:
            slot = (template.author_key, template.key)
            if slot not in latest or template.version > latest[slot].version:
                latest[slot] = template
        return sorted(latest.values(), key=lambda t: (t.source != "bank", t.title))

    async def get_owned(self, template_id: uuid.UUID, user_id: uuid.UUID) -> CvTemplate:
        """Fetch a template the caller may edit (bank is read-only)."""
        rows = await self.db.execute(
            select(CvTemplate).where(
                CvTemplate.id == template_id,
                CvTemplate.author_user_id == user_id,
            )
        )
        template = rows.scalars().first()
        if template is None:
            rows = await self.db.execute(
                select(CvTemplate).where(
                    CvTemplate.id == template_id,
                    CvTemplate.author_key == "bank",
                )
            )
            template = rows.scalars().first()
            if template is not None:
                raise ValidationError("Bank templates are read-only; duplicate to edit")
        if template is None:
            raise NotFoundError("Template not found")
        return template

    async def get_readable(
        self, template_id: uuid.UUID, user_id: uuid.UUID
    ) -> CvTemplate:
        """Fetch any template the caller can render (bank + own)."""
        rows = await self.db.execute(
            select(CvTemplate).where(
                CvTemplate.id == template_id,
                or_(
                    CvTemplate.author_key == "bank",
                    CvTemplate.author_user_id == user_id,
                ),
            )
        )
        template = rows.scalars().first()
        if template is None:
            raise NotFoundError("Template not found")
        return template

    # ---------------------------------------------------------- mutations

    async def create(
        self,
        user_id: uuid.UUID,
        title: str,
        content: TemplateContent,
        *,
        description: str = "",
        source: CvTemplateSource = CvTemplateSource.USER,
        language: str = "en",
        page_size: str = "a4",
        key: str | None = None,
        status: CvTemplateStatus = CvTemplateStatus.DRAFT,
    ) -> CvTemplate:
        """Create version 1 of a new template (validated like any write)."""
        validate_blocks(content.blocks)
        template = CvTemplate(
            key=slugify_key(key or title),
            version=1,
            title=title,
            description=description,
            author_user_id=user_id,
            author_key=str(user_id),
            source=source.value,
            visibility=CvTemplateVisibility.PRIVATE.value,
            language=language,
            page_size=page_size,
            ats_safe=self._ats_safe_estimate(content),
            schema_version=TEMPLATE_SCHEMA_VERSION,
            content_hash=canonical_hash(content.model_dump(mode="json")),
            status=status.value,
            content=content.model_dump(mode="json"),
        )
        self.db.add(template)
        await self.db.commit()
        await self.db.refresh(template)
        return template

    async def new_version(
        self,
        template_id: uuid.UUID,
        user_id: uuid.UUID,
        content: TemplateContent,
        *,
        title: str | None = None,
        description: str | None = None,
        status: CvTemplateStatus = CvTemplateStatus.DRAFT,
    ) -> CvTemplate:
        """Publish the edited content as the next immutable version."""
        template = await self.get_owned(template_id, user_id)
        validate_blocks(content.blocks)
        rows = await self.db.execute(
            select(CvTemplate.version)
            .where(
                CvTemplate.author_key == template.author_key,
                CvTemplate.key == template.key,
            )
            .order_by(CvTemplate.version.desc())
            .limit(1)
        )
        latest = rows.scalar_one()
        version = CvTemplate(
            key=template.key,
            version=latest + 1,
            title=title or template.title,
            description=description or template.description,
            author_user_id=template.author_user_id,
            author_key=template.author_key,
            source=CvTemplateSource.USER.value
            if template.source == CvTemplateSource.USER.value
            else template.source,
            visibility=template.visibility,
            language=template.language,
            page_size=template.page_size,
            ats_safe=self._ats_safe_estimate(content),
            schema_version=TEMPLATE_SCHEMA_VERSION,
            content_hash=canonical_hash(content.model_dump(mode="json")),
            status=status.value,
            content=content.model_dump(mode="json"),
        )
        self.db.add(version)
        await self.db.commit()
        await self.db.refresh(version)
        return version

    async def duplicate(
        self, template_id: uuid.UUID, user_id: uuid.UUID, title: str | None = None
    ) -> CvTemplate:
        """Copy any readable template into the caller's private space."""
        source = await self.get_readable(template_id, user_id)
        content = TemplateContent.model_validate(source.content)
        return await self.create(
            user_id,
            title or f"{source.title} (copy)",
            content,
            description=source.description,
            source=CvTemplateSource.DUPLICATED,
            language=source.language,
            page_size=source.page_size,
        )

    async def delete(self, template_id: uuid.UUID, user_id: uuid.UUID) -> None:
        """Delete every version of one of the caller's template keys."""
        template = await self.get_owned(template_id, user_id)
        rows = await self.db.execute(
            select(CvTemplate).where(
                CvTemplate.author_key == template.author_key,
                CvTemplate.key == template.key,
            )
        )
        for row in rows.scalars().all():
            await self.db.delete(row)
        await self.db.commit()

    # ----------------------------------------------------- import/export

    async def export(
        self, template_id: uuid.UUID, user_id: uuid.UUID
    ) -> CvTemplateExport:
        """File-first export package with hash integrity."""
        template = await self.get_readable(template_id, user_id)
        content = TemplateContent.model_validate(template.content)
        dumped = content.model_dump(mode="json")
        return CvTemplateExport(
            metadata={
                "key": template.key,
                "title": template.title,
                "description": template.description,
                "language": template.language,
                "page_size": template.page_size,
                "ats_safe": template.ats_safe,
            },
            content=dumped,
            content_hash=canonical_hash(dumped),
        )

    async def import_package(
        self, user_id: uuid.UUID, package: CvTemplateExport
    ) -> CvTemplate:
        """Validate + store an imported template (private, source=imported).

        Unknown block kinds are rejected with a report (layout kinds are
        code-adjacent, unlike taxonomy keys which auto-propose).
        """
        if package.kind != "cv_template":
            raise ValidationError("Not a CV template package")
        if package.schema_version != TEMPLATE_SCHEMA_VERSION:
            raise ValidationError(
                f"Unsupported template schema version: {package.schema_version}"
            )
        computed = canonical_hash(package.content)
        if computed != package.content_hash:
            raise ValidationError("Template package hash mismatch")
        try:
            content = TemplateContent.model_validate(package.content)
        except Exception as exc:  # noqa: BLE001 - surfaced as a validation error
            raise ValidationError(f"Invalid template content: {exc}") from exc
        meta = package.metadata or {}
        return await self.create(
            user_id,
            str(meta.get("title") or "Imported template"),
            content,
            description=str(meta.get("description") or ""),
            source=CvTemplateSource.IMPORTED,
            language=str(meta.get("language") or "en"),
            page_size=str(meta.get("page_size") or "a4"),
        )

    # ------------------------------------------------------------- render

    def preview_html(
        self,
        template: CvTemplate,
        snapshot: dict | None = None,
        max_pages: int | None = None,
    ) -> tuple[str, dict]:
        """Render sample (or provided) data; returns (html, metrics)."""
        content = TemplateContent.model_validate(template.content)
        if snapshot is None:
            snapshot = self.sample_snapshot(content)
        result = render_cv(
            content,
            snapshot,
            page_size=template.page_size,
            max_pages=max_pages or content.pages.default_max_pages,
        )
        return result.html, {
            "estimated_pages": result.metrics.estimated_pages,
            "empty_blocks": result.metrics.empty_blocks,
            "overflow": result.metrics.overflow,
            "lines_per_page": result.metrics.lines_per_page,
        }

    @staticmethod
    def sample_snapshot(content: TemplateContent) -> dict:
        """Deterministic sample data covering the template's block kinds."""
        from app.services.cv_blocks import SAMPLE_SNAPSHOT

        return SAMPLE_SNAPSHOT

    @staticmethod
    def preview_html_content(
        content: TemplateContent,
        *,
        page_size: str = "a4",
        max_pages: int | None = None,
    ) -> tuple[str, dict]:
        """Render an unsaved content package over the sample snapshot."""
        from dataclasses import asdict

        result = render_cv(
            content,
            CvTemplateService.sample_snapshot(content),
            page_size=page_size,
            max_pages=max_pages or content.pages.default_max_pages,
        )
        return result.html, asdict(result.metrics)

    @staticmethod
    def _ats_safe_estimate(content: TemplateContent) -> bool:
        """Conservative lint: standard headings only, no exotic props."""
        for kind, props in validate_blocks(content.blocks):
            if kind not in {
                "header",
                "summary",
                "items",
                "skills",
                "languages",
                "achievements",
                "interests",
            }:
                return False
            if kind == "skills" and props.display not in ("chips", "list"):
                return False
            if kind == "items" and props.source_key not in SOURCE_KEYS:
                return False
        return True

    # ----------------------------------------------------------- suggest

    async def suggest(
        self,
        user_id: uuid.UUID,
        language: str = "en",
        posting=None,
    ) -> dict:
        """Rank readable templates for a new CV (deterministic + AI).

        Signal scores (language match, sidebar layout, ATS-safety)
        form the baseline; the CV_TEMPLATE_PICK call may only reorder
        and explain — its output is validated against the candidate
        refs, never a substitute template.
        """
        from app.ai.agents.cv_template_advisor import (
            TemplateCandidate,
            rank_templates,
        )

        rows = await self.list_templates(user_id)
        if not rows:
            return {"picks": [], "candidates_considered": 0}
        scored: list[tuple[float, int, CvTemplate]] = []
        for index, row in enumerate(rows):
            score = 5.0
            if str(row.language) == language:
                score += 2.0
            content = TemplateContent.model_validate(row.content)
            if content.design.layout == "sidebar":
                score += 0.8
            if row.ats_safe:
                score += 1.2
            scored.append((-score, index, row))
        scored.sort(key=lambda entry: (entry[0], entry[1]))
        ordered = [entry[2] for entry in scored]
        candidates = [
            TemplateCandidate(
                ref=f"t{index}",
                template_id=str(row.id),
                title=row.title,
                source=str(row.source),
                language=str(row.language),
                page_size=str(row.page_size),
                ats_safe=bool(row.ats_safe),
                layout=TemplateContent.model_validate(row.content).design.layout,
                score=-scored[index][0],
            )
            for index, row in enumerate(ordered)
        ]
        target: dict = {}
        if posting is not None:
            target = {"title": posting.title, "org": posting.org or ""}
        ranking = await rank_templates(self.db, user_id, candidates, target or None)
        by_ref = {f"t{index}": row for index, row in enumerate(ordered)}
        picks = [
            {"template_id": str(row.id), "title": row.title, "reason": pick.reason}
            for pick in ranking.ranking
            if (row := by_ref.get(pick.template_ref)) is not None
        ]
        return {"picks": picks, "candidates_considered": len(ordered)}

    # ------------------------------------------------------ visual review

    # ------------------------------------------------------ visual review

    def lint(self, template: CvTemplate, max_pages: int | None = None) -> dict:
        """Deterministic layout lint from the renderer's own metrics."""
        content = TemplateContent.model_validate(template.content)
        result = render_cv(
            content,
            self.sample_snapshot(content),
            page_size=template.page_size,
            max_pages=max_pages or content.pages.default_max_pages,
        )
        return {
            "estimated_pages": result.metrics.estimated_pages,
            "overflow": result.metrics.overflow,
            "empty_blocks": result.metrics.empty_blocks,
            "truncated": result.metrics.truncated,
            "lines_per_page": result.metrics.lines_per_page,
        }


SOURCE_KEYS = {"experience", "education", "certifications", "projects"}
