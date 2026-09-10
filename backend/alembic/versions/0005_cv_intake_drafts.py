""" intake: cv_parse_drafts table

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-03 01:30:00.000000
"""
from typing import Sequence, Union

import app.models.base
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0005'
down_revision: Union[str, None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('cv_parse_drafts',
    sa.Column('document_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), 'sqlite'), nullable=False),
    sa.Column('report', postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), 'sqlite'), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', app.models.base.TZDateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', app.models.base.TZDateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], name=op.f('fk_cv_parse_drafts_document_id_documents'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_cv_parse_drafts_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_cv_parse_drafts')),
    sa.UniqueConstraint('document_id', name='uq_cv_parse_drafts_document'),
    sa.CheckConstraint("status IN ('pending', 'applied', 'discarded')", name='status_allowed')
    )


def downgrade() -> None:
    op.drop_table('cv_parse_drafts')
