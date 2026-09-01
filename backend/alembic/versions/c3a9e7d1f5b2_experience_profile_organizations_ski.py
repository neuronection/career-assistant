"""experience profile + organizations + skill_evidence (Phase 40)

New tables: organizations, experience_items, experience_skills,
experience_achievements, skill_evidence. `job_postings.org_id` becomes a
nullable FK. Backfills: distinct posting org labels → organizations rows
(proposed, plan-39 machinery merges later); profiles' legacy JSONB
experience lists → experience_items (+ part_time → job per plan 40) with
their skill_keys as primary role rows.

Revision ID: c3a9e7d1f5b2
Revises: b7d2f4a6c8e0
Create Date: 2026-09-02 00:00:00.000000
"""

import re
import uuid
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.models.base import StructuredJSON

# revision identifiers, used by Alembic.
revision: str = "c3a9e7d1f5b2"
down_revision: Union[str, None] = "b7d2f4a6c8e0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "").strip().lower()).strip("-")
    return slug[:110] or f"org-{uuid.uuid4().hex[:8]}"


def _create_tables() -> None:
    op.create_table(
        "organizations",
        sa.Column("key", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("domain", sa.String(length=200), nullable=True),
        sa.Column("aliases", StructuredJSON, nullable=False,
                  server_default=sa.text("'[]'")),
        sa.Column("status", sa.String(length=20), nullable=False,
                  server_default="proposed"),
        sa.Column("provenance", StructuredJSON, nullable=False,
                  server_default=sa.text("'{}'")),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organizations")),
        sa.CheckConstraint(
            "status IN ('proposed', 'active', 'deprecated')",
            name=op.f("ck_organizations_status_allowed"),
        ),
    )
    op.create_index(op.f("ix_organizations_key"), "organizations", ["key"],
                    unique=True)

    op.create_table(
        "experience_items",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False,
                  server_default="project"),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=True),
        sa.Column("org_name", sa.String(length=200), nullable=False,
                  server_default=""),
        sa.Column("start", sa.Date(), nullable=False),
        sa.Column("end", sa.Date(), nullable=True),
        sa.Column("open_ended", sa.Boolean(), nullable=False,
                  server_default=sa.false()),
        sa.Column("hours_per_week", sa.Integer(), nullable=True),
        sa.Column("onsite_policy", sa.String(length=20), nullable=True),
        sa.Column("description", sa.Text(), nullable=False,
                  server_default=""),
        sa.Column("links", StructuredJSON, nullable=False,
                  server_default=sa.text("'[]'")),
        sa.Column("source", sa.String(length=20), nullable=False,
                  server_default="self_report"),
        sa.Column("status", sa.String(length=20), nullable=False,
                  server_default="active"),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_experience_items")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"],
            name=op.f("fk_experience_items_user_id_users"), ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"],
            name=op.f("fk_experience_items_org_id_organizations"),
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "kind IN ('job', 'project', 'internship', 'volunteer', 'freelance')",
            name=op.f("ck_experience_items_kind_allowed"),
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'active')",
            name=op.f("ck_experience_items_status_allowed"),
        ),
    )
    op.create_index(op.f("ix_experience_items_user_id"), "experience_items",
                    ["user_id"], unique=False)
    op.create_index("ix_experience_items_user_status", "experience_items",
                    ["user_id", "status"], unique=False)

    op.create_table(
        "experience_skills",
        sa.Column("experience_id", sa.Uuid(), nullable=False),
        sa.Column("skill_id", sa.Uuid(), nullable=False),
        sa.Column("role_in_item", sa.String(length=20), nullable=False,
                  server_default="primary"),
        sa.Column("level_claim", sa.Integer(), nullable=True),
        sa.Column("last_used", sa.Date(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_experience_skills")),
        sa.ForeignKeyConstraint(
            ["experience_id"], ["experience_items.id"],
            name=op.f("fk_experience_skills_experience_id_experience_items"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["skill_id"], ["skills.id"],
            name=op.f("fk_experience_skills_skill_id_skills"),
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("experience_id", "skill_id",
                            name=op.f("uq_experience_skills_pair")),
        sa.CheckConstraint(
            "role_in_item IN ('primary', 'secondary', 'exposure')",
            name=op.f("ck_experience_skills_role_allowed"),
        ),
        sa.CheckConstraint(
            "level_claim IS NULL OR (level_claim >= 1 AND level_claim <= 10)",
            name=op.f("ck_experience_skills_level_claim_range"),
        ),
    )
    op.create_index(op.f("ix_experience_skills_skill_id"), "experience_skills",
                    ["skill_id"], unique=False)

    op.create_table(
        "experience_achievements",
        sa.Column("experience_id", sa.Uuid(), nullable=False),
        sa.Column("text", sa.String(length=500), nullable=False),
        sa.Column("metric", StructuredJSON, nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_experience_achievements")),
        sa.ForeignKeyConstraint(
            ["experience_id"], ["experience_items.id"],
            name=op.f("fk_experience_achievements_experience_id_experience_i"),
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        op.f("ix_experience_achievements_experience_id"),
        "experience_achievements", ["experience_id"], unique=False,
    )

    op.create_table(
        "skill_evidence",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("skill_id", sa.Uuid(), nullable=False),
        sa.Column("assessment_run_id", sa.Uuid(), nullable=True),
        sa.Column("experience_item_id", sa.Uuid(), nullable=True),
        sa.Column("cv_document_id", sa.Uuid(), nullable=True),
        sa.Column("note", sa.String(length=500), nullable=False,
                  server_default=""),
        sa.Column("level_value", sa.Numeric(4, 2), nullable=True),
        sa.Column("confidence", sa.Numeric(3, 2), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_skill_evidence")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"],
            name=op.f("fk_skill_evidence_user_id_users"), ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["skill_id"], ["skills.id"],
            name=op.f("fk_skill_evidence_skill_id_skills"), ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["assessment_run_id"], ["assessment_runs.id"],
            name=op.f("fk_skill_evidence_assessment_run_id_assessment_runs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["experience_item_id"], ["experience_items.id"],
            name=op.f("fk_skill_evidence_experience_item_id_experience_ite"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["cv_document_id"], ["documents.id"],
            name=op.f("fk_skill_evidence_cv_document_id_documents"),
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "((CASE WHEN assessment_run_id IS NOT NULL THEN 1 ELSE 0 END) + "
            "(CASE WHEN experience_item_id IS NOT NULL THEN 1 ELSE 0 END) + "
            "(CASE WHEN cv_document_id IS NOT NULL THEN 1 ELSE 0 END)) = 1",
            name=op.f("ck_skill_evidence_one_source_set"),
        ),
    )
    op.create_index(op.f("ix_skill_evidence_user_id"), "skill_evidence",
                    ["user_id"], unique=False)
    op.create_index("ix_skill_evidence_user_skill", "skill_evidence",
                    ["user_id", "skill_id"], unique=False)


def _backfill_orgs(connection) -> None:
    """Distinct posting org labels → proposed organizations + FK link."""
    rows = connection.execute(
        sa.text(
            "SELECT DISTINCT org FROM job_postings "
            "WHERE org IS NOT NULL AND org <> ''"
        )
    ).fetchall()
    seen: dict[str, str] = {}
    for (name,) in rows:
        key = _slug(name)
        org_id = seen.get(key)
        if org_id is None:
            org_id = str(uuid.uuid4())
            seen[key] = org_id
            connection.execute(
                sa.text(
                    "INSERT INTO organizations (key, name, status, provenance, id) "
                    "VALUES (:key, :name, 'proposed', :provenance, :id)"
                ),
                {
                    "key": key,
                    "name": name[:200],
                    "provenance": '{"source": "posting_backfill"}',
                    "id": org_id,
                },
            )
        connection.execute(
            sa.text(
                "UPDATE job_postings SET org_id = :oid WHERE org = :name "
                "AND org_id IS NULL"
            ),
            {"oid": org_id, "name": name},
        )


def _backfill_experience(connection) -> None:
    """Legacy JSONB experience lists → experience_items (+skills)."""
    skill_rows = connection.execute(
        sa.text("SELECT id, key FROM skills")
    ).fetchall()
    skills_by_key = {key: str(skill_id) for skill_id, key in skill_rows}
    profiles = connection.execute(
        sa.text("SELECT id, experience FROM profiles")
    ).fetchall()
    for user_id, experience in profiles:
        if not experience:
            continue
        for item in experience:
            if not isinstance(item, dict) or not item.get("title"):
                continue
            kind = str(item.get("kind") or "project")
            if kind == "part_time":
                kind = "job"
            if kind not in ("job", "project", "internship", "volunteer", "freelance"):
                kind = "project"
            start_year = item.get("start_year")
            if not start_year:
                continue
            end_year = item.get("end_year")
            item_id = str(uuid.uuid4())
            connection.execute(
                sa.text(
                    "INSERT INTO experience_items "
                    "(user_id, kind, title, org_name, start, end, open_ended, "
                    " hours_per_week, description, source, status, id) "
                    "VALUES (:uid, :kind, :title, :org, :start, :end, :open, "
                    " :hours, :descr, 'self_report', 'active', :id)"
                ),
                {
                    "uid": str(user_id),
                    "kind": kind,
                    "title": str(item.get("title"))[:160],
                    "org": str(item.get("org") or "")[:200],
                    "start": f"{int(start_year)}-01-01",
                    "end": f"{int(end_year)}-12-31" if end_year else None,
                    "open": end_year is None,
                    "hours": item.get("hours_per_week"),
                    "descr": str(item.get("description") or ""),
                    "id": item_id,
                },
            )
            for skill_key in (item.get("skill_keys") or [])[:15]:
                skill_id = skills_by_key.get(str(skill_key))
                if skill_id is None:
                    continue
                connection.execute(
                    sa.text(
                        "INSERT INTO experience_skills "
                        "(experience_id, skill_id, role_in_item, id) "
                        "VALUES (:eid, :sid, 'primary', :id) "
                        "ON CONFLICT DO NOTHING"
                    ),
                    {"eid": item_id, "sid": skill_id, "id": str(uuid.uuid4())},
                )


def upgrade() -> None:
    _create_tables()
    op.add_column(
        "job_postings",
        sa.Column("org_id", sa.Uuid(), nullable=True),
    )
    op.create_index(op.f("ix_job_postings_org_id"), "job_postings", ["org_id"],
                    unique=False)
    connection = op.get_bind()
    _backfill_orgs(connection)
    _backfill_experience(connection)


def downgrade() -> None:
    op.drop_index(op.f("ix_job_postings_org_id"), table_name="job_postings")
    op.drop_column("job_postings", "org_id")
    op.drop_table("skill_evidence")
    op.drop_table("experience_achievements")
    op.drop_table("experience_skills")
    op.drop_table("experience_items")
    op.drop_table("organizations")
