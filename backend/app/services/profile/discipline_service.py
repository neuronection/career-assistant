"""Discipline -> job-family suggestions (plan 212 S3.3).

A deterministic, explainable keyword map over the user's programme and
focus subjects. A match expands one level in the catalog family tree (the
matched family, its parent, and the sibling families under that parent),
bounded and de-duplicated. This is a suggestion/filter helper, never a hard
exclusion. Rationale codes are structured; the app translates them.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.job_model import JobFamily
from app.models.profile_entities_model import EducationItem

DISCIPLINE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "technology-software": (
        "computer science",
        "software engineering",
        "software",
        "informatics",
        "informatik",
        "πληροφορική",
        "programming",
        "web development",
        "application development",
    ),
    "technology-data": (
        "data science",
        "data analytics",
        "data analysis",
        "datenanalyse",
        "analytics",
        "statistics",
        "machine learning",
        "artificial intelligence",
        "mathematics",
        "mathematik",
        "μαθηματικά",
    ),
    "technology-ops": (
        "cybersecurity",
        "cyber security",
        "information security",
        "information systems",
        "information technology",
        "network engineering",
        "cloud computing",
    ),
    "healthcare-clinical": (
        "medicine",
        "nursing",
        "νοσηλευτική",
        "dentistry",
        "clinical",
        "midwifery",
        "medical",
        "medizin",
        "ιατρική",
    ),
    "healthcare-therapy": (
        "physiotherapy",
        "occupational therapy",
        "rehabilitation",
        "psychotherapy",
        "speech therapy",
        "psychology",
        "ψυχολογία",
    ),
    "healthcare-pharma": (
        "pharmacy",
        "pharmacology",
        "pharmaceutical",
        "biomedical",
        "laboratory science",
        "pharmazie",
        "φαρμακευτική",
    ),
    "education": (
        "education",
        "teaching",
        "pedagogy",
        "teacher training",
        "pädagogik",
        "εκπαίδευση",
    ),
    "engineering-civil": (
        "civil engineering",
        "construction",
        "architecture",
        "structural engineering",
        "bauingenieurwesen",
    ),
    "engineering-mechanical": (
        "mechanical engineering",
        "electrical engineering",
        "mechatronics",
        "aerospace",
        "manufacturing engineering",
        "maschinenbau",
        "μηχανολογία",
    ),
    "business": (
        "business",
        "business administration",
        "finance",
        "accounting",
        "economics",
        "betriebswirtschaft",
        "οικονομικά",
    ),
    "business-creative": (
        "marketing",
        "media",
        "communications",
        "advertising",
        "journalism",
        "public relations",
        "marketing management",
    ),
    "creative": ("design", "fine art", "arts", "music", "film", "fashion", "graphic design"),
    "public-safety": (
        "law",
        "criminology",
        "public safety",
        "political science",
        "police",
        "legal studies",
        "jura",
        "rechtswissenschaft",
        "νομική",
    ),
    "science": (
        "biology",
        "biological science",
        "chemistry",
        "physics",
        "environmental science",
        "geology",
        "biochemistry",
        "biologie",
        "chemie",
        "βιολογία",
        "χημεία",
        "φυσική",
    ),
    "agriculture": ("agriculture", "agronomy", "animal science", "veterinary", "horticulture"),
    "hospitality": ("hospitality", "tourism", "hotel management", "culinary", "events management"),
}

MAX_MATCHES = 6
ENGINEERING_GENERIC_TERMS = ("engineering", "ingenieurwesen", "μηχανική")
ENGINEERING_SPECIFIC_TERMS = (
    "software engineering",
    "civil engineering",
    "mechanical engineering",
    "electrical engineering",
    "structural engineering",
    "manufacturing engineering",
    "mechatronics",
    "aerospace",
    "construction",
    "architecture",
)
MAX_TERMS = 6
MAX_EXPANDED = 8
_GENERIC_DEGREE_NAMES = (
    "bachelor of arts",
    "bachelor of science",
    "master of arts",
    "master of science",
)


def _normalise(value: str) -> str:
    return " ".join(re.sub(r"[_\W]+", " ", (value or "").lower()).split())


def _keyword_present(keyword: str, corpus: str) -> bool:
    phrase = _normalise(keyword)
    if not phrase:
        return False
    return bool(
        re.search(
            r"(?<!\w)" + re.escape(phrase) + r"(?:s|es)?(?!\w)",
            corpus,
        )
    )


@dataclass(frozen=True)
class DisciplineMatch:
    family_key: str
    family_title: str
    matched_terms: tuple[str, ...]
    reason: Literal["matched", "parent", "family_expansion"]
    depth: int


async def degree_matches(db: AsyncSession, user_id: uuid.UUID) -> list[DisciplineMatch]:
    rows = (
        (
            await db.execute(
                select(EducationItem)
                .where(
                    EducationItem.user_id == user_id,
                    EducationItem.status == "active",
                )
                .order_by(EducationItem.start.desc().nulls_last())
            )
        )
        .scalars()
        .all()
    )
    corpus = _normalise(
        " ".join(
            part
            for row in rows
            for part in [row.program or "", *(row.focus_subjects or [])]
            if part
        )
    )
    for generic in _GENERIC_DEGREE_NAMES:
        corpus = corpus.replace(generic, " ")
    if not corpus.strip():
        return []

    scored: list[tuple[int, str, tuple[str, ...]]] = []
    for family_key, keywords in DISCIPLINE_KEYWORDS.items():
        matched = tuple(keyword for keyword in keywords if _keyword_present(keyword, corpus))
        if matched:
            scored.append((len(matched), family_key, matched[:MAX_TERMS]))
    scored.sort(key=lambda item: (-item[0], item[1]))
    matched_keys = {key for _, key, _ in scored}
    if (
        "engineering-civil" not in matched_keys
        and "engineering-mechanical" not in matched_keys
        and any(_keyword_present(term, corpus) for term in ENGINEERING_GENERIC_TERMS)
        and not any(_keyword_present(term, corpus) for term in ENGINEERING_SPECIFIC_TERMS)
    ):
        scored.append((1, "engineering", ("engineering",)))
    scored.sort(key=lambda item: (-item[0], item[1]))
    if not scored:
        return []

    primary_rows = (
        (
            await db.execute(
                select(JobFamily)
                .options(selectinload(JobFamily.parent))
                .where(JobFamily.key.in_({key for _, key, _ in scored}))
            )
        )
        .scalars()
        .all()
    )
    parent_ids = {row.parent_id for row in primary_rows if row.parent_id is not None}
    root_ids = {row.id for row in primary_rows if row.parent_id is None}
    related_parent_ids = parent_ids | root_ids
    related_rows = (
        (
            await db.execute(
                select(JobFamily)
                .options(selectinload(JobFamily.parent))
                .where(JobFamily.parent_id.in_(related_parent_ids))
                .order_by(JobFamily.key)
            )
        )
        .scalars()
        .all()
        if related_parent_ids
        else []
    )
    all_rows = {row.key: row for row in [*primary_rows, *related_rows]}
    for row in primary_rows:
        if row.parent is not None:
            all_rows[row.parent.key] = row.parent

    matches: list[DisciplineMatch] = []
    seen: set[str] = set()
    direct: list[tuple[JobFamily, tuple[str, ...]]] = []
    for _score, family_key, terms in scored[:MAX_MATCHES]:
        family = all_rows.get(family_key)
        if family is None or family_key in seen:
            continue
        direct.append((family, terms))
        matches.append(
            DisciplineMatch(
                family_key=family_key,
                family_title=family.label,
                matched_terms=terms,
                reason="matched",
                depth=0,
            )
        )
        seen.add(family_key)

    for family, terms in direct:
        parent = family.parent
        if parent is not None and parent.key not in seen:
            matches.append(
                DisciplineMatch(
                    family_key=parent.key,
                    family_title=parent.label,
                    matched_terms=terms,
                    reason="parent",
                    depth=1,
                )
            )
            seen.add(parent.key)
        container_id = parent.id if parent is not None else family.id
        for related in related_rows:
            if related.parent_id != container_id or related.key in seen:
                continue
            matches.append(
                DisciplineMatch(
                    family_key=related.key,
                    family_title=related.label,
                    matched_terms=terms,
                    reason="family_expansion",
                    depth=1,
                )
            )
            seen.add(related.key)
            if len(matches) >= MAX_EXPANDED:
                break
        if len(matches) >= MAX_EXPANDED:
            break
    return matches[:MAX_EXPANDED]
