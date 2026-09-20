"""CV template service: authoring, versioning, import/export,
AI drafts, and the visual-review loop — mirroring's discipline.

Versions are immutable rows; an edit publishes version n+1. Exports carry
the canonical content hash; imports verify it, validate against the block
registry (unknown kinds are rejected with a report), and store as
private/imported. AI outputs are drafts until the author publishes them.
"""

import re
import uuid
from pathlib import Path

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
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
VISUAL_PICK_CANDIDATES = 4


def slugify_key(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "").strip().lower()).strip("-")
    return slug[:78] or f"cv-template-{uuid.uuid4().hex[:8]}"


def _author_key(user) -> str:
    """'bank' for system rows; the user id string otherwise."""
    return str(user.id) if getattr(user, "id", None) else "bank"


_LAYOUT_HINT_KEYWORDS = (
    "sidebar",
    "side panel",
    "side-panel",
    "two-column",
    "two column",
    "2-column",
    "modern",
)


def _layout_hint(notes: str) -> str:
    """A notes-driven layout hint for the template pick ('' = none).

    'modern' maps to the sidebar family — the two-column look the
    renderer's area system produces."""
    lowered = (notes or "").lower()
    for keyword in _LAYOUT_HINT_KEYWORDS:
        if keyword in lowered:
            return "sidebar"
    return ""


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

    async def update_version_content(
        self,
        template_id: uuid.UUID,
        version: int,
        user_id: uuid.UUID,
        content: TemplateContent,
    ) -> CvTemplate:
        """Overwrite a DRAFT version's content in place.

        Polish-loop coalescing only: the run restyles its OWN earlier
        draft instead of stacking an immutable row per AI op. Refuses
        anything that is not the caller's draft at that exact version —
        published/older/user-facing rows stay immutable."""
        template = await self.get_owned(template_id, user_id)
        if (
            template.version != int(version)
            or template.status != CvTemplateStatus.DRAFT.value
        ):
            raise ValidationError("Version is not the caller's coalescable draft")
        validate_blocks(content.blocks)
        template.content = content.model_dump(mode="json")
        template.content_hash = canonical_hash(content.model_dump(mode="json"))
        template.ats_safe = self._ats_safe_estimate(content)
        await self.db.commit()
        await self.db.refresh(template)
        return template

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

    async def diff_versions(
        self,
        template_id: uuid.UUID,
        user_id: uuid.UUID,
        against_id: uuid.UUID | None = None,
    ) -> dict:
        """Deterministic diff between two versions of one template key.

        Compares the caller-readable template against another version row
        of the same (author_key, key) — `against_id` defaults to the
        previous version. Returns flat token changes (path, from, to) and
        block-level structural changes; no prose, no images — the honest
        degradation when no PDF engine exists for pixel diffs."""
        template = await self.get_readable(template_id, user_id)
        if against_id is not None:
            other = (
                (
                    await self.db.execute(
                        select(CvTemplate).where(
                            CvTemplate.id == against_id,
                            CvTemplate.author_key == template.author_key,
                            CvTemplate.key == template.key,
                        )
                    )
                )
                .scalars()
                .first()
            )
            if other is None:
                raise NotFoundError("Comparison version not found for this template")
            if other.version > template.version:
                template, other = other, template
        else:
            rows = await self.db.execute(
                select(CvTemplate)
                .where(
                    CvTemplate.author_key == template.author_key,
                    CvTemplate.key == template.key,
                    CvTemplate.version < template.version,
                )
                .order_by(CvTemplate.version.desc())
                .limit(1)
            )
            other = rows.scalars().first()
            if other is None:
                raise ValidationError("No earlier version to compare against")

        newer = TemplateContent.model_validate(template.content)
        older = TemplateContent.model_validate(other.content)
        token_changes = []
        new_design = newer.design.model_dump(mode="json")
        old_design = older.design.model_dump(mode="json")
        for path in sorted(set(new_design) | set(old_design)):
            if new_design.get(path) != old_design.get(path):
                token_changes.append(
                    {
                        "path": f"design.{path}",
                        "from": old_design.get(path),
                        "to": new_design.get(path),
                    }
                )

        def _block_signature(block: dict) -> str:
            props = block.get("props") or {}
            return f"{block.get('kind')}:{props.get('title') or props.get('source_key') or ''}"

        old_blocks = [_block_signature(block) for block in older.blocks]
        new_blocks = [_block_signature(block) for block in newer.blocks]
        block_changes = {
            "added": [sig for sig in new_blocks if sig not in old_blocks],
            "removed": [sig for sig in old_blocks if sig not in new_blocks],
            "props_changed": [],
        }
        old_by_sig: dict[str, dict] = {}
        for block, sig in zip(older.blocks, old_blocks):
            old_by_sig.setdefault(sig, block)
        for block, sig in zip(newer.blocks, new_blocks):
            previous = old_by_sig.get(sig)
            if previous is None:
                continue
            if previous.get("props") != block.get("props") or previous.get(
                "area"
            ) != block.get("area"):
                block_changes["props_changed"].append(
                    {"block": sig, "area": block.get("area", "main")}
                )
        return {
            "from_version": other.version,
            "to_version": template.version,
            "token_changes": token_changes,
            "block_changes": block_changes,
        }

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
            language=str(template.language or "en"),
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
        notes: str = "",
    ) -> dict:
        """Rank readable templates for a new CV (deterministic + AI).

        Signal scores (language match, sidebar layout, ATS-safety)
        form the baseline; the CV_TEMPLATE_PICK call may only reorder
        and explain — its output is validated against the candidate
        refs, never a substitute template. The user's emphasis notes
        and, with the PDF engine present, the top candidates' sample
        renders ride along so the ranking judges the request and the
        actual LOOK, not the metadata; without them it degrades to the
        metadata-only baseline."""
        from app.ai.agents.cv_template_advisor import (
            TemplateCandidate,
            rank_templates,
        )

        rows = await self.list_templates(user_id)
        if not rows:
            return {"picks": [], "candidates_considered": 0}
        layout_hint = _layout_hint(notes)
        scored: list[tuple[float, int, CvTemplate]] = []
        for index, row in enumerate(rows):
            score = 5.0
            if str(row.language) == language:
                score += 2.0
            content = TemplateContent.model_validate(row.content)
            if content.design.layout == "sidebar":
                score += 1.5 if layout_hint == "sidebar" else 0.8
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
        if notes.strip():
            target["notes"] = notes.strip()[:2000]
        if layout_hint:
            target["layout_hint"] = layout_hint
        images = await self._candidate_thumbnails(ordered[:VISUAL_PICK_CANDIDATES])
        ranking = await rank_templates(
            self.db, user_id, candidates, target or None, images=images or None
        )
        by_ref = {f"t{index}": row for index, row in enumerate(ordered)}
        picks = [
            {"template_id": str(row.id), "title": row.title, "reason": pick.reason}
            for pick in ranking.ranking
            if (row := by_ref.get(pick.template_ref)) is not None
        ]
        return {"picks": picks, "candidates_considered": len(ordered)}

    async def _candidate_thumbnails(
        self, rows: list[CvTemplate]
    ) -> list[tuple[str, bytes]]:
        """First-page PNG per candidate, in candidate order ([] = skip).

        The (mime, bytes) images ride to the model in candidate-ref
        order (t0, t1, …) — the prompt ties order to refs.
        Behavior-based (not a probe): no PDF engine or any render
        failure simply drops the images — the ranking falls back to
        metadata-only."""
        from app.services.cv_pdf_service import measure_pages

        images: list[tuple[str, bytes]] = []
        for row in rows:
            try:
                html, _metrics = self.preview_html_content(
                    TemplateContent.model_validate(row.content)
                )
                measure = await measure_pages(
                    html, page_size=str(row.page_size), max_images=1
                )
            except Exception:  # noqa: BLE001 — one bad candidate degrades
                continue
            if measure.images:
                images.append(measure.images[0])
        return images

    async def first_page_png(self, template: CvTemplate) -> bytes | None:
        """First-page PNG of one template, rendered on demand.

        `None` on any render failure or without the PDF engine —
        callers degrade (the advisor drops the image, the chat preview
        route answers 503). `PDFEngineUnavailable` propagates so the
        capability message stays precise."""
        from app.services.cv_pdf_service import PDFEngineUnavailable, measure_pages

        try:
            html, _metrics = self.preview_html_content(
                TemplateContent.model_validate(template.content)
            )
            measure = await measure_pages(
                html, page_size=str(template.page_size), max_images=1
            )
        except PDFEngineUnavailable:
            raise
        except Exception:  # noqa: BLE001 — one bad template degrades
            return None
        return measure.images[0] if measure.images else None

    async def preview_png_cached(
        self, template_id: uuid.UUID, user_id: uuid.UUID
    ) -> tuple[bytes, str]:
        """First-page PNG with a content-hash cache (plan 83B).

        `previews/{template_id}/{content_hash}-p1.png` under the data
        dir — a template edit renders once, versions coexist while a
        diff is open. Invisible templates raise NotFoundError; a cache
        miss without the print engine raises PDFEngineUnavailable."""
        template = await self.get_readable(template_id, user_id)
        content_hash = canonical_hash(template.content or {})
        cache_dir = Path(settings.data_dir_path) / "previews" / str(template_id)
        cache_path = cache_dir / f"{content_hash}-p1.png"
        if cache_path.exists():
            return cache_path.read_bytes(), content_hash
        png = await self.first_page_png(template)
        if png is None:
            from app.services.cv_pdf_service import PDFEngineUnavailable

            raise PDFEngineUnavailable(
                "The template preview could not be rendered — the print "
                "engine may be missing."
            )
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(png)
        return png, content_hash

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
            language=str(template.language or "en"),
        )
        return {
            "estimated_pages": result.metrics.estimated_pages,
            "overflow": result.metrics.overflow,
            "empty_blocks": result.metrics.empty_blocks,
            "truncated": result.metrics.truncated,
            "lines_per_page": result.metrics.lines_per_page,
        }

    async def export_stats(self) -> list[dict]:
        """Export totals per template (admin telemetry view).

        Derived straight from the immutable `cv_versions` rows stamped
        `created_by='export'` — the version payload already carries the
        effective `template_id`, so no new telemetry pipeline is needed.
        Totals are dialect-safe (no month math in SQL) and stay
        anonymous (no per-user breakdown)."""
        from sqlalchemy import String, cast, func

        from app.models.cv_model import CvVersion

        template_ref = cast(CvVersion.content["template_id"], String).label(
            "template_ref"
        )
        groups = (
            await self.db.execute(
                select(template_ref, func.count())
                .where(CvVersion.created_by == "export")
                .group_by(template_ref)
            )
        ).all()
        by_id: dict[str, CvTemplate] = {}
        if groups:
            templates = await self.db.execute(
                select(CvTemplate).where(
                    CvTemplate.id.in_([uuid.UUID(ref) for ref, _c in groups if ref])
                )
            )
            by_id = {str(row.id): row for row in templates.scalars().all()}
        return [
            {
                "template_key": by_id[str(ref)].key if str(ref) in by_id else None,
                "template_source": (
                    by_id[str(ref)].source if str(ref) in by_id else None
                ),
                "exported": exports,
            }
            for ref, exports in groups
        ]


SOURCE_KEYS = {"experience", "education", "certifications", "projects"}
