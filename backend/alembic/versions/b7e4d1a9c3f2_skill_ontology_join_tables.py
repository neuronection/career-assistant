"""skill ontology + join tables (Phase 21)

Revision ID: b7e4d1a9c3f2
Revises: f5b21e8c9a30
Create Date: 2026-08-31 00:00:00.000000

Destructive reshape (pre-launch, no backwards compatibility):
- `skill_tags` → `skills` (+ parent_id, level_anchors, aliases, status,
  origin, provenance; the `deprecated` bool becomes `status`)
- interests/skills move out of JSONB into FK join tables: `job_tags`,
  `job_skills`, `user_interests`, `user_skills` (data is transformed once
  here — no dual read, no legacy shims)
- `career_paths` + `career_path_steps` land with typed nullable refs
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.models.base import StructuredJSON
from app.models.taxonomy_model import DEFAULT_LEVEL_ANCHORS

# revision identifiers, used by Alembic.
revision: str = "b7e4d1a9c3f2"
down_revision: Union[str, None] = "f5b21e8c9a30"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_sqlite() -> bool:
    return op.get_bind().dialect.name == "sqlite"


def upgrade() -> None:
    op.rename_table("skill_tags", "skills")
    if _is_sqlite():
        # SQLite cannot ALTER-add constraints: batch mode recreates the table.
        with op.batch_alter_table("skills") as batch:
            batch.add_column(sa.Column("parent_id", sa.Uuid(), nullable=True))
            batch.create_foreign_key(
                "fk_skills_parent_id_skills",
                "skills",
                ["parent_id"],
                ["id"],
                ondelete="RESTRICT",
            )
            batch.add_column(
                sa.Column("status", sa.String(length=20), nullable=False,
                          server_default="active")
            )
            batch.add_column(
                sa.Column("origin", sa.String(length=20), nullable=False,
                          server_default="bank")
            )
            batch.add_column(
                sa.Column("level_anchors", StructuredJSON, nullable=False,
                          server_default=sa.text("'[]'"))
            )
            batch.add_column(
                sa.Column("aliases", StructuredJSON, nullable=False,
                          server_default=sa.text("'[]'"))
            )
            batch.add_column(
                sa.Column("provenance", StructuredJSON, nullable=True)
            )
    else:
        op.add_column("skills", sa.Column("parent_id", sa.Uuid(), nullable=True))
        op.create_foreign_key(
            "fk_skills_parent_id_skills", "skills", "skills", ["parent_id"],
            ["id"], ondelete="RESTRICT",
        )
        op.add_column(
            "skills", sa.Column("status", sa.String(length=20), nullable=False,
                                server_default="active")
        )
        op.add_column(
            "skills", sa.Column("origin", sa.String(length=20), nullable=False,
                                server_default="bank")
        )
        op.add_column(
            "skills", sa.Column("level_anchors", StructuredJSON, nullable=False,
                                server_default=sa.text("'[]'"))
        )
        op.add_column(
            "skills", sa.Column("aliases", StructuredJSON, nullable=False,
                                server_default=sa.text("'[]'"))
        )
        op.add_column(
            "skills", sa.Column("provenance", StructuredJSON, nullable=True)
        )
    op.create_index(op.f("ix_skills_status"), "skills", ["status"], unique=False)
    _migrate_skill_rows()
    if _is_sqlite():
        with op.batch_alter_table("skills") as batch:
            batch.drop_column("deprecated")
    else:
        op.drop_column("skills", "deprecated")

    _create_join_tables()
    _migrate_job_attributes()
    _migrate_profile_interests()


def _migrate_skill_rows() -> None:
    """status from the deprecated bool; anchor + alias defaults."""
    conn = op.get_bind()
    skills = sa.table(
        "skills",
        sa.column("id", sa.Uuid),
        sa.column("deprecated", sa.Boolean),
        sa.column("status", sa.String),
        sa.column("level_anchors", StructuredJSON),
        sa.column("aliases", StructuredJSON),
    )
    import json

    anchors_json = json.dumps(DEFAULT_LEVEL_ANCHORS)
    for row in conn.execute(
        sa.select(skills.c.id, skills.c.deprecated, skills.c.level_anchors)
    ).fetchall():
        values = {"level_anchors": json.loads(anchors_json)}
        if row.deprecated:
            values["status"] = "deprecated"
        if not row.level_anchors:
            conn.execute(
                skills.update().where(skills.c.id == row.id).values(**values)
            )
        elif values.get("status"):
            conn.execute(
                skills.update()
                .where(skills.c.id == row.id)
                .values(status=values["status"])
            )


def _create_join_tables() -> None:
    op.create_table(
        "job_tags",
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("interest_tag_id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False,
                  server_default="seed"),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_job_tags")),
        sa.ForeignKeyConstraint(
            ["job_id"], ["jobs.id"], name=op.f("fk_job_tags_job_id_jobs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["interest_tag_id"], ["interest_tags.id"],
            name=op.f("fk_job_tags_interest_tag_id_interest_tags"),
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("job_id", "interest_tag_id",
                            name="uq_job_tags_job_tag"),
    )
    op.create_index(
        "ix_job_tags_interest_tag_id", "job_tags", ["interest_tag_id"],
        unique=False,
    )
    op.create_table(
        "job_skills",
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("skill_id", sa.Uuid(), nullable=False),
        sa.Column("required_level", sa.Integer(), nullable=False),
        sa.Column("importance", sa.String(length=20), nullable=False,
                  server_default="core"),
        sa.Column("source", sa.String(length=20), nullable=False,
                  server_default="seed"),
        sa.Column("rationale", sa.Text(), nullable=False, server_default=""),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_job_skills")),
        sa.ForeignKeyConstraint(
            ["job_id"], ["jobs.id"], name=op.f("fk_job_skills_job_id_jobs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["skill_id"], ["skills.id"], name=op.f("fk_job_skills_skill_id_skills"),
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("job_id", "skill_id", name="uq_job_skills_job_skill"),
        sa.CheckConstraint("required_level >= 1 AND required_level <= 10",
                           name=op.f("ck_job_skills_required_level_range")),
    )
    op.create_index("ix_job_skills_skill_id", "job_skills", ["skill_id"],
                    unique=False)
    op.create_table(
        "user_interests",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("interest_tag_id", sa.Uuid(), nullable=False),
        sa.Column("weight", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False,
                  server_default="self"),
        sa.Column("evidence", StructuredJSON, nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_interests")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_user_interests_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["interest_tag_id"], ["interest_tags.id"],
            name=op.f("fk_user_interests_interest_tag_id_interest_tags"),
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("user_id", "interest_tag_id",
                            name="uq_user_interests_user_tag"),
        sa.CheckConstraint("weight >= 1 AND weight <= 5",
                           name=op.f("ck_user_interests_weight_range")),
    )
    op.create_index(
        "ix_user_interests_interest_tag_id", "user_interests",
        ["interest_tag_id"], unique=False,
    )
    op.create_table(
        "user_skills",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("skill_id", sa.Uuid(), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False,
                  server_default="self_report"),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_skills")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_user_skills_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["skill_id"], ["skills.id"], name=op.f("fk_user_skills_skill_id_skills"),
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("user_id", "skill_id", name="uq_user_skills_user_skill"),
        sa.CheckConstraint("level >= 1 AND level <= 10",
                           name=op.f("ck_user_skills_level_range")),
    )
    op.create_index("ix_user_skills_skill_id", "user_skills", ["skill_id"],
                    unique=False)
    op.create_table(
        "career_paths",
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("source", sa.String(length=20), nullable=False,
                  server_default="ai"),
        sa.Column("status", sa.String(length=20), nullable=False,
                  server_default="draft"),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_career_paths")),
        sa.ForeignKeyConstraint(
            ["job_id"], ["jobs.id"], name=op.f("fk_career_paths_job_id_jobs"),
            ondelete="CASCADE",
        ),
    )
    op.create_index(op.f("ix_career_paths_job_id"), "career_paths", ["job_id"],
                    unique=False)
    op.create_index(op.f("ix_career_paths_status"), "career_paths", ["status"],
                    unique=False)
    op.create_table(
        "career_path_steps",
        sa.Column("path_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("family_id", sa.Uuid(), nullable=True),
        sa.Column("skill_id", sa.Uuid(), nullable=True),
        sa.Column("education_level", sa.String(length=30), nullable=True),
        sa.Column("label", sa.String(length=200), nullable=False,
                  server_default=""),
        sa.Column("optional", sa.Boolean(), nullable=False,
                  server_default=sa.false()),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_career_path_steps")),
        sa.ForeignKeyConstraint(
            ["path_id"], ["career_paths.id"],
            name=op.f("fk_career_path_steps_path_id_career_paths"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["family_id"], ["job_families.id"],
            name=op.f("fk_career_path_steps_family_id_job_families"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["skill_id"], ["skills.id"],
            name=op.f("fk_career_path_steps_skill_id_skills"),
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("path_id", "position",
                            name="uq_career_path_steps_position"),
    )


def _migrate_job_attributes() -> None:
    """interests/skills JSONB keys → join rows, then stripped from attributes."""
    import uuid as uuid_mod

    conn = op.get_bind()
    jobs_t = sa.table("jobs", sa.column("id", sa.Uuid),
                      sa.column("attributes", StructuredJSON))
    interest_keys = dict(
        conn.execute(sa.text("SELECT key, id FROM interest_tags")).fetchall()
    )
    skill_keys = dict(conn.execute(sa.text("SELECT key, id FROM skills")).fetchall())
    existing_tags = {
        (r[0], r[1])
        for r in conn.execute(sa.text("SELECT job_id, interest_tag_id FROM job_tags"))
    }
    existing_skills = {
        (r[0], r[1])
        for r in conn.execute(sa.text("SELECT job_id, skill_id FROM job_skills"))
    }
    job_tags = sa.table(
        "job_tags", sa.column("id", sa.Uuid), sa.column("job_id", sa.Uuid),
        sa.column("interest_tag_id", sa.Uuid), sa.column("source", sa.String),
    )
    job_skills = sa.table(
        "job_skills", sa.column("id", sa.Uuid), sa.column("job_id", sa.Uuid),
        sa.column("skill_id", sa.Uuid), sa.column("required_level", sa.Integer),
        sa.column("importance", sa.String), sa.column("source", sa.String),
        sa.column("rationale", sa.Text),
    )
    for job_id, attributes in conn.execute(
        sa.select(jobs_t.c.id, jobs_t.c.attributes)
    ).fetchall():
        attributes = attributes or {}
        changed = False
        for key in attributes.get("interests") or []:
            tag_id = interest_keys.get(key)
            if tag_id is not None and (job_id, tag_id) not in existing_tags:
                conn.execute(
                    job_tags.insert().values(
                        id=uuid_mod.uuid4(), job_id=job_id,
                        interest_tag_id=tag_id, source="seed",
                    )
                )
                existing_tags.add((job_id, tag_id))
                changed = True
        for key in attributes.get("skills") or []:
            skill_id = skill_keys.get(key)
            if skill_id is not None and (job_id, skill_id) not in existing_skills:
                conn.execute(
                    job_skills.insert().values(
                        id=uuid_mod.uuid4(), job_id=job_id, skill_id=skill_id,
                        required_level=5, importance="important", source="seed",
                        rationale="migrated from catalog attributes",
                    )
                )
                existing_skills.add((job_id, skill_id))
                changed = True
        if changed or "interests" in attributes or "skills" in attributes:
            attributes.pop("interests", None)
            attributes.pop("skills", None)
            conn.execute(
                jobs_t.update().where(jobs_t.c.id == job_id)
                .values(attributes=attributes)
            )


def _migrate_profile_interests() -> None:
    """profile.interests JSONB rows → user_interests, then drop the column."""
    import uuid as uuid_mod

    conn = op.get_bind()
    profiles_t = sa.table(
        "profiles",
        sa.column("user_id", sa.Uuid),
        sa.column("interests", StructuredJSON),
    )
    interest_keys = dict(
        conn.execute(sa.text("SELECT key, id FROM interest_tags")).fetchall()
    )
    user_interests = sa.table(
        "user_interests", sa.column("id", sa.Uuid), sa.column("user_id", sa.Uuid),
        sa.column("interest_tag_id", sa.Uuid), sa.column("weight", sa.Integer),
        sa.column("source", sa.String),
    )
    for user_id, interests in conn.execute(
        sa.select(profiles_t.c.user_id, profiles_t.c.interests)
    ).fetchall():
        for item in interests or []:
            tag_id = interest_keys.get(item.get("tag_key"))
            if tag_id is None:
                continue
            conn.execute(
                user_interests.insert().values(
                    id=uuid_mod.uuid4(), user_id=user_id,
                    interest_tag_id=tag_id,
                    weight=int(item.get("weight") or 3),
                    source=str(item.get("source") or "self"),
                )
            )
    if _is_sqlite():
        with op.batch_alter_table("profiles") as batch:
            batch.drop_column("interests")
    else:
        op.drop_column("profiles", "interests")


def downgrade() -> None:
    op.drop_table("career_path_steps")
    op.drop_table("career_paths")
    op.drop_table("user_skills")
    op.drop_table("user_interests")
    op.drop_table("job_skills")
    op.drop_table("job_tags")
    if _is_sqlite():
        with op.batch_alter_table("profiles") as batch:
            batch.add_column(
                sa.Column("interests", StructuredJSON, nullable=False,
                          server_default=sa.text("'[]'"))
            )
    else:
        op.add_column(
            "profiles",
            sa.Column("interests", StructuredJSON, nullable=False,
                      server_default=sa.text("'[]'")),
        )
    op.drop_index(op.f("ix_skills_status"), table_name="skills")
    if _is_sqlite():
        with op.batch_alter_table("skills") as batch:
            batch.drop_column("parent_id")
            batch.drop_column("provenance")
            batch.drop_column("aliases")
            batch.drop_column("level_anchors")
            batch.drop_column("origin")
            batch.drop_column("status")
    else:
        op.drop_column("skills", "provenance")
        op.drop_column("skills", "aliases")
        op.drop_column("skills", "level_anchors")
        op.drop_column("skills", "origin")
        op.drop_column("skills", "status")
        op.drop_constraint(
            "fk_skills_parent_id_skills", "skills", type_="foreignkey"
        )
        op.drop_column("skills", "parent_id")
    op.rename_table("skills", "skill_tags")
    op.add_column(
        "skill_tags",
        sa.Column("deprecated", sa.Boolean(), nullable=False,
                  server_default=sa.false()),
    )
