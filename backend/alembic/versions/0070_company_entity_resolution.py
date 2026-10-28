"""Plan 135 — company entity resolution.

Aliases graduate from `organizations.aliases` JSONB to the
`organization_aliases` table (provenance + state — the "edit rules" base),
match exclusions become rows (global not-a-company + per-pair never-link),
the gray-band queue (`organization_match_pairs`) and merge suggestions get
tables, and the matcher gains indexed exact-lookup keys (`name_key`,
`initials_key`) plus per-posting link provenance (`job_postings.org_match`).

The JSONB aliases column folds and dies (no-BC); existing aliases land as
`source='legacy'` rows. The quality denylist seeds as global exclusion rows
so it is admin-editable from day one. Downgrade reverses: the JSONB column
is rebuilt from the alias rows.
"""

import json
import re
import uuid

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

_JSON = JSONB().with_variant(sa.JSON(), "sqlite")

revision = "0070"
down_revision = "0069"
branch_labels = None
depends_on = None

_TOKEN = re.compile(r"[a-z0-9]+")

# Mirrors app.services.catalog.company_names (kept inline: a migration must
# stay executable even when app code moves on).
_LEGAL_SUFFIXES = frozenset(
    {
        "gmbh",
        "mbh",
        "ag",
        "kg",
        "ohg",
        "ltd",
        "limited",
        "llc",
        "inc",
        "incorporated",
        "corp",
        "corporation",
        "co",
        "company",
        "sa",
        "sas",
        "srl",
        "spa",
        "bv",
        "nv",
        "plc",
        "oy",
        "ab",
        "as",
        "pty",
    }
)

# Seeded denylist: generic non-employer labels (reason 'quality'). Rows, not
# code — the rules surface edits them from day one.
_QUALITY_DENYLIST = (
    "confidential",
    "confidential company",
    "company confidential",
    "undisclosed",
    "not disclosed",
    "company not disclosed",
    "employer not disclosed",
    "staffing",
    "staffing agency",
    "recruiting",
    "recruiting agency",
    "recruitment agency",
    "a leading company",
    "leading company",
    "your company",
    "my company",
    "the company",
    "various",
    "multiple companies",
    "unknown",
    "n a",
)


def _tokens(name: str) -> list[str]:
    return [t for t in _TOKEN.findall(name.lower()) if t not in _LEGAL_SUFFIXES]


def _name_key(name: str) -> str:
    return " ".join(_tokens(name))[:200]


def _initials_key(name: str) -> str:
    name_tokens = _tokens(name)
    if len(name_tokens) >= 2:
        return "".join(t[0] for t in name_tokens)[:200]
    if name_tokens and len(name_tokens[0]) <= 4:
        return name_tokens[0]
    return ""


def _alias_key(alias: str) -> str:
    return _name_key(alias)


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    ]


def _json_list(value: object) -> list:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return []
    return value if isinstance(value, list) else []


