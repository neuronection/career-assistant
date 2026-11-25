"""Catalog pack identity and lifecycle (plan 224 S2).

Adds the stored `seed_key` identity to the six catalog tables (nullable,
unique where present, both dialect predicates), a `status` on job families,
`PathStatus.RETIRED` (enum only — `career_paths.status` has no CHECK), and the
`delete` action in the import-run ledger. Existing seeded rows are adopted by
backfilling only known keys: jobs/relations/paths carry `source='seed'`;
families/skills/interests have no source discriminator, so the migration
embeds their known key lists (admin-created rows stay null and are never
pack-owned).

Downgrade maps retired paths back to published, drops the columns/indexes and
restores the previous action vocabulary.

Revision ID: 0021
Revises: 0020
Create Date: 2026-11-26
"""

from __future__ import annotations

import re
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = (
    "job_families",
    "jobs",
    "job_relations",
    "skills",
    "interest_tags",
    "career_paths",
)

FAMILY_KEYS = (
    "technology",
    "technology-software",
    "technology-data",
    "technology-ops",
    "healthcare",
    "healthcare-clinical",
    "healthcare-therapy",
    "healthcare-pharma",
    "education",
    "engineering",
    "engineering-civil",
    "engineering-mechanical",
    "business",
    "business-creative",
    "creative",
    "public-safety",
    "science",
    "agriculture",
    "hospitality",
)

SKILL_KEYS = (
    "programming",
    "data-analysis",
    "mathematics",
    "lab-techniques",
    "electronics",
    "engineering-design",
    "mechanical-repair",
    "network-admin",
    "writing",
    "public-speaking",
    "foreign-languages",
    "negotiation",
    "teaching",
    "empathy",
    "teamwork",
    "leadership",
    "conflict-resolution",
    "customer-service",
    "visual-design",
    "storytelling",
    "music-performance",
    "video-editing",
    "cooking",
    "critical-thinking",
    "problem-solving",
    "attention-to-detail",
    "memory-accuracy",
    "organization",
    "physical-stamina",
    "dexterity",
    "driving",
    "first-aid",
)

INTEREST_KEYS = (
    "science-physics",
    "science-chemistry",
    "science-biology",
    "science-earth",
    "nature-animals",
    "nature-plants",
    "science-space",
    "technology-software",
    "technology-hardware",
    "technology-robots",
    "technology-ai",
    "technology-networks",
    "technology-games",
    "technology-data",
    "people-teaching",
    "people-health",
    "people-helping",
    "people-law-justice",
    "people-public-safety",
    "people-animals-care",
    "business-entrepreneurship",
    "business-marketing",
    "business-sales",
    "business-finance",
    "business-management",
    "business-logistics",
    "arts-visual",
    "arts-design",
    "arts-music",
    "arts-writing",
    "arts-performing",
    "arts-photo-video",
    "hands-building",
    "hands-machines",
    "hands-electricity",
    "hands-cooking",
    "hands-crafts",
    "hands-driving",
    "society-history",
    "society-languages",
    "society-politics",
    "society-environment",
    "society-media",
    "sports-fitness",
    "sports-competition",
    "sports-outdoors",
)

ACTION_VALUES_OLD = (
    "create",
    "update",
    "noop",
    "conflict",
    "skip",
    "override",
    "retire",
)
ACTION_VALUES_NEW = (*ACTION_VALUES_OLD, "delete")

_SLUG = re.compile(r"[^a-z0-9]+")


def _slug(title: str, *, max_length: int) -> str:
    value = _SLUG.sub("-", title.lower()).strip("-")[:max_length]
    return value or "path"


def _split_key(key: str) -> tuple[str, str]:
    match = re.match(r"^([a-z][a-z0-9-]{1,63}):([a-z0-9][a-z0-9._/-]{0,119})$", key)
    if not match:
        raise ValueError(f"invalid seed_key: {key!r}")
    return match.group(1), match.group(2)


def _action_check(values: Sequence[str]) -> str:
    quoted = ", ".join(f"'{value}'" for value in values)
    return f"action IN ({quoted})"


def _index_name(table: str) -> str:
    return f"uq_{table}_seed_key"


