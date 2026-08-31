import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.ai.agents import chat_reply
from app.core.errors import NotFoundError, PermissionDeniedError
from app.models.chat_model import ChatMessage, ChatSession
from app.models.user_model import Profile
from app.schemas.chat import SessionCreate
from app.services.profile_service import ProfileService


class ChatService:
    """Chat sessions backed by the chatbot agent with catalog tools."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_session(
        self, user_id: uuid.UUID, data: SessionCreate
    ) -> ChatSession:
        """Start a new chat session."""
        session = ChatSession(user_id=user_id, title=data.title, context=data.context)
        self.db.add(session)
        await self.db.commit()
        await self.db.refresh(session)
        return session

    async def list_sessions(self, user_id: uuid.UUID) -> list[ChatSession]:
        """Sessions of a user, newest first."""
        rows = await self.db.execute(
            select(ChatSession)
            .where(ChatSession.user_id == user_id)
            # Stable tiebreaker for identical timestamps (e.g. migrated data).
            .order_by(ChatSession.updated_at.desc(), ChatSession.id.desc())
        )
        return list(rows.scalars().all())

    async def get_session(
        self, user_id: uuid.UUID, session_id: uuid.UUID
    ) -> ChatSession:
        """Fetch a session owned by the caller."""
        rows = await self.db.execute(
            select(ChatSession)
            .options(selectinload(ChatSession.messages))
            .where(ChatSession.id == session_id)
        )
        session = rows.scalars().first()
        if session is None:
            raise NotFoundError("Session not found")
        if session.user_id != user_id:
            raise PermissionDeniedError("Not your session")
        return session

    async def messages(
        self, user_id: uuid.UUID, session_id: uuid.UUID
    ) -> list[ChatMessage]:
        """Messages of a session in order."""
        session = await self.get_session(user_id, session_id)
        return list(session.messages)

    async def begin_message(
        self,
        user_id: uuid.UUID,
        session_id: uuid.UUID,
        content: str,
    ) -> tuple[ChatSession, list[dict], uuid.UUID]:
        """Persist the user message; returns (session, history, message id)."""
        session = await self.get_session(user_id, session_id)
        history = [
            {"role": m.role, "content": m.content}
            for m in session.messages
            if m.role in ("user", "assistant")
        ]
        message = ChatMessage(session_id=session.id, role="user", content=content)
        self.db.add(message)
        await self.db.flush()
        return session, history, message.id

    async def complete_message(
        self,
        session: ChatSession,
        reply,
        tool_metadata: dict,
    ) -> ChatMessage:
        """Persist the assistant reply and return it."""
        message = ChatMessage(
            session_id=session.id,
            role="assistant",
            content=reply.answer,
            metadata_json={
                **tool_metadata,
                "referenced_job_codes": reply.referenced_job_codes,
                "referenced_posting_refs": getattr(reply, "referenced_posting_refs", [])
                or tool_metadata.get("refs", []),
            },
        )
        self.db.add(message)
        await self.db.commit()
        await self.db.refresh(message)
        return message

    async def send_message(
        self,
        user_id: uuid.UUID,
        session_id: uuid.UUID,
        content: str,
        profile: Profile,
    ) -> ChatMessage:
        """Append a user message and generate the assistant reply."""
        session, history, _ = await self.begin_message(user_id, session_id, content)

        reply, tool_metadata = await chat_reply(
            self.db,
            user_id,
            profile_summary=await ProfileService(self.db).profile_summary(profile),
            history=history,
            message=content,
            page_context=session.context,
        )
        return await self.complete_message(session, reply, tool_metadata)
