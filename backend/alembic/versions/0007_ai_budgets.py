""": ai_budgets table

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-04 14:00:00.000000
"""
from typing import Sequence, Union

import app.models.base
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0007'
down_revision: Union[str, None] = '0006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('ai_budgets',
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('task_type', sa.String(length=40), nullable=True),
    sa.Column('user_id', sa.Uuid(), nullable=True),
    sa.Column('window', sa.String(length=10), nullable=False),
    sa.Column('max_tokens', sa.Integer(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', app.models.base.TZDateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', app.models.base.TZDateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_ai_budgets_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ai_budgets')),
    sa.UniqueConstraint('name', name='uq_ai_budgets_name')
    )
    op.create_index(
        op.f('ix_ai_budgets_user_id'), 'ai_budgets', ['user_id'], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_ai_budgets_user_id'), table_name='ai_budgets')
    op.drop_table('ai_budgets')
