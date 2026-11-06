"""Catalog i18n overlays (plan 113, consumed by 121).

A `label_overrides` row replaces one display field of a catalog entity in
one locale — review-first, like every AI surface: AI drafts land as
`draft`, approval is the only route to `approved`.
"""

import uuid

from sqlalchemy import CheckConstraint, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

_ENTITY_KIND_ALLOWED = (
    "entity_kind IN ('job', 'skill', 'family', 'university', 'department', "
    "'metric_dimension', 'assessment_template', 'cv_template')"
)
_FIELD_ALLOWED = "field IN ('label', 'description', 'short_description')"
_SOURCE_ALLOWED = "source IN ('ai_draft', 'human')"
_STATUS_ALLOWED = "status IN ('draft', 'approved', 'rejected')"


class LabelOverride(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One localized override of a catalog display field."""

    __tablename__ = "label_overrides"
    __table_args__ = (
        UniqueConstraint(
            "entity_kind", "entity_id", "locale", "field", name="uq_label_overrides_target"
        ),
        CheckConstraint(_ENTITY_KIND_ALLOWED, name="entity_kind_allowed"),
        CheckConstraint(_FIELD_ALLOWED, name="field_allowed"),
        CheckConstraint(_SOURCE_ALLOWED, name="source_allowed"),
        CheckConstraint(_STATUS_ALLOWED, name="status_allowed"),
    )

    entity_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    # Polymorphic-by-kind ref confined to this overlay table; the
    # (kind, id) unique key keeps it honest.
    entity_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    locale: Mapped[str] = mapped_column(String(8), nullable=False)
    field: Mapped[str] = mapped_column(String(32), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source: Mapped[str] = mapped_column(String(12), nullable=False, default="ai_draft")
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="draft")
