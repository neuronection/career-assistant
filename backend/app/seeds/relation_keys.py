"""Key-safe encoding for job-relation types (plan 224 S1).

`seed_key` bodies may not contain ``_`` (the parser and the vendored contract
allow ``[a-z0-9._/-]`` only), while the relation vocabulary uses snake_case
(``similar_to``, ``specialises_into``, …). One codec maps between the two so
the backfill, the pack generator, fixtures, parity and `replaces` all speak
the same key.
"""

from __future__ import annotations

from app.models.enums.catalog import RelationType


def relation_type_slug(value: str) -> str:
    """`similar_to` -> `similar-to` (the key-body spelling)."""
    normalized = str(value)
    allowed = {member.value for member in RelationType}
    if normalized not in allowed:
        raise ValueError(f"unknown relation type: {normalized!r}")
    return normalized.replace("_", "-")


def relation_type_from_slug(slug: str) -> str:
    """`similar-to` -> `similar_to` (the enum value)."""
    for member in RelationType:
        if member.value.replace("_", "-") == slug:
            return member.value
    raise ValueError(f"unknown relation type slug: {slug!r}")


def relation_seed_key(from_code: str, to_code: str, relation_type: str) -> str:
    """`job-relation:<from>/<to>/<type-slug>` (colon-free body)."""
    return f"job-relation:{from_code}/{to_code}/{relation_type_slug(relation_type)}"
