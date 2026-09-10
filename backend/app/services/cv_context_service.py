"""CV context engine: profile data → renderer snapshot.

A code-referenced source registry binds each profile
entity to a typed resolver. Per-CV selection (`CvContextSelection` on the
document) resolves deterministically into the snapshot the
renderer consumes, plus a traceable resolution map: snapshot rows map
1:1 (by position) to `{source_key, item_id}` refs, so every rendered
value is auditable. Ineligible-by-design data (constraints, work
preferences, dislikes) is never registered as a render source — it
cannot leak into a CV.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.document_model import Document
from app.models.experience_model import ExperienceItem, ExperienceSkill
from app.models.profile_entities_model import (
    Certification,
    EducationItem,
    ProfileAchievement,
)
from app.models.user_model import Profile, User, UserInterest, UserSkill
from app.models.university_model import Department
from app.schemas.cv import CvContextSelection

SCALAR_KEYS = {"basics", "summary"}


class CvContextItem(BaseModel):
    """One resolvable context unit with its snapshot payload."""

    item_id: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=200)
    detail: str = ""
    payload: dict = Field(default_factory=dict)
    updated_at: datetime


class CvContextSourceDef:
    """Registry entry: one profile entity kind bound to its resolver."""

    def __init__(
        self,
        key: str,
        label: str,
        description: str,
        resolver: Callable[[AsyncSession, uuid.UUID], Awaitable[list[CvContextItem]]],
    ):
        self.key = key
        self.label = label
        self.description = description
        self.usage = "render"
        self.resolver = resolver


def _ym(value: Any) -> str:
    """Renderer period format: YYYY-MM (month precision, never guessed)."""
    if value is None:
        return ""
    return f"{value.year:04d}-{value.month:02d}"


# ------------------------------------------------------------- resolvers


async def _resolve_basics(
    db: AsyncSession, user_id: uuid.UUID, photo_document_id: uuid.UUID | None = None
) -> list[CvContextItem]:
    user = (await db.execute(select(User).where(User.id == user_id))).scalars().first()
    if user is None:
        return []
    profile = (
        (await db.execute(select(Profile).where(Profile.user_id == user_id)))
        .scalars()
        .first()
    )
    basics = dict(profile.basics or {}) if profile else {}
    effective_photo_id = photo_document_id or (
        profile.photo_document_id if profile else None
    )
    photo_uri = ""
    if effective_photo_id:
        from app.api.v1.me_photo import photo_data_uri

        document = (
            (
                await db.execute(
                    select(Document).where(Document.id == profile.photo_document_id)
                )
            )
            .scalars()
            .first()
        )
        if document is not None:
            photo_uri = photo_data_uri(document)
    location = ", ".join(
        part for part in (basics.get("city") or "", basics.get("country") or "") if part
    )
    return [
        CvContextItem(
            item_id="basics",
            label=user.full_name or user.email,
            detail="Contact header",
            payload={
                "name": user.full_name,
                "headline": basics.get("headline") or "",
                "email": basics.get("email") or user.email,
                "phone": basics.get("phone") or "",
                "location": location,
                "photo": photo_uri,
                "links": [
                    {
                        "kind": link.get("kind") or "other",
                        "url": link.get("url") or "",
                        "label": link.get("label") or link.get("kind") or "link",
                    }
                    for link in basics.get("links") or []
                    if link.get("url")
                ],
            },
            updated_at=profile.updated_at if profile else user.updated_at,
        )
    ]


async def _resolve_summary(db: AsyncSession, user_id: uuid.UUID) -> list[CvContextItem]:
    profile = (
        (await db.execute(select(Profile).where(Profile.user_id == user_id)))
        .scalars()
        .first()
    )
    if profile is None:
        return []
    text = "; ".join(
        str(a.get("label") or "").strip()
        for a in profile.aspirations or []
        if a.get("label")
    )
    notes = "; ".join(
        str(a.get("notes") or "").strip()
        for a in profile.aspirations or []
        if a.get("notes")
    )
    summary = " — ".join(part for part in (text, notes) if part)
    if not summary:
        return []
    return [
        CvContextItem(
            item_id="summary",
            label="Career objective",
            detail="From profile aspirations",
            payload={"summary": summary},
            updated_at=profile.updated_at,
        )
    ]


async def _resolve_experience(
    db: AsyncSession, user_id: uuid.UUID
) -> list[CvContextItem]:
    rows = await db.execute(
        select(ExperienceItem)
        .where(ExperienceItem.user_id == user_id, ExperienceItem.status == "active")
        .options(
            selectinload(ExperienceItem.skills).selectinload(ExperienceSkill.skill),
            selectinload(ExperienceItem.achievements),
        )
        .order_by(ExperienceItem.start.desc(), ExperienceItem.created_at.desc())
    )
    return [
        CvContextItem(
            item_id=str(row.id),
            label=row.title,
            detail=row.org_name,
            payload={
                "title": row.title,
                "org": row.org_name,
                "start": _ym(row.start),
                "end": "" if row.open_ended else _ym(row.end),
                "description": row.description,
                "skills": [
                    link.skill.label for link in row.skills if link.skill is not None
                ],
                "achievements": [
                    {"text": achievement.text} for achievement in row.achievements
                ],
            },
            updated_at=row.updated_at,
        )
        for row in rows.scalars().all()
    ]


async def _resolve_education(
    db: AsyncSession, user_id: uuid.UUID
) -> list[CvContextItem]:
    rows = await db.execute(
        select(EducationItem, Department.name)
        .outerjoin(Department, EducationItem.department_id == Department.id)
        .where(EducationItem.user_id == user_id, EducationItem.status == "active")
        .order_by(
            EducationItem.start.desc().nullslast(), EducationItem.created_at.desc()
        )
    )
    items: list[CvContextItem] = []
    for row, department_name in rows.all():
        institution = row.institution or row.org_name
        org = f"{institution} — {department_name}" if department_name else institution
        items.append(
            CvContextItem(
                item_id=str(row.id),
                label=row.program or row.institution,
                detail=org,
                payload={
                    "title": row.program,
                    "org": org,
                    "department": department_name or "",
                    "level": row.level,
                    "start": _ym(row.start),
                    "end": "" if row.in_progress else _ym(row.end),
                    "description": row.description,
                },
                updated_at=row.updated_at,
            )
        )
    return items


async def _resolve_certifications(
    db: AsyncSession, user_id: uuid.UUID
) -> list[CvContextItem]:
    rows = await db.execute(
        select(Certification)
        .where(Certification.user_id == user_id, Certification.status == "active")
        .order_by(Certification.issued.desc().nullslast())
    )
    return [
        CvContextItem(
            item_id=str(row.id),
            label=row.name,
            detail=row.issuer,
            payload={
                "title": row.name,
                "org": row.issuer,
                "start": _ym(row.issued),
                "end": _ym(row.expires),
                "description": "",
            },
            updated_at=row.updated_at,
        )
        for row in rows.scalars().all()
    ]


async def _resolve_achievements(
    db: AsyncSession, user_id: uuid.UUID
) -> list[CvContextItem]:
    rows = await db.execute(
        select(ProfileAchievement)
        .where(
            ProfileAchievement.user_id == user_id,
            ProfileAchievement.status == "active",
        )
        .order_by(ProfileAchievement.date.desc().nullslast())
    )
    return [
        CvContextItem(
            item_id=str(row.id),
            label=row.title,
            detail=row.issuer,
            payload={
                "title": row.title,
                "issuer": row.issuer,
                "date": _ym(row.date),
                "kind": row.kind,
            },
            updated_at=row.updated_at,
        )
        for row in rows.scalars().all()
    ]


async def _resolve_skills(db: AsyncSession, user_id: uuid.UUID) -> list[CvContextItem]:
    rows = await db.execute(
        select(UserSkill)
        .where(UserSkill.user_id == user_id)
        .options(selectinload(UserSkill.skill))
        .order_by(UserSkill.level.desc(), UserSkill.created_at.asc())
    )
    return [
        CvContextItem(
            item_id=str(row.skill_id),
            label=row.skill.label,
            detail=row.skill.category,
            payload={
                "label": row.skill.label,
                "level": row.level,
                "category": row.skill.category,
            },
            updated_at=row.updated_at,
        )
        for row in rows.scalars().all()
        if row.skill is not None
    ]


async def _resolve_languages(
    db: AsyncSession, user_id: uuid.UUID
) -> list[CvContextItem]:
    profile = (
        (await db.execute(select(Profile).where(Profile.user_id == user_id)))
        .scalars()
        .first()
    )
    if profile is None:
        return []
    items = []
    for language in (profile.academics or {}).get("languages") or []:
        code = str(language.get("code") or "").strip()
        if not code:
            continue
        items.append(
            CvContextItem(
                item_id=code,
                label=code.upper(),
                detail=str(language.get("level") or ""),
                payload={
                    "label": code.upper(),
                    "level": language.get("level") or "",
                },
                updated_at=profile.updated_at,
            )
        )
    return items


async def _resolve_interests(
    db: AsyncSession, user_id: uuid.UUID
) -> list[CvContextItem]:
    rows = await db.execute(
        select(UserInterest)
        .where(UserInterest.user_id == user_id)
        .options(selectinload(UserInterest.tag))
        .order_by(UserInterest.weight.desc(), UserInterest.created_at.asc())
    )
    return [
        CvContextItem(
            item_id=str(row.interest_tag_id),
            label=row.tag.label,
            payload={"label": row.tag.label},
            updated_at=row.updated_at,
        )
        for row in rows.scalars().all()
        if row.tag is not None
    ]


CV_CONTEXT_SOURCES: dict[str, CvContextSourceDef] = {
    definition.key: definition
    for definition in (
        CvContextSourceDef(
            "basics",
            "Contact header",
            "Name, headline, contact, links",
            _resolve_basics,
        ),
        CvContextSourceDef(
            "summary",
            "Objective",
            "Career objective from profile aspirations",
            _resolve_summary,
        ),
        CvContextSourceDef(
            "experience",
            "Experience",
            "Roles, internships, projects, volunteering",
            _resolve_experience,
        ),
        CvContextSourceDef(
            "education",
            "Education",
            "Schools and programs",
            _resolve_education,
        ),
        CvContextSourceDef(
            "certifications",
            "Certifications",
            "Certificates and licenses",
            _resolve_certifications,
        ),
        CvContextSourceDef(
            "achievements",
            "Achievements",
            "Awards, honors, publications",
            _resolve_achievements,
        ),
        CvContextSourceDef(
            "skills",
            "Skills",
            "Claimed skill levels with evidence",
            _resolve_skills,
        ),
        CvContextSourceDef(
            "languages",
            "Languages",
            "Spoken languages",
            _resolve_languages,
        ),
        CvContextSourceDef(
            "interests",
            "Interests",
            "Interest tags",
            _resolve_interests,
        ),
    )
}


def register_context_source(definition: CvContextSourceDef) -> None:
    """Register an additional render source (entry-point extensible later)."""
    if definition.key in CV_CONTEXT_SOURCES:
        raise ValueError(f"Context source already registered: {definition.key}")
    CV_CONTEXT_SOURCES[definition.key] = definition


@dataclass
class CvResolution:
    """Deterministic resolution of a context selection."""

    snapshot: dict
    snapshot_index: dict[str, list[str]]
    items: list[CvContextItem]
    resolved_at: datetime

    def item_refs(self) -> list[dict]:
        """Flat `{source_key, item_id, label, updated_at}` trace list."""
        return [
            {
                "source_key": source_key,
                "item_id": item.item_id,
                "label": item.label,
                "updated_at": item.updated_at.isoformat(),
            }
            for source_key, items in self._by_source().items()
            for item in items
        ]

    def _by_source(self) -> dict[str, list[CvContextItem]]:
        grouped: dict[str, list[CvContextItem]] = {}
        for source_key in CV_CONTEXT_SOURCES:
            key = "summary" if source_key == "summary" else source_key
            refs = self.snapshot_index.get(key) or []
            if not refs:
                continue
            wanted = {ref: item for item in self.items for ref in [item.item_id]}
            grouped[source_key] = [wanted[ref] for ref in refs if ref in wanted]
        return grouped


async def resolve_sources(
    db: AsyncSession, user_id: uuid.UUID
) -> dict[str, list[CvContextItem]]:
    """Resolve every registered source for the caller."""
    return {
        key: list(await definition.resolver(db, user_id))
        for key, definition in CV_CONTEXT_SOURCES.items()
    }


def select_items(
    resolved: dict[str, list[CvContextItem]], selection: CvContextSelection
) -> dict[str, list[CvContextItem]]:
    """Apply the selection per source: all-minus / none-plus / custom.

    Exclusions always win — an excluded id never renders, even when
    included.
    """

    def grouped(refs: list) -> dict[str, set[str]]:
        out: dict[str, set[str]] = {}
        for ref in refs:
            out.setdefault(ref.source_key, set()).add(ref.item_id)
        return out

    include, exclude = grouped(selection.include), grouped(selection.exclude)
    selected: dict[str, list[CvContextItem]] = {}
    for key, items in resolved.items():
        inc, exc = include.get(key, set()), exclude.get(key, set())
        if selection.mode == "all":
            chosen = [item for item in items if item.item_id not in exc]
        elif selection.mode == "none":
            chosen = [item for item in items if item.item_id in inc]
        else:
            chosen = [
                item
                for item in items
                if item.item_id in inc and item.item_id not in exc
            ]
        if chosen:
            selected[key] = chosen
    return selected


async def resolve(
    db: AsyncSession,
    user_id: uuid.UUID,
    selection: CvContextSelection | None = None,
    photo_document_id: uuid.UUID | None = None,
) -> CvResolution:
    """Resolve the caller's context selection into snapshot + trace map."""
    selection = selection or CvContextSelection()
    resolved = await resolve_sources(db, user_id)
    resolved["basics"] = await _resolve_basics(db, user_id, photo_document_id)
    selected = select_items(resolved, selection)
    snapshot: dict[str, Any] = {}
    snapshot_index: dict[str, list[str]] = {}
    items: list[CvContextItem] = []
    for source_key in CV_CONTEXT_SOURCES:
        chosen = selected.get(source_key) or []
        if not chosen:
            continue
        key = "summary" if source_key == "summary" else source_key
        snapshot_index[key] = [item.item_id for item in chosen]
        items.extend(chosen)
        if key in SCALAR_KEYS:
            snapshot[key] = dict(chosen[0].payload)
        else:
            snapshot[key] = [dict(item.payload) for item in chosen]
    return CvResolution(
        snapshot=snapshot,
        snapshot_index=snapshot_index,
        items=items,
        resolved_at=datetime.now(timezone.utc),
    )


def apply_overrides(
    snapshot: dict, snapshot_index: dict[str, list[str]], overrides: dict
) -> dict:
    """Merge editor field patches keyed `"{source_key}:{item_id}"`.

    Positions in `snapshot_index` map 1:1 onto snapshot rows, so a patch
    targets exactly the resolved item it names. Scalars match on the
    singleton item id.
    """
    if not overrides:
        return snapshot
    patched = {
        key: (dict(rows) if key in SCALAR_KEYS else list(rows))
        for key, rows in snapshot.items()
    }
    for ref, patches in overrides.items():
        source_key, _, item_id = str(ref).partition(":")
        key = "summary" if source_key == "summary" else source_key
        if key in SCALAR_KEYS:
            if snapshot_index.get(key, [None])[0] == item_id:
                patched[key] = {**(patched.get(key) or {}), **patches}
            continue
        rows = [dict(row) for row in patched.get(key) or []]
        for position, ref_id in enumerate(snapshot_index.get(key) or []):
            if ref_id == item_id and position < len(rows):
                rows[position] = {**rows[position], **patches}
        patched[key] = rows
    return patched
