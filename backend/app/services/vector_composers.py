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
    "compose_posting_views",
    "compose_profile_views",
    "compose_skill_text",
    "compose_skill_views",
]
