""": model-tier routing + audit columns

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-04 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0006'
down_revision: Union[str, None] = '0005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'ai_models', sa.Column('tier', sa.String(length=10), nullable=True)
    )
    op.add_column(
        'ai_task_assignments',
        sa.Column('tier', sa.String(length=10), nullable=True),
    )
    op.add_column(
        'ai_generations',
        sa.Column('task_tier', sa.String(length=10), nullable=True),
    )
    op.add_column(
        'ai_generations',
        sa.Column('prompt_version', sa.String(length=40), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('ai_generations', 'prompt_version')
    op.drop_column('ai_generations', 'task_tier')
    op.drop_column('ai_task_assignments', 'tier')
    op.drop_column('ai_models', 'tier')
