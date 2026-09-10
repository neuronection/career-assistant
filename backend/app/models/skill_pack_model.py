"""Agent skill packs: versioned instruction packs as data.

Packs steer tone/structure per AI task — content, not code. The gateway
resolves the latest published bank pack for a task, appends its
instructions to the system prompt, and pins `pack_key`/`pack_version` on
the audit row so every call records which pack version served it. Packs
never bypass validators: they carry no behavioral claims, only
instructions the same pydantic/registry discipline still gates.
"""

import uuid

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    Base,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)


class AISkillPack(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One immutable skill-pack version (37's versioning discipline)."""

    __tablename__ = "ai_skill_packs"
    __table_args__ = (
        UniqueConstraint(
            "author_key", "key", "version", name="uq_ai_skill_packs_version"
        ),
        CheckConstraint(
            "status IN ('draft', 'published', 'retired')", name="status_allowed"
        ),
        CheckConstraint("version >= 1", name="version_positive"),
        Index("ix_ai_skill_packs_task_status", "task", "status"),
    )

    key: Mapped[str] = mapped_column(String(80), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    # AITaskType value the pack binds to (open enum — plain string, no FK).
    task: Mapped[str] = mapped_column(String(60), nullable=False)
    instructions: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    author_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # 'bank' for system packs, else the author's user id.
    author_key: Mapped[str] = mapped_column(String(64), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
