import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import CheckConstraint, Float, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import (
    Base,
    StructuredJSON,
    TimestampMixin,
    TZDateTime,
    UUIDPrimaryKeyMixin,
)
from app.models.enums import InterestTagKind, SkillRelationStatus, SkillRelationType

# Semantic 1-10 proficiency anchors seeded onto every skill; AI drafts
# per-skill anchors and admins review overrides (Phase 21).
DEFAULT_LEVEL_ANCHORS: list[dict] = [
    {
        "level": 1,
        "label": "Novice",
        "description": "Aware of the basics; needs step-by-step guidance.",
    },
    {
        "level": 3,
        "label": "Guided",
        "description": "Can do it with support and examples.",
    },
    {
        "level": 6,
        "label": "Independent",
        "description": "Works unsupervised on routine tasks.",
    },
    {
        "level": 9,
        "label": "Expert",
        "description": "Handles the hardest cases; others learn from them.",
    },
]


class InterestTag(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Controlled vocabulary of interest areas referenced by key."""

    __tablename__ = "interest_tags"

    key: Mapped[str] = mapped_column(String(80), unique=True, index=True, nullable=False)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    category: Mapped[str] = mapped_column(String(60), index=True, nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    # Deprecated tags stay resolvable (jobs/profiles reference them) but are
    # hidden from onboarding pickers; deletion is the admin's last resort.
    deprecated: Mapped[bool] = mapped_column(nullable=False, default=False)
    # topic vs industry (Phase 24) — one vocabulary, filterable distinction.
    kind: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=InterestTagKind.TOPIC.value,
        server_default=InterestTagKind.TOPIC.value,
        index=True,
    )


class Skill(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Skillset ontology node referenced by key (ex `skill_tags`).

    Lifecycle: proposed (usable in its originating context only) → active
    (catalog/fit default) → deprecated (resolvable, hidden from pickers).
    """

    __tablename__ = "skills"

    key: Mapped[str] = mapped_column(String(80), unique=True, index=True, nullable=False)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    category: Mapped[str] = mapped_column(String(60), index=True, nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("skills.id", ondelete="RESTRICT"), nullable=True
    )
    level_anchors: Mapped[list] = mapped_column(
        StructuredJSON, nullable=False, default=lambda: list(DEFAULT_LEVEL_ANCHORS)
    )
    # Display aliases only — matching/dedup resolves through keys and ids.
    aliases: Mapped[list] = mapped_column(StructuredJSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", index=True)
    origin: Mapped[str] = mapped_column(String(20), nullable=False, default="bank")
    # Where a non-bank skill came from: template hash, posting ref, CV parse…
    provenance: Mapped[dict | None] = mapped_column(StructuredJSON, nullable=True)

    parent: Mapped[Optional["Skill"]] = relationship(remote_side="Skill.id")
    children: Mapped[list["Skill"]] = relationship(back_populates="parent")


class SkillRelation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Typed edge between two skills — multi-parent truth over the
    one-parent tree (plan 138).

    Symmetric kinds (``synonym``, ``related_to``) are stored with
    canonically ordered endpoints — ``from_skill_id`` is the lower UUID —
    so one unordered pair can never carry two rows and a rejection blocks
    both directions; directed kinds (``SkillRelationType.directed()``)
    keep their direction. ``status='rejected'`` is the negative edge
    ("never this pair + relation"), not a tombstone.
    """

    __tablename__ = "skill_relations"
    __table_args__ = (
        UniqueConstraint("from_skill_id", "to_skill_id", "relation", name="uq_skill_relation_edge"),
        CheckConstraint("from_skill_id != to_skill_id", name="no_self_loop"),
        CheckConstraint(
            f"relation IN ({SkillRelationType.allowed_sql()})",
            name="relation_allowed",
        ),
        CheckConstraint(
            "status IN ('proposed', 'approved', 'rejected')",
            name="status_allowed",
        ),
        CheckConstraint(
            "source IN ('llm', 'manual', 'import', 'derived')",
            name="source_allowed",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="confidence_range",
        ),
        # Directed kinds are the ones the enum calls directed — one source of
        # truth, so vocabulary growth can't silently break pair ordering/dedup.
        CheckConstraint(
            f"relation IN ({SkillRelationType.directed_sql()}) OR from_skill_id <= to_skill_id",
            name="symmetric_pair_ordered",
        ),
        Index("ix_skill_relations_from", "from_skill_id"),
        Index("ix_skill_relations_to", "to_skill_id"),
        Index("ix_skill_relations_relation_status", "relation", "status"),
    )

    from_skill_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("skills.id", ondelete="CASCADE"), nullable=False
    )
    to_skill_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("skills.id", ondelete="CASCADE"), nullable=False
    )
    relation: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=SkillRelationStatus.PROPOSED.value,
        server_default=SkillRelationStatus.PROPOSED.value,
    )
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    evidence: Mapped[dict | None] = mapped_column(StructuredJSON, nullable=True)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
