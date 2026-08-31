import uuid
from typing import Optional

from sqlalchemy import Boolean, ForeignKey, Integer, Float, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class AIProvider(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Configured AI provider (scope system = global, user = personal)."""

    __tablename__ = "ai_providers"
    __table_args__ = (
        UniqueConstraint(
            "scope", "user_id", "name", name="uq_ai_providers_scope_user_name"
        ),
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    scope: Mapped[str] = mapped_column(
        String(20), nullable=False, default="system", index=True
    )
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    provider_type: Mapped[str] = mapped_column(
        String(40), nullable=False, default="openai_compatible"
    )
    api_base: Mapped[str] = mapped_column(
        String(500), nullable=False, default="https://api.openai.com/v1"
    )
    api_key_encrypted: Mapped[Optional[str]] = mapped_column(String(600), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    models: Mapped[list["AIModel"]] = relationship(
        back_populates="provider", cascade="all, delete-orphan"
    )
    task_assignments: Mapped[list["AITaskAssignment"]] = relationship(
        back_populates="provider", cascade="all, delete-orphan"
    )

    @property
    def api_key(self) -> Optional[str]:
        """Decrypted API key (legacy plaintext rows are read verbatim)."""
        from app.core.encryption import decrypt_secret

        return decrypt_secret(self.api_key_encrypted)


class AIModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A concrete model exposed by a provider (e.g. gpt-4o-mini)."""

    __tablename__ = "ai_models"

    provider_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ai_providers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    model_name: Mapped[str] = mapped_column(String(200), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    temperature: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    max_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    provider: Mapped[AIProvider] = relationship(back_populates="models")


class AITaskAssignment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Maps a task type to a provider/model at system or user scope."""

    __tablename__ = "ai_task_assignments"

    task_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    scope: Mapped[str] = mapped_column(
        String(20), nullable=False, default="system", index=True
    )
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    provider_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("ai_providers.id", ondelete="CASCADE"), nullable=True
    )
    model_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("ai_models.id", ondelete="CASCADE"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    provider: Mapped[Optional[AIProvider]] = relationship(
        back_populates="task_assignments"
    )
    model: Mapped[Optional[AIModel]] = relationship()
