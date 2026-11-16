"""JSON Resume interop (plan 212 S2.4).

Export the structured profile in the community JSON Resume shape, and
import it through a review report: mapped fields are listed, every
unmapped key or value is reported, and nothing is written until the
caller explicitly applies the proposal. No schema package is imported at
runtime — the small set of fields we understand is validated by hand.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import ValidationError
from app.models.experience_model import ExperienceItem
from app.models.profile_entities_model import EducationItem
from app.models.user_model import User, UserSkill
from app.schemas.profile import BasicSection, ProfileSectionUpdate
from app.services.profile.experience_service import ExperienceService
from app.services.profile.profile_entities_service import ProfileEntitiesService
from app.services.profile.profile_service import ProfileService

SCHEMA_URL = "https://raw.githubusercontent.com/jsonresume/resume-schema/v1.0.0/schema.json"
MAX_IMPORT_BYTES = 1_000_000
MAX_WORK_ITEMS = 100
MAX_EDUCATION_ITEMS = 100
MAX_HIGHLIGHTS = 30
MAX_SKILLS = 200
_MAPPED_TOP = {"$schema", "basics", "work", "education", "skills"}
_WORK_KEYS = {
    "name",
    "position",
    "url",
    "startDate",
    "endDate",
    "summary",
    "highlights",
    "location",
}
_EDUCATION_KEYS = {
    "institution",
    "url",
    "area",
    "studyType",
    "startDate",
    "endDate",
    "score",
    "courses",
}
_BASICS_KEYS = {
    "name",
    "label",
    "image",
    "email",
    "phone",
    "url",
    "summary",
    "location",
    "profiles",
}


def _level_from_study_type(raw: Any) -> tuple[str, bool]:
    """Map the JSON Resume studyType vocabulary onto our education enum.

    Returns ``(level, recognised)`` so an unknown "Diploma"/"Licence"
    never silently masquerades as high school.
    """
    token = str(raw or "").strip().lower()
    if not token:
        return "high_school", False
    if any(word in token for word in ("phd", "doctor", "dphil")):
        return "doctorate", True
    if any(word in token for word in ("master", "msc", "mba", "ma ", "m.a")):
        return "master", True
    if any(word in token for word in ("bachelor", "bsc", "b.s", "ba ", "b.a", "undergrad")):
        return "bachelor", True
    if any(word in token for word in ("vocational", "apprentice", "trade")):
        return "vocational", True
    if "middle" in token:
        return "middle_school", True
    if any(
        phrase in token for phrase in ("high school", "highschool", "secondary", "school diploma")
    ):
        return "high_school", True
    return "high_school", False


def _iso(value: date | None) -> str | None:
    return value.isoformat() if value else None


def _date(value: Any) -> date | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    for pattern in ("%Y-%m-%d", "%Y-%m", "%Y"):
        try:
            from datetime import datetime

            parsed = datetime.strptime(raw[: len(pattern.replace("%Y", "0000"))], pattern)
            return parsed.date()
        except ValueError:
            continue
    return None


def _as_list(value: Any) -> list:
    return list(value) if isinstance(value, list) else []


def _normalise_key(value: str) -> str:
    return " ".join(str(value or "").lower().split())


def _links(basics: dict) -> list[dict]:
    links = basics.get("links") or []
    return [
        {
            "network": str(link.get("kind") or "other").title(),
            "username": "",
            "url": str(link.get("url") or ""),
        }
        for link in links
        if isinstance(link, dict) and link.get("url")
    ]


async def export_resume(db: AsyncSession, user_id: uuid.UUID) -> dict:
    profile = await ProfileService(db).get(user_id)
    user = await db.get(User, user_id)
    basics = dict(profile.basics or {})
    location = {
        "address": "",
        "city": basics.get("city") or "",
        "region": "",
        "postalCode": "",
        "countryCode": basics.get("country") or "",
    }
    resume: dict[str, Any] = {
        "$schema": SCHEMA_URL,
        "basics": {
            "name": (user.full_name if user else "") or basics.get("full_name") or "",
            "label": basics.get("headline") or "",
            "email": basics.get("email") or (user.email if user else "") or "",
            "phone": basics.get("phone") or "",
            "url": next(
                (
                    str(link.get("url"))
                    for link in basics.get("links") or []
                    if isinstance(link, dict) and link.get("url")
                ),
                "",
            ),
            "summary": "",
            "location": location,
            "profiles": _links(basics),
        },
        "work": [],
        "education": [],
        "skills": [],
    }

    work_rows = (
        (
            await db.execute(
                select(ExperienceItem)
                .options(selectinload(ExperienceItem.achievements))
                .where(
                    ExperienceItem.user_id == user_id,
                    ExperienceItem.status == "active",
                )
                .order_by(ExperienceItem.start.desc().nulls_last(), ExperienceItem.title)
            )
        )
        .scalars()
        .all()
    )
    for item in work_rows:
        resume["work"].append(
            {
                "name": item.org_name,
                "position": item.title,
                "url": (item.links or [{}])[0].get("url", "")
                if isinstance((item.links or [{}])[0], dict)
                else "",
                "startDate": _iso(item.start),
                "endDate": _iso(item.end),
                "summary": item.description,
                "highlights": [row.text for row in item.achievements if row.text],
                "location": "",
            }
        )

    education_rows = (
        (
            await db.execute(
                select(EducationItem)
                .where(
                    EducationItem.user_id == user_id,
                    EducationItem.status == "active",
                )
                .order_by(EducationItem.start.desc().nulls_last(), EducationItem.institution)
            )
        )
        .scalars()
        .all()
    )
    for education in education_rows:
        resume["education"].append(
            {
                "institution": education.institution,
                "url": "",
                "area": education.program,
                "studyType": education.level.replace("_", " ").title(),
                "startDate": _iso(education.start),
                "endDate": _iso(education.end),
                "score": str(education.grade_value) if education.grade_value is not None else "",
                "courses": list(education.focus_subjects or []),
            }
        )

    skills = (
        (
            await db.execute(
                select(UserSkill)
                .options(selectinload(UserSkill.skill))
                .where(UserSkill.user_id == user_id, UserSkill.hidden.is_(False))
                .order_by(UserSkill.level.desc())
            )
        )
        .scalars()
        .all()
    )
    resume["skills"] = [
        {"name": row.skill.label if row.skill is not None else "", "level": "", "keywords": []}
        for row in skills
        if row.skill is not None
    ]
    return resume


def _basics_proposal(raw: dict) -> tuple[dict, list[str]]:
    warnings: list[str] = []
    proposal: dict[str, Any] = {}
    mapping = {
        "name": ("full_name", 160),
        "label": ("headline", 120),
        "email": ("email", 200),
        "phone": ("phone", 40),
    }
    for source, (target, limit) in mapping.items():
        value = str(raw.get(source) or "").strip()
        if value:
            proposal[target] = value[:limit]
    location = raw.get("location") or {}
    if isinstance(location, dict):
        if str(location.get("city") or "").strip():
            proposal["city"] = str(location["city"]).strip()[:80]
        if str(location.get("countryCode") or "").strip():
            proposal["country"] = str(location["countryCode"]).strip()[:80]
    links = []
    for entry in raw.get("profiles") or []:
        if not isinstance(entry, dict) or not entry.get("url"):
            continue
        url = str(entry["url"]).strip()
        if not url.startswith(("http://", "https://")):
            warnings.append(f"profile link dropped (not http(s)): {entry}")
            continue
        links.append(
            {
                "kind": "linkedin" if "linkedin" in url.lower() else "other",
                "url": url[:500],
                "label": str(entry.get("network") or "")[:120],
            }
        )
    if links:
        proposal["links"] = links[:8]
    if raw.get("summary"):
        warnings.append("basics.summary has no profile field and was kept out of the write")
    return proposal, warnings


async def import_resume(
    db: AsyncSession, user_id: uuid.UUID, payload: dict, *, apply: bool = False
) -> dict:
    if not isinstance(payload, dict):
        raise ValidationError("JSON Resume payload must be an object")
    dropped = sorted(key for key in payload if key not in _MAPPED_TOP)
    mapped: dict[str, Any] = {"basics": {}, "work": [], "education": [], "skills": []}
    warnings: list[str] = []

    basics_conflicts: list[dict] = []
    profile = await ProfileService(db).get(user_id)
    current_basics = dict(profile.basics or {})
    raw_basics = payload.get("basics")
    if isinstance(raw_basics, dict):
        mapped["basics"], basics_warnings = _basics_proposal(raw_basics)
        warnings.extend(basics_warnings)
        dropped.extend(f"basics.{key}" for key in raw_basics if key not in _BASICS_KEYS)
        for key in ("url", "image"):
            if raw_basics.get(key):
                dropped.append(f"basics.{key}")
        if isinstance(raw_basics.get("location"), dict):
            dropped.extend(
                f"basics.location.{key}"
                for key, value in raw_basics["location"].items()
                if key not in {"city", "countryCode"} and value not in (None, "")
            )
        for index, profile_entry in enumerate(_as_list(raw_basics.get("profiles"))):
            if isinstance(profile_entry, dict):
                dropped.extend(
                    f"basics.profiles[{index}].{key}"
                    for key, value in profile_entry.items()
                    if key not in {"url", "network"} and value not in (None, "")
                )
        for key, value in mapped["basics"].items():
            current = current_basics.get(key)
            if key == "links":
                if current and current != value:
                    basics_conflicts.append(
                        {"field": "links", "current": current, "incoming": value}
                    )
                continue
            if current not in (None, "", []) and current != value:
                basics_conflicts.append({"field": key, "current": current, "incoming": value})

    work_payload = payload.get("work") or []
    if not isinstance(work_payload, list):
        warnings.append("work was not a list and was skipped")
        work_payload = []
    if len(work_payload) > MAX_WORK_ITEMS:
        warnings.append(f"work capped at {MAX_WORK_ITEMS} entries")
        work_payload = work_payload[:MAX_WORK_ITEMS]
    for index, entry in enumerate(work_payload):
        if not isinstance(entry, dict):
            warnings.append(f"work[{index}] dropped (not an object)")
            continue
        dropped.extend(f"work[{index}].{key}" for key in entry if key not in _WORK_KEYS)
        if entry.get("location"):
            dropped.append(f"work[{index}].location")
        if entry.get("highlights") and not isinstance(entry.get("highlights"), list):
            warnings.append(f"work[{index}].highlights was not a list and was skipped")
        title = str(entry.get("position") or "").strip()
        org = str(entry.get("name") or "").strip()
        if not title:
            warnings.append(f"work[{index}] dropped (no position)")
            continue
        start = _date(entry.get("startDate"))
        end = _date(entry.get("endDate"))
        if start is None:
            warnings.append(f"work[{index}] kept as a proposal but needs a start date")
        mapped["work"].append(
            {
                "kind": "job",
                "title": title[:160],
                "org_name": org[:200],
                "start": _iso(start),
                "end": _iso(end),
                "open_ended": end is None,
                "description": str(entry.get("summary") or "")[:20000],
                "achievements": [
                    {"text": str(text)[:500]}
                    for text in _as_list(entry.get("highlights"))[:MAX_HIGHLIGHTS]
                    if str(text).strip()
                ],
                "links": [{"url": str(entry["url"])[:500]}]
                if entry.get("url") and str(entry["url"]).startswith(("http://", "https://"))
                else [],
            }
        )

    education_payload = _as_list(payload.get("education"))
    if payload.get("education") and not isinstance(payload.get("education"), list):
        warnings.append("education was not a list and was skipped")
    if len(education_payload) > MAX_EDUCATION_ITEMS:
        warnings.append(f"education capped at {MAX_EDUCATION_ITEMS} entries")
        education_payload = education_payload[:MAX_EDUCATION_ITEMS]
    for index, entry in enumerate(education_payload):
        if not isinstance(entry, dict):
            warnings.append(f"education[{index}] dropped (not an object)")
            continue
        dropped.extend(f"education[{index}].{key}" for key in entry if key not in _EDUCATION_KEYS)
        if entry.get("url"):
            dropped.append(f"education[{index}].url")
        if entry.get("courses") and not isinstance(entry.get("courses"), list):
            warnings.append(f"education[{index}].courses was not a list and was skipped")
        level, recognised = _level_from_study_type(entry.get("studyType"))
        if not recognised:
            warnings.append(
                f"education[{index}].studyType not mapped; stored as high school "
                "— edit it on the education page"
            )
        institution = str(entry.get("institution") or "").strip()
        if not institution:
            warnings.append(f"education[{index}] dropped (no institution)")
            continue
        start = _date(entry.get("startDate"))
        end = _date(entry.get("endDate"))
        if entry.get("score"):
            warnings.append(
                f"education[{index}].score kept out (no scale; enter it on the education page)"
            )
        mapped["education"].append(
            {
                "institution": institution[:200],
                "level": level,
                "program": " · ".join(
                    part
                    for part in (
                        str(entry.get("area") or "").strip(),
                        str(entry.get("studyType") or "").strip(),
                    )
                    if part
                )[:200],
                "start": _iso(start),
                "end": _iso(end),
                "in_progress": end is None,
                "focus_subjects": [
                    str(course)[:120] for course in _as_list(entry.get("courses"))[:12]
                ],
            }
        )

    if payload.get("skills"):
        warnings.append("skills are reported only; import them through the skills page")
        mapped["skills"] = [
            str(entry.get("name"))[:120]
            for entry in payload["skills"][:MAX_SKILLS]
            if isinstance(entry, dict) and entry.get("name")
        ]
        if len(payload["skills"]) > MAX_SKILLS:
            warnings.append(f"skills capped at {MAX_SKILLS} entries")

    result: dict[str, Any] = {
        "mapped": mapped,
        "dropped": dropped,
        "warnings": warnings,
        "basics_conflicts": basics_conflicts,
        "applied": False,
        "created": {"work": 0, "education": 0},
    }
    if not apply:
        return result

    profile_service = ProfileService(db)
    if mapped["basics"]:
        merged = {**dict(profile.basics or {}), **mapped["basics"]}
        try:
            basics = BasicSection(**merged)
        except ValueError as exc:
            warnings.append(f"basics not written: {exc}")
        else:
            await profile_service.update(user_id, ProfileSectionUpdate(basics=basics))
            result["applied"] = True

    experience = ExperienceService(db)
    existing = (
        (await db.execute(select(ExperienceItem).where(ExperienceItem.user_id == user_id)))
        .scalars()
        .all()
    )
    existing_keys = {
        (_normalise_key(row.title), _normalise_key(row.org_name), _iso(row.start))
        for row in existing
    }
    for item in mapped["work"]:
        if item.get("start") is None:
            continue
        work_key = (
            _normalise_key(str(item["title"])),
            _normalise_key(str(item["org_name"])),
            item["start"],
        )
        if work_key in existing_keys:
            warnings.append(f"work already exists and was skipped: {item['title']}")
            continue
        try:
            await experience.create_item(user_id, item, commit=False)
        except ValidationError as exc:
            warnings.append(f"work not written: {exc}")
        else:
            existing_keys.add(work_key)
            result["created"]["work"] += 1
            result["applied"] = True

    entities = ProfileEntitiesService(db)
    existing_education = (
        (await db.execute(select(EducationItem).where(EducationItem.user_id == user_id)))
        .scalars()
        .all()
    )
    education_keys = {
        (_normalise_key(row.institution), _iso(row.start)) for row in existing_education
    }
    for item in mapped["education"]:
        education_key = (
            _normalise_key(str(item["institution"])),
            item["start"],
        )
        if education_key in education_keys:
            warnings.append(f"education already exists and was skipped: {item['institution']}")
            continue
        try:
            await entities.create_education(
                user_id,
                __import__(
                    "app.schemas.profile_entities", fromlist=["EducationItemIn"]
                ).EducationItemIn(
                    institution=item["institution"],
                    level=item["level"],
                    program=item["program"],
                    start=_date(item["start"]),
                    end=_date(item["end"]),
                    in_progress=item["in_progress"],
                    focus_subjects=item["focus_subjects"],
                ),
                commit=False,
            )
        except ValidationError as exc:
            warnings.append(f"education not written: {exc}")
        else:
            education_keys.add(education_key)
            result["created"]["education"] += 1
            result["applied"] = True
    if result["created"]["work"] or result["created"]["education"]:
        await db.commit()
    result["warnings"] = warnings
    return result
