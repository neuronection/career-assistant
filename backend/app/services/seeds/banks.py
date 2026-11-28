"""Bank entity adapters for the seed lane (plan 225 S0-S4).

The six bank formats ride the same parse → plan → apply lane as the catalog:
identity is the stored ``seed_key``, content is compared by the item digest,
and removal retires the stored row instead of deleting it. S0 ships the
assessment-template adapter; S1 the assessment-question adapter; S2 the
CV-template adapter; S3 the metric-dimension and category-anchor adapters;
S4 the skill-pack adapter.

Versioned templates publish immutable rows: a new pack version creates a new
row, a removal retires the row, and a changed body at an already-applied
version is a plan-time conflict. The lane's canonical item digest
(``ParsedItem.content_hash``) drives no-op/update detection through
``SeedItemProvenance``; CV templates and skill packs also keep their own
content hash.

Skill packs are the one bank whose apply never takes effect: a new version
lands ``draft`` so no model ever sees unreviewed instructions. An admin
publishes a draft explicitly, which retires the same-key predecessor; revoke
restores the previous version's published state. A key dropped from a pack is
left untouched (a plan warning) rather than auto-retired.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.seed_pack.errors import BANK_UNSUPPORTED, SeedPackError
from app.models.assessment_model import AssessmentQuestion
from app.models.assessment_template_model import AssessmentTemplate
from app.models.cv_template_model import CvTemplate
from app.models.metric_model import MetricCategoryAnchor, MetricDimension
from app.models.seed_model import SeedItemProvenance
from app.models.skill_pack_model import AISkillPack

REFERENCE_BANK_PACK = "neuronection-reference-banks"
REFERENCE_BANK_SUBPATH = "packs/neuronection/reference-banks"

ENTITY_ASSESSMENT_QUESTION = "assessment_question"
ENTITY_ASSESSMENT_TEMPLATE = "assessment_template"
ENTITY_CV_TEMPLATE = "cv_template"
ENTITY_METRIC_DIMENSION = "metric_dimension"
ENTITY_METRIC_CATEGORY_ANCHOR = "metric_category_anchor"
ENTITY_SKILL_PACK = "skill_pack"

SEED_PREFIX_ENTITY: dict[str, str] = {
    "assessment-question": ENTITY_ASSESSMENT_QUESTION,
    "assessment-template": ENTITY_ASSESSMENT_TEMPLATE,
    "cv-template": ENTITY_CV_TEMPLATE,
    "metric-dimension": ENTITY_METRIC_DIMENSION,
    "interest-category": ENTITY_METRIC_CATEGORY_ANCHOR,
    "skill-pack": ENTITY_SKILL_PACK,
}


def entity_for_seed_key(seed_key: str) -> str | None:
    """The bank entity type a stored seed key belongs to, by its prefix."""
    return SEED_PREFIX_ENTITY.get(seed_key.split(":", 1)[0])


def skill_pack_key(seed_key: str) -> str:
    """The skill-pack ``key`` of a ``skill-pack:<key>/v<version>`` seed key."""
    body = seed_key.split(":", 1)[1] if ":" in seed_key else seed_key
    return body.rsplit("/v", 1)[0]


BANK_ENTITY_MODELS: dict[str, Any] = {
    ENTITY_ASSESSMENT_QUESTION: AssessmentQuestion,
    ENTITY_ASSESSMENT_TEMPLATE: AssessmentTemplate,
    ENTITY_CV_TEMPLATE: CvTemplate,
    ENTITY_METRIC_DIMENSION: MetricDimension,
    ENTITY_METRIC_CATEGORY_ANCHOR: MetricCategoryAnchor,
    ENTITY_SKILL_PACK: AISkillPack,
}
ITEM_ENTITY = {
    "assessment_questions": ENTITY_ASSESSMENT_QUESTION,
    "assessment_templates": ENTITY_ASSESSMENT_TEMPLATE,
    "cv_templates": ENTITY_CV_TEMPLATE,
    "metric_dimensions": ENTITY_METRIC_DIMENSION,
    "metric_category_anchors": ENTITY_METRIC_CATEGORY_ANCHOR,
    "skill_packs": ENTITY_SKILL_PACK,
}
BANK_ITEM_TYPES = frozenset(ITEM_ENTITY)
ENTITY_FORMATS = {entity: format_name for format_name, entity in ITEM_ENTITY.items()}

APPLY_ORDER = (
    ENTITY_METRIC_DIMENSION,
    ENTITY_METRIC_CATEGORY_ANCHOR,
    ENTITY_ASSESSMENT_QUESTION,
    ENTITY_ASSESSMENT_TEMPLATE,
    ENTITY_CV_TEMPLATE,
    ENTITY_SKILL_PACK,
)
RETIRE_ORDER = tuple(reversed(APPLY_ORDER))

RETIRE: dict[str, tuple[str, Any]] = {
    ENTITY_ASSESSMENT_QUESTION: ("status", "retired"),
    ENTITY_ASSESSMENT_TEMPLATE: ("status", "retired"),
    ENTITY_CV_TEMPLATE: ("status", "retired"),
    ENTITY_METRIC_DIMENSION: ("status", "retired"),
    ENTITY_METRIC_CATEGORY_ANCHOR: ("status", "retired"),
    ENTITY_SKILL_PACK: ("status", "retired"),
}

COUNT_KEYS: dict[str, str] = {
    ENTITY_ASSESSMENT_QUESTION: "assessment_questions",
    ENTITY_ASSESSMENT_TEMPLATE: "assessment_templates",
    ENTITY_CV_TEMPLATE: "cv_templates",
    ENTITY_METRIC_DIMENSION: "metric_dimensions",
    ENTITY_METRIC_CATEGORY_ANCHOR: "metric_category_anchors",
    ENTITY_SKILL_PACK: "skill_packs",
}


def stage(action: str, entity: str) -> int:
    order = RETIRE_ORDER if action == "retire" else APPLY_ORDER
    return order.index(entity) if entity in order else -1


async def load_current(db: AsyncSession) -> dict[tuple[str, str], Any]:
    current: dict[tuple[str, str], Any] = {}
    for entity, model in BANK_ENTITY_MODELS.items():
        rows = cast(
            list[Any],
            (await db.execute(select(model).where(model.seed_key.is_not(None)))).scalars().all(),
        )
        for row in rows:
            current[(entity, row.seed_key)] = row
    return current


async def apply_assessment_question(
    db: AsyncSession, payload: dict[str, Any], row: AssessmentQuestion | None, *, seed_key: str
) -> AssessmentQuestion:
    """Upsert one bank question with its options, stages and time split.

    Questions publish as ``active`` (their lifecycle is active/retired and the
    phase reader selects active bank rows); removal retires them.
    """
    fields = {
        "phase": int(payload["phase"]),
        "kind": str(payload["kind"]),
        "prompt": str(payload["prompt"]),
        "help": str(payload.get("help") or ""),
        "options": list(payload.get("options") or []),
        "time_split": payload.get("time_split"),
        "audience_stages": list(payload.get("audience_stages") or []),
        "source": "bank",
        "status": "active",
        "sort_index": int(payload.get("sort_index") or 0),
    }
    if row is None:
        row = AssessmentQuestion(run_id=None, **fields)
        db.add(row)
    else:
        for key, value in fields.items():
            setattr(row, key, value)
    row.seed_key = seed_key
    await db.flush()
    return row


def template_content_hash(payload: dict[str, Any]) -> str:
    """Canonical hash of a battery's validated content (the row's hash column)."""
    from app.schemas.assessment_template import TemplateContent
    from app.services.assessment.assessment_templates import _canonical_hash

    content = TemplateContent.model_validate(payload["content"])
    return _canonical_hash(content.model_dump(mode="json"))


def cv_template_content_hash(payload: dict[str, Any]) -> str:
    """Canonical hash of a CV template's validated content (the row's hash column)."""
    from app.schemas.cv_template import TemplateContent
    from app.services.postings.engagement_service import canonical_hash

    content = TemplateContent.model_validate(payload["content"])
    return canonical_hash(content.model_dump(mode="json"))


async def apply_assessment_template(
    db: AsyncSession, payload: dict[str, Any], row: AssessmentTemplate | None, *, seed_key: str
) -> AssessmentTemplate:
    from app.schemas.assessment_template import TemplateContent
    from app.services.assessment.assessment_templates import (
        _canonical_hash,
        generate_template_ref,
    )

    content = TemplateContent.model_validate(payload["content"])
    dumped = content.model_dump(mode="json")
    fields = {
        "key": str(payload["key"]),
        "version": int(payload["version"]),
        "title": str(payload["title"]),
        "description": str(payload.get("description") or ""),
        "author_user_id": None,
        "author_key": "bank",
        "source": "bank",
        "visibility": "private",
        "audience_stages": list(payload.get("audience_stages") or []),
        "language": str(payload.get("language") or "en"),
        "schema_version": int(payload.get("schema_version") or content.schema_version),
        "content_hash": _canonical_hash(dumped),
        "status": "published",
        "content": dumped,
    }
    if row is None:
        row = AssessmentTemplate(ref=generate_template_ref(), **fields)
        db.add(row)
    else:
        for key, value in fields.items():
            setattr(row, key, value)
    row.seed_key = seed_key
    await db.flush()
    return row


async def apply_cv_template(
    db: AsyncSession, payload: dict[str, Any], row: CvTemplate | None, *, seed_key: str
) -> CvTemplate:
    """Upsert one immutable CV template version as a published bank row."""
    from app.models.enums import CvTemplateSource, CvTemplateStatus
    from app.schemas.cv_template import TemplateContent
    from app.services.cv.cv_template_service import TEMPLATE_SCHEMA_VERSION
    from app.services.postings.engagement_service import canonical_hash

    content = TemplateContent.model_validate(payload["content"])
    dumped = content.model_dump(mode="json")
    fields = {
        "key": str(payload["key"]),
        "version": int(payload["version"]),
        "title": str(payload["title"]),
        "description": str(payload.get("description") or ""),
        "author_user_id": None,
        "author_key": "bank",
        "source": CvTemplateSource.BANK.value,
        "visibility": "private",
        "language": str(payload.get("language") or "en"),
        "page_size": str(payload.get("page_size") or "a4"),
        "ats_safe": bool(payload.get("ats_safe", False)),
        "schema_version": TEMPLATE_SCHEMA_VERSION,
        "content_hash": canonical_hash(dumped),
        "status": CvTemplateStatus.PUBLISHED.value,
        "content": dumped,
    }
    if row is None:
        row = CvTemplate(**fields)
        db.add(row)
    else:
        for key, value in fields.items():
            setattr(row, key, value)
    row.seed_key = seed_key
    await db.flush()
    return row


async def apply_metric_dimension(
    db: AsyncSession, payload: dict[str, Any], row: MetricDimension | None, *, seed_key: str
) -> MetricDimension:
    """Upsert one published metric dimension."""
    fields = {
        "key": str(payload["key"]),
        "label": str(payload["label"]),
        "group": str(payload["group"]),
        "description": str(payload.get("description") or ""),
        "scale": str(payload.get("scale") or "scalar"),
        "reverse_score": bool(payload.get("reverse_score", False)),
        "sources": list(payload.get("sources") or []),
        "consumers": list(payload.get("consumers") or []),
        "status": "published",
    }
    if row is None:
        row = MetricDimension(**fields)
        db.add(row)
    else:
        for key, value in fields.items():
            setattr(row, key, value)
    row.seed_key = seed_key
    await db.flush()
    return row


async def apply_metric_category_anchor(
    db: AsyncSession, payload: dict[str, Any], row: MetricCategoryAnchor | None, *, seed_key: str
) -> MetricCategoryAnchor:
    """Upsert one active interest-category → Holland-letter anchor."""
    fields = {
        "category": str(payload["category"]),
        "letter": str(payload["letter"]),
        "status": "published",
    }
    if row is None:
        row = MetricCategoryAnchor(**fields)
        db.add(row)
    else:
        for key, value in fields.items():
            setattr(row, key, value)
    row.seed_key = seed_key
    await db.flush()
    return row


def skill_pack_content_hash(payload: dict[str, Any]) -> str:
    """Canonical hash of a skill pack's instructions (the row's hash column)."""
    from app.services.postings.engagement_service import canonical_hash

    return canonical_hash({"instructions": str(payload["instructions"])})


async def apply_skill_pack(
    db: AsyncSession, payload: dict[str, Any], row: AISkillPack | None, *, seed_key: str
) -> AISkillPack:
    """Upsert one skill-pack version as a ``draft`` (never published).

    The apply lane may create or restore a row, but it never makes an
    instruction live: publishing is the explicit admin step.
    """
    fields = {
        "key": str(payload["key"]),
        "version": int(payload["version"]),
        "title": str(payload["title"]),
        "task": str(payload["task"]),
        "instructions": str(payload["instructions"]),
        "author_user_id": None,
        "author_key": "bank",
        "content_hash": skill_pack_content_hash(payload),
        "status": "draft",
    }
    if row is None:
        row = AISkillPack(**fields)
        db.add(row)
    else:
        for key, value in fields.items():
            setattr(row, key, value)
    row.seed_key = seed_key
    await db.flush()
    return row


BANK_FORMATS: dict[str, Callable[..., Any] | None] = {
    "assessment_questions": apply_assessment_question,
    "assessment_templates": apply_assessment_template,
    "cv_templates": apply_cv_template,
    "metric_dimensions": apply_metric_dimension,
    "metric_category_anchors": apply_metric_category_anchor,
    "skill_packs": apply_skill_pack,
}


def adapter_for(format_name: str) -> Callable[..., Any]:
    """The writer for a bank format; refuses a registered format without one."""
    adapter = BANK_FORMATS.get(format_name)
    if adapter is None:
        raise SeedPackError(BANK_UNSUPPORTED, f"no bank adapter for {format_name}")
    return adapter


def require_adapter(format_name: str) -> None:
    """Plan-time check: a registered bank format must ship its adapter."""
    if format_name in BANK_ITEM_TYPES and BANK_FORMATS.get(format_name) is None:
        raise SeedPackError(BANK_UNSUPPORTED, f"no bank adapter for {format_name}")


def adapter_for_entity(entity: str) -> Callable[..., Any]:
    """The writer for a bank entity type."""
    return adapter_for(ENTITY_FORMATS[entity])


async def retire(db: AsyncSession, entity: str, row: Any) -> None:
    field, value = RETIRE[entity]
    setattr(row, field, value)
    await db.flush()


async def skill_pack_seed_keys_for_version(
    db: AsyncSession, version_id, *, status: str
) -> list[str]:
    """Seed keys of the skill packs a source version owns in ``status``."""
    version_keys = (
        (
            await db.execute(
                select(SeedItemProvenance.seed_key).where(
                    SeedItemProvenance.entity_type == ENTITY_SKILL_PACK,
                    SeedItemProvenance.source_version_id == version_id,
                )
            )
        )
        .scalars()
        .all()
    )
    if not version_keys:
        return []
    found = (
        (
            await db.execute(
                select(AISkillPack.seed_key).where(
                    AISkillPack.seed_key.in_(version_keys),
                    AISkillPack.status == status,
                )
            )
        )
        .scalars()
        .all()
    )
    return [seed_key for seed_key in found if seed_key is not None]


async def retire_published_skill_packs_for_version(db: AsyncSession, version_id) -> list[str]:
    """Retire the skill packs a revoked version had published.

    Revoking a source version must stop serving the behavior it published;
    the previous version's rows are republished by the revoke path.
    """
    seed_keys = await skill_pack_seed_keys_for_version(db, version_id, status="published")
    for seed_key in seed_keys:
        row = await db.scalar(select(AISkillPack).where(AISkillPack.seed_key == seed_key))
        if row is not None:
            row.status = "retired"
    if seed_keys:
        await db.flush()
    return seed_keys


async def restore_published_skill_packs_for_version(db: AsyncSession, version_id) -> list[str]:
    """Republish the skill packs a restored version had published before."""
    seed_keys = await skill_pack_seed_keys_for_version(db, version_id, status="retired")
    for seed_key in seed_keys:
        row = await db.scalar(select(AISkillPack).where(AISkillPack.seed_key == seed_key))
        if row is not None:
            row.status = "published"
    if seed_keys:
        await db.flush()
    return seed_keys


def preview_fields(entity: str, payload: dict[str, Any], row: Any = None) -> dict[str, Any]:
    """The bounded preview an admin sees for a bank plan item."""
    source = payload or row
    if source is None:
        return {}
    if entity == ENTITY_ASSESSMENT_QUESTION:
        options = getattr(source, "options", None)
        if options is None:
            options = source.get("options")
        return {
            "prompt": _get(source, "prompt"),
            "phase": _get(source, "phase"),
            "kind": _get(source, "kind"),
            "options": len(options or []),
        }
    if entity == ENTITY_ASSESSMENT_TEMPLATE:
        content = _get(source, "content") or {}
        phases = content.get("phases") or []
        return {
            "title": _get(source, "title"),
            "version": _get(source, "version"),
            "phases": len(phases),
            "questions": sum(len(phase.get("questions") or []) for phase in phases),
        }
    if entity == ENTITY_CV_TEMPLATE:
        return {
            "title": _get(source, "title"),
            "version": _get(source, "version"),
            "page_size": _get(source, "page_size"),
        }
    if entity == ENTITY_METRIC_DIMENSION:
        return {
            "key": _get(source, "key"),
            "label": _get(source, "label"),
            "group": _get(source, "group"),
        }
    if entity == ENTITY_METRIC_CATEGORY_ANCHOR:
        return {"category": _get(source, "category"), "letter": _get(source, "letter")}
    if entity == ENTITY_SKILL_PACK:
        instructions = _get(source, "instructions")
        content_hash = _get(source, "content_hash")
        if not content_hash and isinstance(instructions, str):
            content_hash = skill_pack_content_hash({"instructions": instructions})
        return {
            "key": _get(source, "key"),
            "title": _get(source, "title"),
            "version": _get(source, "version"),
            "task": _get(source, "task"),
            "instructions": instructions,
            "content_hash": content_hash,
        }
    return {}


def _get(source: Any, field: str) -> Any:
    if isinstance(source, dict):
        return source.get(field)
    return getattr(source, field, None)


__all__ = [
    "APPLY_ORDER",
    "BANK_ENTITY_MODELS",
    "BANK_FORMATS",
    "BANK_ITEM_TYPES",
    "COUNT_KEYS",
    "ENTITY_ASSESSMENT_QUESTION",
    "ENTITY_ASSESSMENT_TEMPLATE",
    "ENTITY_CV_TEMPLATE",
    "ENTITY_FORMATS",
    "ENTITY_METRIC_CATEGORY_ANCHOR",
    "ENTITY_METRIC_DIMENSION",
    "ENTITY_SKILL_PACK",
    "ITEM_ENTITY",
    "REFERENCE_BANK_PACK",
    "REFERENCE_BANK_SUBPATH",
    "RETIRE",
    "RETIRE_ORDER",
    "SEED_PREFIX_ENTITY",
    "adapter_for",
    "adapter_for_entity",
    "apply_assessment_question",
    "apply_assessment_template",
    "apply_cv_template",
    "apply_metric_category_anchor",
    "apply_metric_dimension",
    "apply_skill_pack",
    "cv_template_content_hash",
    "entity_for_seed_key",
    "load_current",
    "preview_fields",
    "require_adapter",
    "restore_published_skill_packs_for_version",
    "retire",
    "retire_published_skill_packs_for_version",
    "skill_pack_content_hash",
    "skill_pack_key",
    "skill_pack_seed_keys_for_version",
    "stage",
    "template_content_hash",
]
