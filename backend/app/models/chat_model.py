import uuid
from typing import Optional

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, StructuredJSON, TimestampMixin, UUIDPrimaryKeyMixin


class ChatSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A chatbot conversation, optionally anchored to a page context."""

    __tablename__ = "chat_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="New chat")
    context: Mapped[Optional[dict]] = mapped_column(StructuredJSON, nullable=True)

    messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ChatMessage.created_at",
    )


class ChatMessage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One message inside a chat session."""

    __tablename__ = "chat_messages"

    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[Optional[dict]] = mapped_column(StructuredJSON, nullable=True)

    session: Mapped[ChatSession] = relationship(back_populates="messages")