def upgrade() -> None:
    bind = op.get_bind()

    op.create_table(
        "organization_aliases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("alias", sa.String(length=200), nullable=False),
        sa.Column("alias_key", sa.String(length=200), nullable=False),
        sa.Column("source", sa.String(length=12), nullable=False, server_default="learned"),
        sa.Column("state", sa.String(length=12), nullable=False, server_default="active"),
        sa.Column("created_by", sa.String(length=120), nullable=False, server_default="system"),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("org_id", "alias_key"),
        sa.CheckConstraint(
            "source IN ('manual', 'learned', 'llm', 'url', 'merge', 'legacy')",
            name="source_allowed",
        ),
        sa.CheckConstraint("state IN ('active', 'excluded')", name="state_allowed"),
    )
    op.create_index("ix_organization_aliases_alias_key", "organization_aliases", ["alias_key"])
    op.create_index("ix_organization_aliases_org_id", "organization_aliases", ["org_id"])

    op.create_table(
        "organization_match_exclusions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column("label_key", sa.String(length=200), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=True),
        sa.Column("reason", sa.String(length=300), nullable=False, server_default=""),
        sa.Column("source", sa.String(length=12), nullable=False, server_default="manual"),
        sa.Column("created_by", sa.String(length=120), nullable=False, server_default="system"),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("label_key", "org_id"),
        sa.CheckConstraint("source IN ('manual', 'llm', 'dismiss', 'seed')", name="source_allowed"),
    )
    op.create_index(
        "ix_organization_match_exclusions_label_key",
        "organization_match_exclusions",
        ["label_key"],
    )
    op.create_index(
        "ux_organization_match_exclusions_global",
        "organization_match_exclusions",
        ["label_key"],
        unique=True,
        postgresql_where=sa.text("org_id IS NULL"),
        sqlite_where=sa.text("org_id IS NULL"),
    )

    op.create_table(
        "organization_match_pairs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column("label_key", sa.String(length=200), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("evidence", _JSON, nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False, server_default="pending"),
        sa.Column("verdict", sa.String(length=12), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("canonical_name", sa.String(length=200), nullable=True),
        sa.Column("decided_by", sa.String(length=120), nullable=False, server_default=""),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("label_key", "org_id"),
        sa.CheckConstraint("status IN ('pending', 'resolved', 'dropped')", name="status_allowed"),
        sa.CheckConstraint(
            "verdict IS NULL OR verdict IN ('same', 'different', 'uncertain')",
            name="verdict_allowed",
        ),
    )
    op.create_index(
        "ix_organization_match_pairs_label_key", "organization_match_pairs", ["label_key"]
    )
    op.create_index("ix_organization_match_pairs_org_id", "organization_match_pairs", ["org_id"])
    op.create_index("ix_organization_match_pairs_status", "organization_match_pairs", ["status"])

    op.create_table(
        "organization_merge_suggestions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("org_a", sa.Uuid(), nullable=False),
        sa.Column("org_b", sa.Uuid(), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column("label_key", sa.String(length=200), nullable=False),
        sa.Column("score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("reason", sa.String(length=300), nullable=False, server_default=""),
        sa.Column("evidence", _JSON, nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False, server_default="open"),
        sa.Column("decided_by", sa.String(length=120), nullable=False, server_default=""),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["org_a"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["org_b"], ["organizations.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("org_a", "org_b", "label_key"),
        sa.CheckConstraint("status IN ('open', 'accepted', 'dismissed')", name="status_allowed"),
        sa.CheckConstraint("org_a <> org_b", name="distinct_orgs"),
    )
    op.create_index(
        "ix_organization_merge_suggestions_label_key",
        "organization_merge_suggestions",
        ["label_key"],
    )
    op.create_index(
        "ix_organization_merge_suggestions_org_a", "organization_merge_suggestions", ["org_a"]
    )
    op.create_index(
        "ix_organization_merge_suggestions_org_b", "organization_merge_suggestions", ["org_b"]
    )

    op.add_column(
        "organizations",
        sa.Column("name_key", sa.String(length=200), nullable=False, server_default=""),
    )
    op.add_column(
        "organizations",
        sa.Column("initials_key", sa.String(length=200), nullable=False, server_default=""),
    )
    op.create_index("ix_organizations_name_key", "organizations", ["name_key"])
    op.create_index("ix_organizations_initials_key", "organizations", ["initials_key"])

    op.add_column("job_postings", sa.Column("org_match", _JSON, nullable=True))

    orgs = bind.execute(sa.text("SELECT id, name FROM organizations")).fetchall()
    for org_id, name in orgs:
        bind.execute(
            sa.text("UPDATE organizations SET name_key = :nk, initials_key = :ik WHERE id = :oid"),
            {"nk": _name_key(name or ""), "ik": _initials_key(name or ""), "oid": str(org_id)},
        )

    for org_id, aliases in bind.execute(
        sa.text("SELECT id, aliases FROM organizations")
    ).fetchall():
        for alias in _json_list(aliases):
            alias = str(alias).strip()[:200]
            if not alias:
                continue
            bind.execute(
                sa.text(
                    "INSERT INTO organization_aliases "
                    "(id, org_id, alias, alias_key, source, state, created_by) "
                    "VALUES (:id, :oid, :alias, :akey, 'legacy', 'active', 'system')"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "oid": str(org_id),
                    "alias": alias,
                    "akey": _alias_key(alias),
                },
            )

    with op.batch_alter_table("organizations") as batch:
        batch.drop_column("aliases")

    seen_keys: set[str] = set()
    for label in _QUALITY_DENYLIST:
        label_key = _alias_key(label)
        if label_key in seen_keys:
            continue
        seen_keys.add(label_key)
        bind.execute(
            sa.text(
                "INSERT INTO organization_match_exclusions "
                "(id, label, label_key, org_id, reason, source, created_by) "
                "VALUES (:id, :label, :lkey, NULL, 'quality', 'seed', 'system')"
            ),
            {"id": str(uuid.uuid4()), "label": label, "lkey": label_key},
        )


def downgrade() -> None:
    bind = op.get_bind()

    with op.batch_alter_table("organizations") as batch:
        batch.add_column(sa.Column("aliases", _JSON, nullable=False, server_default="[]"))
    for (org_id,) in bind.execute(sa.text("SELECT id FROM organizations")).fetchall():
        rows = bind.execute(
            sa.text(
                "SELECT alias FROM organization_aliases "
                "WHERE org_id = :oid AND state = 'active' ORDER BY created_at"
            ),
            {"oid": str(org_id)},
        ).fetchall()
        aliases = json.dumps([row[0] for row in rows])
        if bind.dialect.name == "postgresql":
            bind.execute(
                sa.text("UPDATE organizations SET aliases = CAST(:a AS jsonb) WHERE id = :oid"),
                {"a": aliases, "oid": str(org_id)},
            )
        else:
            bind.execute(
                sa.text("UPDATE organizations SET aliases = :a WHERE id = :oid"),
                {"a": aliases, "oid": str(org_id)},
            )

    op.drop_column("job_postings", "org_match")
    op.drop_index("ix_organizations_initials_key", table_name="organizations")
    op.drop_index("ix_organizations_name_key", table_name="organizations")
    with op.batch_alter_table("organizations") as batch:
        batch.drop_column("initials_key")
        batch.drop_column("name_key")

    op.drop_index(
        "ix_organization_merge_suggestions_org_b", table_name="organization_merge_suggestions"
    )
    op.drop_index(
        "ix_organization_merge_suggestions_org_a", table_name="organization_merge_suggestions"
    )
    op.drop_index(
        "ix_organization_merge_suggestions_label_key",
        table_name="organization_merge_suggestions",
    )
    op.drop_table("organization_merge_suggestions")

    op.drop_index("ix_organization_match_pairs_status", table_name="organization_match_pairs")
    op.drop_index("ix_organization_match_pairs_org_id", table_name="organization_match_pairs")
    op.drop_index("ix_organization_match_pairs_label_key", table_name="organization_match_pairs")
    op.drop_table("organization_match_pairs")

    op.drop_index(
        "ux_organization_match_exclusions_global", table_name="organization_match_exclusions"
    )
    op.drop_index(
        "ix_organization_match_exclusions_label_key", table_name="organization_match_exclusions"
    )
    op.drop_table("organization_match_exclusions")

    op.drop_index("ix_organization_aliases_org_id", table_name="organization_aliases")
    op.drop_index("ix_organization_aliases_alias_key", table_name="organization_aliases")
    op.drop_table("organization_aliases")
