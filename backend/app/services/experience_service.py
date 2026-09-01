"""Experience service (plan 40): structured CRUD, derivation, evidence.

Draft → active review flow: items land as `draft` (CV parse) or `active`
(self-report); derivation previews are computed live and applied
explicitly — conflicts with existing self-report levels route through the
plan-23 reconciliation shape (recorded, never silently overwritten).
"""

import re
import uuid
from datetime import date, datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import NotFoundError, ValidationError
from app.models.experience_model import (
    ExperienceAchievement,
    ExperienceItem,
    ExperienceSkill,
    Organization,
    SkillEvidence,
)
from app.models.taxonomy_model import Skill
from app.models.user_model import UserSkill
from app.services.experience_derivation import (
    DerivedSkill,
    default_last_used,
    derive_skill_months,
    derivation_summary,
    years_of_experience,
)

CONFLICT_STEP = 2.0


def slugify_org(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "").strip().lower()).strip("-")
    return slug[:110] or f"org-{uuid.uuid4().hex[:8]}"


class ExperienceService:
    """CRUD over experience items + derivation/apply + evidence trace."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # -------------------------------------------------------------- items

    async def list_items(
        self, user_id: UUID, *, status: Optional[str] = None
    ) -> list[ExperienceItem]:
        query = (
            select(ExperienceItem)
            .options(
                selectinload(ExperienceItem.skills).selectinload(ExperienceSkill.skill),
                selectinload(ExperienceItem.achievements),
            )
            .where(ExperienceItem.user_id == user_id)
            .order_by(ExperienceItem.start.desc())
        )
        if status:
            query = query.where(ExperienceItem.status == status)
        return list((await self.db.execute(query)).scalars().unique().all())

    async def get_item(self, user_id: UUID, item_id: UUID) -> ExperienceItem:
        rows = await self.db.execute(
            select(ExperienceItem)
            .options(
                selectinload(ExperienceItem.skills).selectinload(ExperienceSkill.skill),
                selectinload(ExperienceItem.achievements),
            )
            .where(ExperienceItem.id == item_id, ExperienceItem.user_id == user_id)
        )
        item = rows.scalars().unique().first()
        if item is None:
            raise NotFoundError("Experience item not found")
        return item

    async def create_item(self, user_id: UUID, payload: dict) -> ExperienceItem:
        from app.models.enums import ExperienceKind

        kind = payload.get("kind", ExperienceKind.PROJECT.value)
        if kind not in ExperienceKind._value2member_map_:
            raise ValidationError(f"Unknown experience kind: {kind}")
        start = _parse_date(payload.get("start"))
        if start is None:
            raise ValidationError("start (YYYY-MM-DD) is required")
        end = _parse_date(payload.get("end"))
        open_ended = bool(payload.get("open_ended"))
        if end is None and not open_ended:
            raise ValidationError("end is required unless the item is open-ended")
        if end is not None and end < start:
            raise ValidationError("end cannot precede start")
        org = await self._resolve_org(payload.get("org_name") or "")
        item = ExperienceItem(
            user_id=user_id,
            kind=kind,
            title=payload["title"],
            org_id=org.id if org else None,
            org_name=payload.get("org_name") or "",
            start=start,
            end=end,
            open_ended=open_ended,
            hours_per_week=payload.get("hours_per_week"),
            onsite_policy=payload.get("onsite_policy"),
            description=payload.get("description") or "",
            links=payload.get("links") or [],
            source=payload.get("source", "self_report"),
            status=payload.get("status", "active"),
        )
        self.db.add(item)
        await self.db.flush()
        await self._replace_skills(item, payload.get("skills") or [])
        await self._replace_achievements(item, payload.get("achievements") or [])
        await self.db.commit()
        await self.db.refresh(item)
        return item

    async def update_item(
        self, user_id: UUID, item_id: UUID, payload: dict
    ) -> ExperienceItem:
        item = await self.get_item(user_id, item_id)
        if "title" in payload:
            item.title = payload["title"]
        if "kind" in payload:
            item.kind = payload["kind"]
        if "org_name" in payload:
            org = await self._resolve_org(payload.get("org_name") or "")
            item.org_id = org.id if org else None
            item.org_name = payload.get("org_name") or ""
        if "start" in payload:
            start = _parse_date(payload.get("start"))
            if start is None:
                raise ValidationError("start must be YYYY-MM-DD")
            item.start = start
        if "end" in payload or "open_ended" in payload:
            end = _parse_date(payload.get("end"))
            open_ended = bool(payload.get("open_ended", item.open_ended))
            if (
                end is None
                and not open_ended
                and not item.open_ended
                and "end" in payload
            ):
                raise ValidationError("end is required unless the item is open-ended")
            item.end = end
            item.open_ended = open_ended
        if "hours_per_week" in payload:
            item.hours_per_week = payload.get("hours_per_week")
        if "onsite_policy" in payload:
            item.onsite_policy = payload.get("onsite_policy")
        if "description" in payload:
            item.description = payload.get("description") or ""
        if "links" in payload:
            item.links = payload.get("links") or []
        if "status" in payload:
            if payload["status"] not in ("draft", "active"):
                raise ValidationError("status must be draft or active")
            item.status = payload["status"]
        if "skills" in payload:
            await self._replace_skills(item, payload.get("skills") or [])
        if "achievements" in payload:
            await self._replace_achievements(item, payload.get("achievements") or [])
        await self.db.commit()
        await self.db.refresh(item)
        return item

    async def delete_item(self, user_id: UUID, item_id: UUID) -> None:
        item = await self.get_item(user_id, item_id)
        await self.db.delete(item)
        await self.db.commit()

    async def _replace_skills(self, item: ExperienceItem, skills: list[dict]) -> None:
        """Full-replace of the item's skill participations."""
        existing_rows = (
            (
                await self.db.execute(
                    select(ExperienceSkill).where(
                        ExperienceSkill.experience_id == item.id
                    )
                )
            )
            .scalars()
            .all()
        )
        for row in existing_rows:
            await self.db.delete(row)
        await self.db.flush()
        if not skills:
            return
        keys = [s.get("skill_key") for s in skills if s.get("skill_key")]
        rows = {
            s.key: s
            for s in (await self.db.execute(select(Skill).where(Skill.key.in_(keys))))
            .scalars()
            .all()
        }
        unknown = [k for k in keys if k not in rows]
        if unknown:
            raise ValidationError(
                f"Unknown skill keys: {', '.join(sorted(set(unknown)))}"
            )
        for entry in skills:
            skill = rows[entry["skill_key"]]
            role = entry.get("role_in_item", "primary")
            if role not in ("primary", "secondary", "exposure"):
                raise ValidationError(f"Invalid role_in_item: {role}")
            level_claim = entry.get("level_claim")
            if level_claim is not None and not 1 <= int(level_claim) <= 10:
                raise ValidationError("level_claim must be 1–10")
            self.db.add(
                ExperienceSkill(
                    experience_id=item.id,
                    skill_id=skill.id,
                    role_in_item=role,
                    level_claim=level_claim,
                    last_used=_parse_date(entry.get("last_used"))
                    or default_last_used(item.end, item.open_ended),
                )
            )
        await self.db.flush()

    async def _replace_achievements(
        self, item: ExperienceItem, achievements: list[dict]
    ) -> None:
        existing_rows = (
            (
                await self.db.execute(
                    select(ExperienceAchievement).where(
                        ExperienceAchievement.experience_id == item.id
                    )
                )
            )
            .scalars()
            .all()
        )
        for row in existing_rows:
            await self.db.delete(row)
        await self.db.flush()
        for entry in achievements:
            metric = entry.get("metric")
            if metric is not None:
                if metric.get("kind") not in (
                    "time_saved",
                    "scale",
                    "revenue",
                    "quality",
                ):
                    raise ValidationError(f"Unknown metric kind: {metric.get('kind')}")
            self.db.add(
                ExperienceAchievement(
                    experience_id=item.id,
                    text=entry.get("text", "")[:500],
                    metric=metric,
                )
            )
        await self.db.flush()

    async def _resolve_org(self, name: str) -> Optional[Organization]:
        """Find-or-propose by slug (plan 39 adds the matcher/merge)."""
        name = (name or "").strip()
        if not name:
            return None
        key = slugify_org(name)
        rows = await self.db.execute(
            select(Organization).where(Organization.key == key)
        )
        org = rows.scalars().first()
        if org is not None:
            return org
        org = Organization(
            key=key,
            name=name[:200],
            status="proposed",
            provenance={"source": "experience"},
        )
        self.db.add(org)
        await self.db.flush()
        return org

    # -------------------------------------------------------- derivation

    async def _participations(self, user_id: UUID) -> list[dict]:
        rows = await self.db.execute(
            select(ExperienceItem)
            .options(selectinload(ExperienceItem.skills))
            .where(
                ExperienceItem.user_id == user_id,
                ExperienceItem.status == "active",
            )
        )
        items = rows.scalars().unique().all()
        participations: list[dict] = []
        for item in items:
            for link in item.skills:
                participations.append(
                    {
                        "item": item,
                        "skill_id": link.skill_id,
                        "role_in_item": link.role_in_item,
                    }
                )
        return participations

    async def derivation(self, user_id: UUID) -> dict:
        """Live preview: derived levels + years, never written."""
        participations = await self._participations(user_id)
        derived = derive_skill_months(participations)
        labels = await self._skill_labels(set(derived.keys()))
        items = await self.list_items(user_id, status="active")
        return {
            "skills": [
                derivation_summary(derived[key], labels.get(key, ""))
                for key in sorted(derived, key=lambda k: -derived[k].months)
            ],
            "years_of_experience": years_of_experience(items),
        }

    async def apply_derivation(self, user_id: UUID) -> dict:
        """Write derived levels + evidence rows (review-first contract).

        Existing levels: |existing − derived| ≤ 2 updates (source=
        experience, confidence attached); larger gaps record a conflict
        and leave the row untouched.
        """
        participations = await self._participations(user_id)
        derived = derive_skill_months(participations)
        labels = await self._skill_labels(set(derived.keys()))
        existing_rows = {
            row.skill_id: row
            for row in (
                await self.db.execute(
                    select(UserSkill).where(UserSkill.user_id == user_id)
                )
            )
            .scalars()
            .all()
        }
        applied = 0
        conflicts: list[dict] = []
        for skill_id, derived_skill in derived.items():
            sid = UUID(skill_id)
            existing = existing_rows.get(sid)
            target = int(round(derived_skill.level))
            await self._write_evidence(user_id, sid, derived_skill, participations)
            if existing is None:
                self.db.add(
                    UserSkill(
                        user_id=user_id,
                        skill_id=sid,
                        level=max(1, target),
                        source="experience",
                        confidence=derived_skill.confidence,
                    )
                )
                applied += 1
            elif abs(existing.level - derived_skill.level) > CONFLICT_STEP:
                conflicts.append(
                    {
                        "key": labels.get(skill_id, skill_id),
                        "self_level": existing.level,
                        "derived_level": derived_skill.level,
                    }
                )
            else:
                existing.level = target
                existing.source = "experience"
                existing.confidence = derived_skill.confidence
                applied += 1
        await self.db.commit()
        return {
            "applied": applied,
            "conflicts": conflicts,
            "derived": [
                derivation_summary(derived[key], labels.get(key, ""))
                for key in sorted(derived, key=lambda k: -derived[k].months)
            ],
        }

    async def _write_evidence(
        self,
        user_id: UUID,
        skill_id: UUID,
        derived_skill: DerivedSkill,
        participations: list[dict],
    ) -> None:
        """One skill_evidence row per supporting item (source set: item)."""
        for item_id in derived_skill.supporting_items:
            self.db.add(
                SkillEvidence(
                    user_id=user_id,
                    skill_id=skill_id,
                    experience_item_id=UUID(item_id),
                    note="derived from experience",
                    level_value=derived_skill.level,
                    confidence=derived_skill.confidence,
                    claimed_at=datetime.now(timezone.utc),
                )
            )

    async def _skill_labels(self, skill_ids: set[str]) -> dict[str, str]:
        if not skill_ids:
            return {}
        ids = [UUID(s) for s in skill_ids]
        rows = await self.db.execute(select(Skill).where(Skill.id.in_(ids)))
        return {str(s.id): s.label for s in rows.scalars().all()}

    # ----------------------------------------------------------- evidence

    async def skill_evidence(self, user_id: UUID, skill_id: UUID) -> dict:
        """Trace: which items/runs/documents support this skill's level."""
        rows = await self.db.execute(
            select(SkillEvidence)
            .options(selectinload(SkillEvidence.experience_item))
            .where(
                SkillEvidence.user_id == user_id,
                SkillEvidence.skill_id == skill_id,
            )
            .order_by(SkillEvidence.claimed_at.desc())
        )
        evidence = rows.scalars().unique().all()
        return {
            "skill_id": str(skill_id),
            "items": [
                {
                    "id": str(row.id),
                    "source": (
                        "assessment"
                        if row.assessment_run_id is not None
                        else "experience"
                        if row.experience_item_id is not None
                        else "cv_document"
                    ),
                    "experience_item": (
                        {
                            "id": str(row.experience_item.id),
                            "title": row.experience_item.title,
                            "kind": row.experience_item.kind,
                        }
                        if row.experience_item is not None
                        else None
                    ),
                    "level_value": float(row.level_value)
                    if row.level_value is not None
                    else None,
                    "confidence": float(row.confidence)
                    if row.confidence is not None
                    else None,
                    "note": row.note,
                    "claimed_at": row.claimed_at,
                }
                for row in evidence
            ],
        }


def _parse_date(value) -> Optional[date]:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValidationError(f"Invalid date: {value!r}") from exc