def _backfill_families(bind: sa.Connection) -> None:
    for key in FAMILY_KEYS:
        bind.execute(
            sa.text(
                "UPDATE job_families SET seed_key = :seed_key WHERE key = :key AND seed_key IS NULL"
            ),
            {"seed_key": f"job-family:{key}", "key": key},
        )


def _backfill_taxonomy(bind: sa.Connection) -> None:
    for table, prefix, keys in (
        ("skills", "skill", SKILL_KEYS),
        ("interest_tags", "interest", INTEREST_KEYS),
    ):
        for key in keys:
            bind.execute(
                sa.text(
                    f"UPDATE {table} SET seed_key = :seed_key WHERE key = :key AND seed_key IS NULL"
                ),
                {"seed_key": f"{prefix}:{key}", "key": key},
            )


def _backfill_jobs(bind: sa.Connection) -> None:
    bind.execute(
        sa.text(
            "UPDATE jobs SET seed_key = 'job-type:' || code "
            "WHERE source = 'seed' AND seed_key IS NULL"
        )
    )


def _backfill_relations(bind: sa.Connection) -> None:
    rows = bind.execute(
        sa.text(
            "SELECT r.id, f.code AS from_code, t.code AS to_code, r.relation_type "
            "FROM job_relations r "
            "JOIN jobs f ON f.id = r.from_job_id "
            "JOIN jobs t ON t.id = r.to_job_id "
            "WHERE r.source = 'seed' AND r.seed_key IS NULL"
        )
    ).all()
    for row in rows:
        seed_key = (
            f"job-relation:{row.from_code}/{row.to_code}/{str(row.relation_type).replace('_', '-')}"
        )
        bind.execute(
            sa.text("UPDATE job_relations SET seed_key = :seed_key WHERE id = :id"),
            {"seed_key": seed_key, "id": row.id},
        )


def _backfill_paths(bind: sa.Connection) -> None:
    rows = bind.execute(
        sa.text(
            "SELECT p.id, j.code AS job_code, p.title "
            "FROM career_paths p JOIN jobs j ON j.id = p.job_id "
            "WHERE p.source = 'seed' AND p.seed_key IS NULL"
        )
    ).all()
    seen: set[str] = set()
    for row in rows:
        body = f"{row.job_code}/{_slug(row.title, max_length=120 - len(row.job_code) - 1)}"
        seed_key = f"career-path:{body}"
        _prefix, bare = _split_key(seed_key)
        if bare in seen:
            raise ValueError(f"duplicate career-path key: {seed_key}")
        seen.add(bare)
        bind.execute(
            sa.text("UPDATE career_paths SET seed_key = :seed_key WHERE id = :id"),
            {"seed_key": seed_key, "id": row.id},
        )


def upgrade() -> None:
    bind = op.get_bind()

    for table in TABLES:
        op.add_column(table, sa.Column("seed_key", sa.String(200), nullable=True))
        op.create_index(
            _index_name(table),
            table,
            ["seed_key"],
            unique=True,
            postgresql_where=sa.text("seed_key IS NOT NULL"),
            sqlite_where=sa.text("seed_key IS NOT NULL"),
        )

    with op.batch_alter_table("job_families") as batch:
        batch.add_column(
            sa.Column("status", sa.String(20), nullable=False, server_default="published")
        )
        batch.create_check_constraint("status_allowed", "status IN ('published', 'retired')")

    with op.batch_alter_table("seed_import_run_items", recreate="always") as batch:
        batch.drop_constraint("action_allowed", type_="check")
        batch.create_check_constraint("action_allowed", _action_check(ACTION_VALUES_NEW))

    _backfill_families(bind)
    _backfill_taxonomy(bind)
    _backfill_jobs(bind)
    _backfill_relations(bind)
    _backfill_paths(bind)


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("UPDATE career_paths SET status = 'published' WHERE status = 'retired'"))

    with op.batch_alter_table("seed_import_run_items", recreate="always") as batch:
        batch.drop_constraint("action_allowed", type_="check")
        batch.create_check_constraint("action_allowed", _action_check(ACTION_VALUES_OLD))

    with op.batch_alter_table("job_families") as batch:
        batch.drop_constraint("status_allowed", type_="check")
        batch.drop_column("status")

    for table in TABLES:
        op.drop_index(_index_name(table), table_name=table)
        op.drop_column(table, "seed_key")
