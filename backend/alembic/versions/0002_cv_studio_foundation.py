"""CV Studio foundation: cv_documents + cv_versions

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-02 22:00:00.000000
"""
from typing import Sequence, Union

import app.models.base
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0002'
down_revision: Union[str, None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('cv_documents',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('target_posting_id', sa.Uuid(), nullable=True),
    sa.Column('language', sa.String(length=10), nullable=False),
    sa.Column('page_size', sa.String(length=10), nullable=False),
    sa.Column('max_pages', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('working_content', postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), 'sqlite'), nullable=False),
    sa.Column('context', postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), 'sqlite'), nullable=False),
    sa.Column('source_document_id', sa.Uuid(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', app.models.base.TZDateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', app.models.base.TZDateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_cv_documents_user_id_users'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['target_posting_id'], ['job_postings.id'], name=op.f('fk_cv_documents_target_posting_id_job_postings'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['source_document_id'], ['documents.id'], name=op.f('fk_cv_documents_source_document_id_documents'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_cv_documents')),
    sa.CheckConstraint("kind IN ('resume', 'cover_letter')", name='kind_allowed'),
    sa.CheckConstraint("status IN ('draft', 'final', 'archived')", name='status_allowed'),
    sa.CheckConstraint("page_size IN ('a4', 'letter')", name='page_size_allowed'),
    sa.CheckConstraint('max_pages >= 1 AND max_pages <= 10', name='max_pages_range')
    )
    op.create_index('ix_cv_documents_user_updated', 'cv_documents', ['user_id', 'updated_at'], unique=False)
    op.create_table('cv_versions',
    sa.Column('cv_document_id', sa.Uuid(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('content', postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), 'sqlite'), nullable=False),
    sa.Column('context_resolution', postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), 'sqlite'), nullable=False),
    sa.Column('content_hash', sa.String(length=64), nullable=False),
    sa.Column('created_by', sa.String(length=20), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', app.models.base.TZDateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', app.models.base.TZDateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['cv_document_id'], ['cv_documents.id'], name=op.f('fk_cv_versions_cv_document_id_cv_documents'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_cv_versions')),
    sa.UniqueConstraint('cv_document_id', 'version', name='uq_cv_versions_doc_version'),
    sa.CheckConstraint("created_by IN ('user_save', 'ai_apply', 'export', 'restore', 'duplicate')", name='created_by_allowed')
    )
    op.create_index('ix_cv_versions_doc_version', 'cv_versions', ['cv_document_id', 'version'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_cv_versions_doc_version', table_name='cv_versions')
    op.drop_table('cv_versions')
    op.drop_index('ix_cv_documents_user_updated', table_name='cv_documents')
    op.drop_table('cv_documents')
