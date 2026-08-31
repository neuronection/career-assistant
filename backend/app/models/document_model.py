import uuid
from typing import Optional

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, StructuredJSON, TimestampMixin, UUIDPrimaryKeyMixin


class Document(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An uploaded file (e.g. university admissions PDF) and its extraction."""

    __tablename__ = "documents"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(
        String(40), nullable=False, default="university_catalog"
    )
    filename: Mapped[str] = mapped_column(String(300), nullable=False)
    mime: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    page_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="uploaded", index=True
    )
    error: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    extraction: Mapped[Optional[dict]] = mapped_column(StructuredJSON, nullable=True)
