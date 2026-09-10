""": education catalog linkage — education_items gains optional
university_id/department_id FKs (SET NULL) into the universities catalog.

Revision ID: 0017
Revises: 0016
Create Date: 2026-09-07 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0017"
down_revision: Union[str, None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("education_items") as batch:
        batch.add_column(sa.Column("university_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("department_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key(
            op.f("fk_education_items_university_id_universities"),
            "universities",
            ["university_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_foreign_key(
            op.f("fk_education_items_department_id_departments"),
            "departments",
            ["department_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("education_items") as batch:
        batch.drop_constraint(
            op.f("fk_education_items_department_id_departments"),
            type_="foreignkey",
        )
        batch.drop_constraint(
            op.f("fk_education_items_university_id_universities"),
            type_="foreignkey",
        )
        batch.drop_column("department_id")
        batch.drop_column("university_id")
