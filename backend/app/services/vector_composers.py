"""Versioned, pure composers for the family vector store (plan 50 §5, P1c).

A composer turns one source entity into the embeddable surface of a
*document*: named views (``summary``, ``requirements``,
``responsibilities``, ``skills``, ``body``) and, for long text, deterministic
chunks of one. Nothing here touches the network, the database, an LLM or the
clock — same input, same output, so a content hash (and the embed spend
behind it) tracks real content changes only.

Every record carries a ``text_ref`` pointer (``{table, id, field}`` plus
``text_ref_schema_version``) instead of a copy of the source text; the
retrieval tables never store raw text. Chunk ``char_start``/``char_end``
index into the composed view text, so a reader can rehydrate the exact
window under the caller's ACL.

``COMPOSER_VERSION`` is part of the space identity (``space_key``): changing
the projection of an existing view requires bumping it in the same change,
which creates a ``building`` space and runs the cutover instead of silently
mixing two projections in one space.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from app.storage.vector_contract import content_hash

COMPOSER_VERSION = "1"
CHUNKER_VERSION = "1"
TEXT_REF_SCHEMA_VERSION = 1

BODY_CHUNK_CHARS = 1600
BODY_CHUNK_OVERLAP_CHARS = 240
SUMMARY_EXCERPT_CHARS = 600

_PRIORITY_RANK = {"must_have": 0, "nice_to_have": 1}
_IMPORTANCE_RANK = {"core": 0, "important": 1, "bonus": 2}


@dataclass(frozen=True)
class TextChunk:
    """One deterministic character window of a long view."""

    text: str
    char_start: int
    char_end: int


@dataclass(frozen=True)
class ComposedRecord:
    """One record a composer wants embedded (before any vector exists)."""

    view: str
    text: str
    chunk_index: int = 0
    char_start: int | None = None
    char_end: int | None = None
    text_ref: Mapping[str, str] | None = None
    text_ref_schema_version: int | None = None

    @property
    def content_hash(self) -> str:
        return content_hash(self.text)

    @property
    def key(self) -> tuple[str, int]:
        return (self.view, self.chunk_index)


@dataclass(frozen=True)
class ComposedDocument:
    """The composed surface of one source entity.

    ``views`` holds the whole text per view (what a reader rehydrates);
    ``records`` is the authoritative embeddable set — whole views for the
    short views and chunks for ``body``.
    """

    kind: str
    source_id: str
    views: Mapping[str, str]
    records: tuple[ComposedRecord, ...]
    composer_version: str = COMPOSER_VERSION

    @property
    def source_hash(self) -> str:
        """SHA-256 over every composed record hash (the document's version)."""
        digest = hashlib.sha256()
        for record in sorted(self.records, key=lambda item: (item.view, item.chunk_index)):
            digest.update(f"{record.view}:{record.chunk_index}:{record.content_hash}\n".encode())
        return digest.hexdigest()

    @property
    def is_empty(self) -> bool:
        return not self.records


def chunk_text(
    text: str,
    *,
    size: int = BODY_CHUNK_CHARS,
    overlap: int = BODY_CHUNK_OVERLAP_CHARS,
) -> list[TextChunk]:
    """Split ``text`` into deterministic overlapping character windows.

    Windows are ``size`` characters with ``overlap`` characters of context,
    trimmed of surrounding whitespace; ``char_start``/``char_end`` point at
    the trimmed window inside the input text. Whitespace-only windows are
    dropped, so an empty view composes no records.
    """
    if size <= 0:
        raise ValueError("chunk size must be positive")
    if overlap < 0 or overlap >= size:
        raise ValueError("chunk overlap must be >= 0 and < size")
    if not (text or "").strip():
        return []
    step = size - overlap
    chunks: list[TextChunk] = []
    start = 0
    total = len(text)
    while start < total:
        end = min(start + size, total)
        window = text[start:end]
        stripped = window.strip()
        if stripped:
            leading = len(window) - len(window.lstrip())
            trailing = len(window.rstrip())
            chunks.append(
                TextChunk(
                    text=stripped,
                    char_start=start + leading,
                    char_end=start + trailing,
                )
            )
        if end >= total:
            break
        start += step
    return chunks


def _ref(
    table: str, source_id: str | None, field: str
) -> tuple[Mapping[str, str] | None, int | None]:
    if not source_id:
        return None, None
    return (
        {"table": table, "id": str(source_id), "field": field},
        TEXT_REF_SCHEMA_VERSION,
    )


def _clean_lines(lines: Iterable[str | None]) -> str:
    return "\n".join(line for line in (str(value or "").strip() for value in lines) if line)


def _posting_skills(extract: Mapping) -> list[dict]:
    rows: list[dict] = []
    for row in extract.get("skills") or []:
        if not isinstance(row, Mapping):
            continue
        label = str(row.get("raw_label") or row.get("skill_key") or "").strip()
        if not label:
            continue
        rows.append(
            {
                "label": label,
                "priority": str(row.get("priority") or ""),
                "level": row.get("required_level"),
            }
        )
    return sorted(
        rows,
        key=lambda row: (
            _PRIORITY_RANK.get(row["priority"], len(_PRIORITY_RANK)),
            -int(row["level"] or 0),
            row["label"],
        ),
    )


def _skill_line(skill: Mapping) -> str:
    parts = [f"skill: {skill['label']}"]
    if skill["priority"]:
        parts.append(skill["priority"])
    if skill["level"] is not None:
        parts.append(f"level {skill['level']}")
    return " ".join(parts)


def _posting_body(posting) -> str:
    raw = getattr(posting, "raw", None) or {}
    parts: list[str] = []
    for key in ("description", "text", "note"):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    return "\n".join(parts)


def _posting_responsibilities(extract: Mapping) -> str:
    lines: list[str] = []
    for row in extract.get("responsibilities") or []:
        if not isinstance(row, Mapping):
            continue
        text = str(row.get("text") or "").strip()
        if not text:
            continue
        suffix = f" ({row['time_pct']}%)" if row.get("time_pct") else ""
        optional = " (optional)" if row.get("optional") else ""
        lines.append(f"responsibility: {text}{suffix}{optional}")
    return "\n".join(lines)


def _posting_prerequisites(extract: Mapping) -> list[str]:
    labels: list[str] = []
    for row in extract.get("prerequisites") or []:
        if isinstance(row, Mapping):
            label = str(row.get("label") or "").strip()
        else:
            label = str(row or "").strip()
        if label:
            labels.append(label)
    return sorted(labels)


def compose_posting_views(posting) -> ComposedDocument:
    """Compose a job posting's views: summary, requirements,
    responsibilities, skills and the chunked body.

    ``summary`` is the title, org and a short excerpt of the raw text;
    ``requirements`` the must-have skills (label, priority, level) plus the
    stated non-skill prerequisites; ``responsibilities`` the extracted
    duties with their time shares; ``skills`` the resolved skill lines; and
    ``body`` the full raw text, chunked deterministically.
    """
    title = str(getattr(posting, "title", "") or "").strip()
    org = str(getattr(posting, "org", "") or "").strip()
    source_id = getattr(posting, "id", None)
    extract = getattr(posting, "extract", None) or {}
    body = _posting_body(posting)
    skills = _posting_skills(extract)

    summary = _clean_lines([title, org, body[:SUMMARY_EXCERPT_CHARS] if body else None])
    requirements = _clean_lines(
        [_skill_line(skill) for skill in skills]
        + [f"prerequisite: {label}" for label in _posting_prerequisites(extract)]
    )
    responsibilities = _posting_responsibilities(extract)
    skills_text = _clean_lines([_skill_line(skill) for skill in skills])

    views = {
        "summary": summary,
        "requirements": requirements,
        "responsibilities": responsibilities,
        "skills": skills_text,
        "body": body,
    }
    records: list[ComposedRecord] = []
    ref_fields = {
        "summary": "title",
        "requirements": "extract.skills",
        "responsibilities": "extract.responsibilities",
        "skills": "extract.skills",
    }
    for view in ("summary", "requirements", "responsibilities", "skills"):
        text = views[view]
        if not text:
            continue
        ref, version = _ref("job_postings", source_id, ref_fields[view])
        records.append(
            ComposedRecord(
                view=view,
                text=text,
                text_ref=ref,
                text_ref_schema_version=version,
            )
        )
    body_ref, body_version = _ref("job_postings", source_id, "raw.description")
    for index, chunk in enumerate(chunk_text(body)):
        records.append(
            ComposedRecord(
                view="body",
                text=chunk.text,
                chunk_index=index,
                char_start=chunk.char_start,
                char_end=chunk.char_end,
                text_ref=body_ref,
                text_ref_schema_version=body_version,
            )
        )
    return ComposedDocument(
        kind="posting",
        source_id=str(source_id or ""),
        views=views,
        records=tuple(records),
    )


def _job_skill_rows(job) -> list[dict]:
    """The catalog job's skill links as normalized, deterministically ordered rows.

    ``skills`` (the explicit, already-loaded projection) wins; otherwise the
    relationship is read. Callers load it eagerly — a lazy load inside an
    async session would be a ``MissingGreenlet``, which is why the composer
    takes the projection as an option.
    """
    rows: list[dict] = []
    for link in getattr(job, "skill_links", None) or []:
        skill = getattr(link, "skill", None)
        label = str(getattr(skill, "label", None) or getattr(link, "skill_id", "") or "").strip()
        if not label:
            continue
        rows.append(
            {
                "label": label,
                "key": str(getattr(skill, "key", "") or ""),
                "importance": str(getattr(link, "importance", "") or ""),
                "level": getattr(link, "required_level", None),
            }
        )
    return rows


def _job_responsibilities(job) -> str:
    """The curated duties, when a job carries them (optional attributes field).

    Catalog jobs ship no responsibilities today; a posting's extracted
    duties still meet the job's ``summary``/``body`` in the matcher, and the
    view stays empty rather than inventing one from unrelated attributes.
    """
    attributes = getattr(job, "attributes", None) or {}
    lines: list[str] = []
    for key in ("responsibilities", "duties"):
        for row in attributes.get(key) or []:
            if isinstance(row, Mapping):
                text = str(row.get("text") or row.get("title") or "").strip()
                detail = str(row.get("detail") or "").strip()
                if text and detail:
                    text = f"{text}: {detail}"
            else:
                text = str(row or "").strip()
            if text:
                lines.append(f"responsibility: {text}")
        if lines:
            break
    return "\n".join(lines)


def compose_job_views(
    job,
    *,
    family_label: str | None = None,
    skills: Sequence[Mapping] | None = None,
) -> ComposedDocument:
    """Compose a **catalog job's** views for long-text job↔posting matching.

    The same closed view vocabulary as a posting, so the two sides compare
    view to view (plan 50 §7.1): ``summary`` (title, family, short
    description excerpt), ``requirements`` (skill label + importance +
    level), ``responsibilities`` (the optional curated duties), ``skills``
    (skill label + level) and the chunked ``body`` (the full short
    description). ``family_label``/``skills`` are the caller's already-loaded
    projections — a composer never triggers IO.
    """
    title = str(getattr(job, "title", "") or "").strip()
    source_id = getattr(job, "id", None)
    family = family_label
    if family is None:
        loaded_family = getattr(job, "family", None)
        family = str(getattr(loaded_family, "label", None) or "").strip() or None
    body = str(getattr(job, "short_description", "") or "").strip()
    rows = list(skills) if skills is not None else _job_skill_rows(job)
    ordered = sorted(
        rows,
        key=lambda row: (
            _IMPORTANCE_RANK.get(str(row.get("importance") or ""), len(_IMPORTANCE_RANK)),
            -int(row.get("level") or 0),
            str(row.get("label") or ""),
        ),
    )

    def requirement_line(skill: Mapping) -> str:
        parts = [f"skill: {skill.get('label')}"]
        if skill.get("importance"):
            parts.append(str(skill["importance"]))
        if skill.get("level") is not None:
            parts.append(f"level {skill['level']}")
        return " ".join(parts)

    summary = _clean_lines([title, family, body[:SUMMARY_EXCERPT_CHARS] if body else None])
    requirements = _clean_lines([requirement_line(skill) for skill in ordered])
    responsibilities = _job_responsibilities(job)
    skills_text = _clean_lines(
        [
            " ".join(
                [
                    f"skill: {skill.get('label')}",
                    f"level {skill['level']}" if skill.get("level") is not None else "",
                ]
            ).strip()
            for skill in ordered
        ]
    )

    views = {
        "summary": summary,
        "requirements": requirements,
        "responsibilities": responsibilities,
        "skills": skills_text,
        "body": body,
    }
    ref_fields = {
        "summary": "title+family+short_description",
        "requirements": "job_skills",
        "responsibilities": "attributes.responsibilities",
        "skills": "job_skills",
    }
    records: list[ComposedRecord] = []
    for view in ("summary", "requirements", "responsibilities", "skills"):
        text = views[view]
        if not text:
            continue
        ref, version = _ref("jobs", source_id, ref_fields[view])
        records.append(
            ComposedRecord(
                view=view,
                text=text,
                text_ref=ref,
                text_ref_schema_version=version,
            )
        )
    body_ref, body_version = _ref("jobs", source_id, "short_description")
    for index, chunk in enumerate(chunk_text(body)):
        records.append(
            ComposedRecord(
                view="body",
                text=chunk.text,
                chunk_index=index,
                char_start=chunk.char_start,
                char_end=chunk.char_end,
                text_ref=body_ref,
                text_ref_schema_version=body_version,
            )
        )
    return ComposedDocument(
        kind="job",
        source_id=str(source_id or ""),
        views=views,
        records=tuple(records),
    )


def compose_profile_views(
    *,
    user_id: str | None,
    profiles: Sequence[Mapping],
    interests: Sequence[str],
    skills: Sequence[Mapping],
    experience_titles: Sequence[str],
) -> ComposedDocument:
    """Compose a user's profile: interests/location, skills and background.

    Mirrors the user-scoped surface of the legacy ``compose_profile_text``
    (every profile of the user merges deterministically) but splits it into
    views: ``summary`` (interests + location), ``skills`` (label + level)
    and ``body`` (experience titles + education).
    """
    interest_lines = [
        f"interest: {str(value).strip()}" for value in interests if str(value).strip()
    ]
    location_lines: list[str] = []
    education_lines: list[str] = []
    for profile in profiles:
        location = " ".join(
            str(profile[key]) for key in ("city", "country") if profile.get(key)
        ).strip()
        if location:
            location_lines.append(f"location: {location}")
        education = str(profile.get("education") or "").strip()
        if education:
            education_lines.append(f"education: {education}")
    skill_lines = [
        f"skill: {str(skill.get('label') or '').strip()} level {skill.get('level')}"
        for skill in skills
        if str(skill.get("label") or "").strip()
    ]
    experience_lines = [
        f"experience: {str(title).strip()}" for title in experience_titles if str(title).strip()
    ]

    views = {
        "summary": _clean_lines([*interest_lines, *location_lines]),
        "skills": _clean_lines(skill_lines),
        "body": _clean_lines([*experience_lines, *education_lines]),
    }
    ref_fields = {
        "summary": "interests+profile_basics",
        "skills": "user_skills",
        "body": "experience+education",
    }
    records: list[ComposedRecord] = []
    for view in ("summary", "skills", "body"):
        text = views[view]
        if not text:
            continue
        ref, version = _ref("users", user_id, ref_fields[view])
        records.append(
            ComposedRecord(
                view=view,
                text=text,
                text_ref=ref,
                text_ref_schema_version=version,
            )
        )
    return ComposedDocument(
        kind="profile",
        source_id=str(user_id or ""),
        views=views,
        records=tuple(records),
    )


def compose_skill_text(skill) -> str:
    """The embedded surface of a skill: key + label + sorted aliases."""
    aliases = sorted(
        str(alias).strip()
        for alias in (getattr(skill, "aliases", None) or [])
        if str(alias).strip()
    )
    return _clean_lines([getattr(skill, "key", None), getattr(skill, "label", None), *aliases])


def compose_skill_views(skill) -> ComposedDocument:
    """Compose a skill as one short ``summary`` vector (plan 50 §7.1)."""
    text = compose_skill_text(skill)
    views = {"summary": text}
    records: tuple[ComposedRecord, ...] = ()
    if text:
        ref, version = _ref("skills", getattr(skill, "id", None), "key+label+aliases")
        records = (
            ComposedRecord(
                view="summary",
                text=text,
                text_ref=ref,
                text_ref_schema_version=version,
            ),
        )
    return ComposedDocument(
        kind="skill",
        source_id=str(getattr(skill, "id", "") or ""),
        views=views,
        records=records,
    )


__all__ = [
    "BODY_CHUNK_CHARS",
    "BODY_CHUNK_OVERLAP_CHARS",
    "CHUNKER_VERSION",
    "COMPOSER_VERSION",
    "SUMMARY_EXCERPT_CHARS",
    "TEXT_REF_SCHEMA_VERSION",
    "ComposedDocument",
    "ComposedRecord",
    "TextChunk",
    "chunk_text",
    "compose_job_views",
    "compose_posting_views",
    "compose_profile_views",
    "compose_skill_text",
    "compose_skill_views",
]
