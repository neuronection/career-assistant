"""CV Studio templates + profile entities (education, certifications, achievements)

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-03 00:30:00.000000
"""
from typing import Sequence, Union

import app.models.base
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0004'
down_revision: Union[str, None] = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('education_items',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('institution', sa.String(length=200), nullable=False),
    sa.Column('org_id', sa.Uuid(), nullable=True),
    sa.Column('org_name', sa.String(length=200), nullable=False),
    sa.Column('program', sa.String(length=200), nullable=False),
    sa.Column('level', sa.String(length=30), nullable=False),
    sa.Column('start', sa.Date(), nullable=True),
    sa.Column('end', sa.Date(), nullable=True),
    sa.Column('in_progress', sa.Boolean(), nullable=False),
    sa.Column('grade_band', sa.String(length=20), nullable=True),
    sa.Column('focus_subjects', postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), 'sqlite'), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('source', sa.String(length=20), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', app.models.base.TZDateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', app.models.base.TZDateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_education_items_user_id_users'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], name=op.f('fk_education_items_org_id_organizations'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_education_items')),
    sa.CheckConstraint("status IN ('draft', 'active')", name='status_allowed'),
    sa.CheckConstraint("source IN ('self_report', 'cv_parse', 'assessment', 'import')", name='source_allowed')
    )
    op.create_index(op.f('ix_education_items_user'), 'education_items', ['user_id'], unique=False)
    op.create_table('certifications',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('issuer', sa.String(length=200), nullable=False),
    sa.Column('org_id', sa.Uuid(), nullable=True),
    sa.Column('issued', sa.Date(), nullable=True),
    sa.Column('expires', sa.Date(), nullable=True),
    sa.Column('credential_id', sa.String(length=120), nullable=False),
    sa.Column('link', sa.String(length=500), nullable=False),
    sa.Column('source', sa.String(length=20), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', app.models.base.TZDateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', app.models.base.TZDateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_certifications_user_id_users'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], name=op.f('fk_certifications_org_id_organizations'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_certifications')),
    sa.CheckConstraint("status IN ('draft', 'active')", name='status_allowed'),
    sa.CheckConstraint("source IN ('self_report', 'cv_parse', 'assessment', 'import')", name='source_allowed')
    )
    op.create_index(op.f('ix_certifications_user'), 'certifications', ['user_id'], unique=False)
    op.create_table('profile_achievements',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('issuer', sa.String(length=200), nullable=False),
    sa.Column('date', sa.Date(), nullable=True),
    sa.Column('detail', sa.Text(), nullable=False),
    sa.Column('link', sa.String(length=500), nullable=False),
    sa.Column('source', sa.String(length=20), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', app.models.base.TZDateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', app.models.base.TZDateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_profile_achievements_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_profile_achievements')),
    sa.CheckConstraint("kind IN ('award', 'honor', 'publication', 'extracurricular')", name='kind_allowed'),
    sa.CheckConstraint("status IN ('draft', 'active')", name='status_allowed'),
    sa.CheckConstraint("source IN ('self_report', 'cv_parse', 'assessment', 'import')", name='source_allowed')
    )
    op.create_index(op.f('ix_profile_achievements_user'), 'profile_achievements', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_profile_achievements_user'), table_name='profile_achievements')
    op.drop_table('profile_achievements')
    op.drop_index(op.f('ix_certifications_user'), table_name='certifications')
    op.drop_table('certifications')
    op.drop_index(op.f('ix_education_items_user'), table_name='education_items')
    op.drop_table('education_items')
