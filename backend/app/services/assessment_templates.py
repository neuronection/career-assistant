"""Assessment template library service (plan 37).

Authoring (three paths, one validator: bank / AI-drafted / user-authored),
immutable versions, file-first import/export with taxonomy resolution
(unknown keys auto-propose on import — availability over curation; plan-15
promotion governs the vocabulary), and execution by compiling onto the
plan-23 engine (runs gain template_id; nothing new at runtime).
"""

import re
import uuid
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, ValidationError
from app.models.assessment_model import AssessmentRun
from app.models.assessment_template_model import AssessmentTemplate
from app.models.enums import (
    AssessmentKind,
    TemplateSource,
    TemplateStatus,
    TemplateVisibility,
)
from app.schemas.assessment_template import (
    EVIDENCE_ONLY_KINDS,
    TemplateContent,
)

TEMPLATE_SCHEMA_VERSION = 1
EXPORT_REF_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def generate_template_ref() -> str:
    """8-char Crockford base32 share ref (plan-32 pattern)."""
    import secrets

    return "".join(secrets.choice(EXPORT_REF_ALPHABET) for _ in range(8))


def slugify_key(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "").strip().lower()).strip("-")
    return slug[:78] or f"template-{uuid.uuid4().hex[:8]}"


class TemplateService:
    """CRUD + versioning + validation + import/export + run compile."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ---------------------------------------------------------- validate

    async def validate_content(
        self, content: TemplateContent, *, propose_unknown: bool = False
    ) -> dict:
        """Taxonomy resolution + registry discipline for one package.

        Every referenced skill_key must resolve; on import unknown keys
        auto-create `proposed` skills (origin=import) and the import
        succeeds with a report — authoring hard-rejects instead.
        """
        keys: set[str] = set()
        for phase in content.phases:
            for question in phase.questions:
                if question.skill_key:
                    keys.add(question.skill_key)
                for option in question.options:
                    keys.update((option.scores.skill_levels or {}).keys())
                for statement in question.statements:
                    keys.update((statement.scores.skill_levels or {}).keys())
        for band in content.normalization.bands:
            keys.update((band.suggested_levels or {}).keys())
        keys.discard(None)
        return await self._resolve_skill_keys(
            sorted(keys), propose_unknown=propose_unknown
        )

    async def _resolve_skill_keys(
        self, keys: list[str], *, propose_unknown: bool
    ) -> dict:
        from app.models.taxonomy_model import Skill

        if not keys:
            return {"proposed": [], "resolved": 0}
        rows = (
            (await self.db.execute(select(Skill).where(Skill.key.in_(keys))))
            .scalars()
            .all()
        )
        known = {s.key for s in rows}
        missing = [k for k in keys if k not in known]
        if not missing:
            return {"proposed": [], "resolved": len(known)}
        if not propose_unknown:
            raise ValidationError("Unknown skill keys: " + ", ".join(sorted(missing)))
        for key in missing:
            self.db.add(
                Skill(
                    key=key,
                    label=key.replace("-", " ").title()[:80],
                    category="general",
                    status="proposed",
                    origin="import",
                    provenance={"source": "template_import"},
                )
            )
        await self.db.flush()
        return {"proposed": sorted(missing), "resolved": len(known)}

    def _check_kinds(self, content: TemplateContent) -> None:
        """Kinds must be registry-known; evidence-only kinds carry no deltas."""
        from app.services.assessment.question_kinds import handler_for

        for phase in content.phases:
            for question in phase.questions:
                handler_for(question.kind)
                if question.kind in EVIDENCE_ONLY_KINDS:
                    if any(
                        o.scores.skill_levels or o.scores.interest_keys
                        for o in question.options
                    ):
                        raise ValidationError(
                            f"evidence-only kind {question.kind} carries deltas"
                        )

    # -------------------------------------------------------------- CRUD

    async def list_templates(
        self,
        user_id: UUID,
        *,
        include_bank: bool = True,
        source: Optional[str] = None,
        language: Optional[str] = None,
        audience_stage: Optional[str] = None,
        ref: Optional[str] = None,
    ) -> list[AssessmentTemplate]:
        """Mine + bank + unlisted-by-ref. `public` stays unreachable (422
        on write; the discovery page is the later sharing phase)."""
        query = select(AssessmentTemplate).where(
            AssessmentTemplate.retired.is_(False),
            AssessmentTemplate.status == TemplateStatus.PUBLISHED.value,
        )
        from sqlalchemy import or_

        scope = [AssessmentTemplate.author_user_id == user_id]
        if include_bank:
            scope.append(AssessmentTemplate.author_key == "bank")
        query = query.where(or_(*scope))
        if source:
            query = query.where(AssessmentTemplate.source == source)
        if language:
            query = query.where(AssessmentTemplate.language == language)
        if audience_stage:
            query = query.where(
                AssessmentTemplate.audience_stages.contains([audience_stage])
                | AssessmentTemplate.audience_stages
                == []
            )
        rows = await self.db.execute(
            query.order_by(AssessmentTemplate.created_at.desc()).limit(200)
        )
        templates = list(rows.scalars().all())
        if ref:
            resolved = await self.resolve_by_ref(ref)
            templates = [t for t in templates if t.id == resolved.id]
        return templates

    async def resolve_by_ref(self, ref: str) -> AssessmentTemplate:
        """A share ref resolves to the LATEST version of its family."""
        rows = await self.db.execute(
            select(AssessmentTemplate).where(
                AssessmentTemplate.ref == ref.strip().upper()
            )
        )
        first = rows.scalars().first()
        if first is None:
            raise NotFoundError("No template with that ref")
        return await self._latest_version(first.key, first.author_key)

    async def get_template(
        self,
        template_id: UUID,
        user_id: UUID,
        *,
        require_owner: bool = False,
    ) -> AssessmentTemplate:
        rows = await self.db.execute(
            select(AssessmentTemplate).where(AssessmentTemplate.id == template_id)
        )
        template = rows.scalars().first()
        if template is None:
            raise NotFoundError("Template not found")
        if template.author_user_id == user_id or template.author_key == "bank":
            return template
        if require_owner:
            raise NotFoundError("Template not found")
        shareable = (
            template.status == TemplateStatus.PUBLISHED.value
            and template.visibility
            in (TemplateVisibility.UNLISTED.value, TemplateVisibility.PUBLIC.value)
        )
        if not shareable:
            raise NotFoundError("Template not found")
        return template

    async def create_template(
        self,
        user_id: UUID,
        *,
        title: str,
        description: str = "",
        content: TemplateContent,
        visibility: str = TemplateVisibility.PRIVATE.value,
        audience_stages: Optional[list[str]] = None,
        language: str = "en",
        source: str = TemplateSource.USER.value,
    ) -> AssessmentTemplate:
        if visibility == TemplateVisibility.PUBLIC.value:
            raise ValidationError(
                "Public visibility is not reachable yet (plan-15 moderation)"
            )
        self._check_kinds(content)
        await self.validate_content(content, propose_unknown=False)
        template = AssessmentTemplate(
            key=slugify_key(title),
            version=1,
            title=title[:200],
            description=description[:2000],
            author_user_id=user_id,
            author_key=str(user_id),
            source=source,
            visibility=visibility,
            audience_stages=audience_stages or [],
            language=language[:10],
            schema_version=content.schema_version,
            content_hash=_canonical_hash(content.model_dump(mode="json")),
            ref=generate_template_ref(),
            status=TemplateStatus.DRAFT.value,
            content=content.model_dump(mode="json"),
        )
        self.db.add(template)
        await self.db.flush()
        await self.db.commit()
        await self.db.refresh(template)
        return template

    async def new_version(
        self,
        user_id: UUID,
        template_id: UUID,
        *,
        title: Optional[str] = None,
        description: Optional[str] = None,
        content: Optional[TemplateContent] = None,
        visibility: Optional[str] = None,
        status: Optional[str] = None,
    ) -> AssessmentTemplate:
        """Edits create version n+1 — versions are immutable rows (42.B)."""
        template = await self.get_template(template_id, user_id, require_owner=True)
        if visibility == TemplateVisibility.PUBLIC.value:
            raise ValidationError(
                "Public visibility is not reachable yet (plan-15 moderation)"
            )
        latest = await self._latest_version(template.key, template.author_key)
        next_version = latest.version + 1
        new_content = content or TemplateContent.model_validate(template.content)
        if content is not None:
            self._check_kinds(content)
            await self.validate_content(content, propose_unknown=False)
        row = AssessmentTemplate(
            key=template.key,
            version=next_version,
            title=title or template.title,
            description=(
                description if description is not None else template.description
            ),
            author_user_id=template.author_user_id,
            author_key=template.author_key,
            source=template.source,
            visibility=visibility or template.visibility,
            audience_stages=template.audience_stages,
            language=template.language,
            schema_version=new_content.schema_version,
            content_hash=_canonical_hash(new_content.model_dump(mode="json")),
            # The share ref identifies the template FAMILY and lives on the
            # first version only; ref lookups resolve to the latest version.
            ref=None,
            status=status or template.status,
            content=new_content.model_dump(mode="json"),
        )
        self.db.add(row)
        await self.db.commit()
        await self.db.refresh(row)
        return row

    async def _latest_version(self, key: str, author_key: str) -> AssessmentTemplate:
        rows = await self.db.execute(
            select(AssessmentTemplate)
            .where(
                AssessmentTemplate.key == key,
                AssessmentTemplate.author_key == author_key,
            )
            .order_by(AssessmentTemplate.version.desc())
            .limit(1)
        )
        template = rows.scalars().first()
        if template is None:
            raise NotFoundError("Template not found")
        return template

    async def publish(self, user_id: UUID, template_id: UUID) -> AssessmentTemplate:
        """Publish the latest draft version (authors never write into the
        shared bank — their templates are theirs)."""
        template = await self.get_template(template_id, user_id, require_owner=True)
        template.status = TemplateStatus.PUBLISHED.value
        await self.db.commit()
        await self.db.refresh(template)
        return template

    # ---------------------------------------------------- import/export

    async def export_template(self, user_id: UUID, template_id: UUID) -> dict:
        """JSON package {schema_version, metadata, content, content_hash}."""
        template = await self.get_template(template_id, user_id)
        return {
            "schema_version": TEMPLATE_SCHEMA_VERSION,
            "metadata": {
                "key": template.key,
                "title": template.title,
                "description": template.description,
                "language": template.language,
                "audience_stages": template.audience_stages,
                "version": template.version,
            },
            "content": template.content,
            "content_hash": template.content_hash,
        }

    async def import_template(
        self, user_id: UUID, package: dict
    ) -> tuple[AssessmentTemplate, dict]:
        """Import pipeline: schema check → validation → key resolution
        (unknown → proposed, import succeeds with a report) → stored as
        source=imported, private, author=importer."""
        if package.get("schema_version") != TEMPLATE_SCHEMA_VERSION:
            raise ValidationError(
                f"Unsupported template schema: {package.get('schema_version')}"
            )
        content_hash = package.get("content_hash")
        content = TemplateContent.model_validate(package.get("content") or {})
        computed = _canonical_hash(content.model_dump(mode="json"))
        if content_hash and content_hash != computed:
            raise ValidationError("content_hash mismatch — package corrupted")
        metadata = package.get("metadata") or {}
        resolution = await self.validate_content(content, propose_unknown=True)
        self._check_kinds(content)
        template = AssessmentTemplate(
            key=slugify_key(metadata.get("title") or "imported-template"),
            version=1,
            title=(metadata.get("title") or "Imported template")[:200],
            description=(metadata.get("description") or "")[:2000],
            author_user_id=user_id,
            author_key=str(user_id),
            source=TemplateSource.IMPORTED.value,
            visibility=TemplateVisibility.PRIVATE.value,
            audience_stages=metadata.get("audience_stages") or [],
            language=(metadata.get("language") or "en")[:10],
            schema_version=content.schema_version,
            content_hash=computed,
            ref=generate_template_ref(),
            status=TemplateStatus.DRAFT.value,
            content=content.model_dump(mode="json"),
        )
        self.db.add(template)
        await self.db.flush()
        await self.db.commit()
        await self.db.refresh(template)
        return template, resolution

    # ------------------------------------------------------------- runs

    async def start_run(self, user_id: UUID, template_id: UUID) -> AssessmentRun:
        """Compile the template onto the plan-23 engine: one run with
        template phases materialized as ordinary questions."""
        from app.services.assessment.runner import AssessmentService

        template = await self._latest_published(template_id, user_id)
        content = TemplateContent.model_validate(template.content)
        phase_order = [5 + i for i in range(len(content.phases))]
        context = {
            "template_id": str(template.id),
            "template_key": template.key,
            "template_title": template.title,
            "template_content": template.content,
            "phase_titles": {
                str(5 + i): phase.title for i, phase in enumerate(content.phases)
            },
        }
        service = AssessmentService(self.db)
        run = await service.create_run(
            user_id,
            AssessmentKind.TEMPLATE.value,
            context={"phase_order": phase_order, **context},
        )
        run.template_id = template.id
        await self.db.commit()
        return run

    async def _latest_published(
        self, template_id: UUID, user_id: UUID
    ) -> AssessmentTemplate:
        template = await self.get_template(template_id, user_id)
        if (
            template.status != TemplateStatus.PUBLISHED.value
            and template.author_user_id != user_id
        ):
            raise ValidationError("Template is not published")
        latest = await self._latest_version(template.key, template.author_key)
        return latest

    async def compile_results(self, run: AssessmentRun) -> dict:
        """Raw accumulated deltas → normalized levels + band (plan-23
        parity: same answer shapes, evidence upserts, fit refresh)."""
        content = TemplateContent.model_validate(
            (run.context or {}).get("template_content") or {}
        )
        raw: dict[str, float] = {}
        interests: list[str] = []
        for answer in run.answers:
            derived = answer.derived or {}
            for key, value in (derived.get("skill_levels") or {}).items():
                raw[key] = raw.get(key, 0.0) + float(value)
            for key in derived.get("interest_keys") or []:
                if key not in interests:
                    interests.append(key)
        normalization = content.normalization
        levels = {
            key: round(
                min(
                    normalization.clamp_max,
                    max(normalization.clamp_min, value * normalization.multiplier),
                ),
                1,
            )
            for key, value in raw.items()
        }
        mean = sum(levels.values()) / len(levels) if levels else 0.0
        band = None
        for candidate in normalization.bands:
            if candidate.min <= mean <= candidate.max:
                band = candidate
                break
        return {
            "raw_scores": raw,
            "levels": levels,
            "interest_keys": interests,
            "band": (
                {
                    "label": band.label,
                    "summary": band.summary,
                    "suggested_levels": band.suggested_levels,
                    "next_actions": band.next_actions,
                }
                if band
                else None
            ),
        }


def _canonical_hash(payload: dict) -> str:
    """Canonical-JSON sha256 (sorted keys, stable types) — plan-42 policy."""
    import hashlib
    import json

    canonical = json.dumps(
        payload or {}, sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
