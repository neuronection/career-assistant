"""Catalog label overlays: review-first, read-time resolution (plan 121).

A `label_overrides` row replaces one display field of a catalog entity in
one locale. Resolution has a strict fallback chain:

    approved overlay -> base label -> stable key slug

Draft and rejected rows never render: AI batches land as `draft`, and an
administrator approval is the only route to `approved` (the catalog
enrichment law). Universities and departments keep their official names
authoritative; an overlay may translate a display label, never rewrite
the stored name.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import LabelEntityKind, LabelField, LabelSource, LabelStatus
from app.models.localization_model import LabelOverride
from app.services.locale_service import SOURCE_LOCALE, normalize_locale

_FIELD_BY_PROPERTY: dict[LabelEntityKind, dict[str, LabelField]] = {
    LabelEntityKind.JOB: {
        "title": LabelField.LABEL,
        "short_description": LabelField.SHORT_DESCRIPTION,
    },
    LabelEntityKind.SKILL: {
        "label": LabelField.LABEL,
        "description": LabelField.DESCRIPTION,
    },
    LabelEntityKind.FAMILY: {
        "label": LabelField.LABEL,
        "description": LabelField.DESCRIPTION,
    },
    LabelEntityKind.UNIVERSITY: {"name": LabelField.LABEL},
    LabelEntityKind.DEPARTMENT: {"name": LabelField.LABEL},
    LabelEntityKind.METRIC_DIMENSION: {"label": LabelField.LABEL},
    LabelEntityKind.ASSESSMENT_TEMPLATE: {"title": LabelField.LABEL},
    LabelEntityKind.CV_TEMPLATE: {"title": LabelField.LABEL},
}


class LabelOverlayService:
    """Read-time overlay resolution plus the moderation queue."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def approved_map(
        self,
        kind: LabelEntityKind | str,
        entity_ids: Iterable[uuid.UUID],
        locale: str | None,
    ) -> dict[uuid.UUID, dict[str, str]]:
        """Approved overlay values keyed by entity id and stored field."""
        normalized = normalize_locale(locale)
        ids = list(set(entity_ids))
        if not normalized or normalized == SOURCE_LOCALE or not ids:
            return {}
        rows = (
            (
                await self.db.execute(
                    select(LabelOverride).where(
                        LabelOverride.entity_kind == str(kind),
                        LabelOverride.entity_id.in_(ids),
                        LabelOverride.locale == normalized,
                        LabelOverride.status == LabelStatus.APPROVED.value,
                    )
                )
            )
            .scalars()
            .all()
        )
        result: dict[uuid.UUID, dict[str, str]] = {}
        for row in rows:
            if row.value:
                result.setdefault(row.entity_id, {})[row.field] = row.value
        return result

    async def apply(
        self,
        kind: LabelEntityKind | str,
        records: Sequence[dict],
        locale: str | None,
        *,
        id_key: str = "id",
        fields: dict[str, str] | None = None,
    ) -> list[dict]:
        """Return copies of display records with approved overlays applied.

        ``fields`` maps a record property to the stored overlay field name;
        defaults come from the entity-kind map (e.g. a job's ``title`` reads
        the ``label`` overlay). Missing overlays leave the base value intact.
        """
        kind_enum = LabelEntityKind(str(kind))
        mapping = fields or {
            prop: field.value for prop, field in _FIELD_BY_PROPERTY.get(kind_enum, {}).items()
        }
        normalized = normalize_locale(locale)
        if not normalized or normalized == SOURCE_LOCALE or not mapping:
            return [dict(record) for record in records]
        ids = [record[id_key] for record in records if isinstance(record.get(id_key), uuid.UUID)]
        overlays = await self.approved_map(kind, ids, normalized)
        localized: list[dict] = []
        for record in records:
            copy = dict(record)
            record_id = copy.get(id_key)
            values = overlays.get(record_id, {}) if isinstance(record_id, uuid.UUID) else {}
            for prop, overlay_field in mapping.items():
                replacement = values.get(str(overlay_field))
                if replacement:
                    copy[prop] = replacement
            localized.append(copy)
        return localized

    async def resolve_one(
        self,
        kind: LabelEntityKind | str,
        entity_id: uuid.UUID,
        field: LabelField | str,
        base_value: str,
        locale: str | None,
    ) -> str:
        """Resolve one field: approved overlay, else the base value."""
        overlays = await self.approved_map(kind, [entity_id], locale)
        return overlays.get(entity_id, {}).get(str(field)) or base_value

    async def ensure_draft(
        self,
        *,
        entity_kind: LabelEntityKind | str,
        entity_id: uuid.UUID,
        locale: str,
        field: LabelField | str,
        value: str,
        source: LabelSource = LabelSource.AI_DRAFT,
    ) -> LabelOverride:
        """Create or refresh a draft row; never overwrites an approved row."""
        normalized = normalize_locale(locale)
        if normalized is None or normalized == SOURCE_LOCALE:
            from app.core.errors import ValidationError

            raise ValidationError("Overlays target a non-source locale")
        row = (
            (
                await self.db.execute(
                    select(LabelOverride).where(
                        LabelOverride.entity_kind == str(entity_kind),
                        LabelOverride.entity_id == entity_id,
                        LabelOverride.locale == normalized,
                        LabelOverride.field == str(field),
                    )
                )
            )
            .scalars()
            .first()
        )
        if row is not None and row.status == LabelStatus.APPROVED.value:
            return row
        if row is None:
            row = LabelOverride(
                entity_kind=str(entity_kind),
                entity_id=entity_id,
                locale=normalized,
                field=str(field),
                value=value,
                source=str(source),
                status=LabelStatus.DRAFT.value,
            )
        else:
            row.value = value
            row.source = str(source)
            row.status = LabelStatus.DRAFT.value
        self.db.add(row)
        await self.db.flush()
        return row

    async def queue(
        self,
        *,
        locale: str | None = None,
        row_status: LabelStatus | str | None = LabelStatus.DRAFT,
        limit: int = 100,
    ) -> list[LabelOverride]:
        """Overlay rows awaiting (or having completed) review."""
        query = select(LabelOverride).order_by(LabelOverride.created_at)
        normalized = normalize_locale(locale)
        if normalized:
            query = query.where(LabelOverride.locale == normalized)
        if row_status:
            query = query.where(LabelOverride.status == str(row_status))
        return list((await self.db.execute(query.limit(limit))).scalars().all())

    async def set_status(self, overlay_id: uuid.UUID, status: LabelStatus) -> LabelOverride:
        """Approve or reject one overlay (approval is the only rendering route)."""
        row = (
            (await self.db.execute(select(LabelOverride).where(LabelOverride.id == overlay_id)))
            .scalars()
            .first()
        )
        if row is None:
            from app.core.errors import NotFoundError

            raise NotFoundError("Overlay not found")
        row.status = str(status)
        self.db.add(row)
        await self.db.commit()
        await self.db.refresh(row)
        return row

    async def edit_value(self, overlay_id: uuid.UUID, value: str) -> LabelOverride:
        """Reviewer edit of a drafted value (status is unchanged)."""
        row = (
            (await self.db.execute(select(LabelOverride).where(LabelOverride.id == overlay_id)))
            .scalars()
            .first()
        )
        if row is None:
            from app.core.errors import NotFoundError

            raise NotFoundError("Overlay not found")
        row.value = value
        self.db.add(row)
        await self.db.commit()
        await self.db.refresh(row)
        return row
