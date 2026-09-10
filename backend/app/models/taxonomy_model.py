import uuid
from typing import Optional

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, StructuredJSON, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import InterestTagKind

# Semantic 1–10 proficiency anchors seeded onto every skill; AI drafts
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

    key: Mapped[str] = mapped_column(
        String(80), unique=True, index=True, nullable=False
    )
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

    key: Mapped[str] = mapped_column(
        String(80), unique=True, index=True, nullable=False
    )
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    category: Mapped[str] = mapped_column(String(60), index=True, nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    parent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("skills.id", ondelete="RESTRICT"), nullable=True
    )
    level_anchors: Mapped[list] = mapped_column(
        StructuredJSON, nullable=False, default=lambda: list(DEFAULT_LEVEL_ANCHORS)
    )
    # Display aliases only — matching/dedup resolves through keys and ids.
    aliases: Mapped[list] = mapped_column(StructuredJSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", index=True
    )
    origin: Mapped[str] = mapped_column(String(20), nullable=False, default="bank")
    # Where a non-bank skill came from: template hash, posting ref, CV parse…
    provenance: Mapped[Optional[dict]] = mapped_column(StructuredJSON, nullable=True)

    parent: Mapped[Optional["Skill"]] = relationship(remote_side="Skill.id")
    children: Mapped[list["Skill"]] = relationship(back_populates="parent")
