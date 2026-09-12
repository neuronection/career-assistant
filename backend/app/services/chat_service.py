import uuid
from collections import defaultdict
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.ai.agents import chat_reply
from app.core.errors import DomainError, NotFoundError, PermissionDeniedError
from app.models.chat_model import ChatMessage, ChatSession
from app.models.user_model import Profile
from app.schemas.chat import SessionCreate
from app.services.profile_service import ProfileService

EXCERPT_LEN = 100


def _sort_key(message: ChatMessage):
    return (message.created_at, message.id)


def _walk_active_path(
    all_messages: list[ChatMessage], active_root_id: Optional[uuid.UUID]
) -> list[ChatMessage]:
    """The visible conversation: pointer walk from the active root, active-
    child pointers with newest-sibling fallback, cycle-safe."""
    by_id = {message.id: message for message in all_messages}
    children: dict[Optional[uuid.UUID], list[ChatMessage]] = defaultdict(list)
    for message in sorted(all_messages, key=_sort_key):
        children[message.parent_id].append(message)

    start = active_root_id if active_root_id in by_id else None
    if start is None:
        roots = children.get(None, [])
        start = roots[-1].id if roots else None

    path: list[ChatMessage] = []
    visited: set[uuid.UUID] = set()
    current = start
    while current is not None and current not in visited:
        node = by_id.get(current)
        if node is None:
            break
        visited.add(current)
        path.append(node)
        kids = children.get(current, [])
        nxt = node.active_child_id if node.active_child_id in by_id else None
        if nxt is None and kids:
            nxt = kids[-1].id
        current = nxt
    return path


def _siblings_of(
    message: ChatMessage,
    children: dict[Optional[uuid.UUID], list[ChatMessage]],
) -> list[ChatMessage]:
    return children.get(message.parent_id, [message])


def _decorate(messages: list[ChatMessage], all_messages: list[ChatMessage]) -> None:
    """Attach variant info in-memory (index/count/sibling ids) for MessageOut."""
    children: dict[Optional[uuid.UUID], list[ChatMessage]] = defaultdict(list)
    for message in sorted(all_messages, key=_sort_key):
        children[message.parent_id].append(message)
    for message in messages:
        siblings = _siblings_of(message, children)
        ids = [sibling.id for sibling in siblings]
        object.__setattr__(message, "sibling_ids", ids)
        object.__setattr__(message, "variant_count", len(ids))
        try:
            object.__setattr__(message, "variant_index", ids.index(message.id) + 1)
        except ValueError:  # pragma: no cover - defensive
            object.__setattr__(message, "variant_index", 1)


class ChatService:
    """Chat sessions backed by the chatbot agent with catalog tools.
    Messages form a branch tree (family contract): parent +
    active-child pointers; the visible conversation is the active path."""

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

    async def seed_assistant_message(
        self,
        session: ChatSession,
        content: str,
        metadata: Optional[dict] = None,
    ) -> ChatMessage:
        """Root assistant message (no user turn before it) — the opening
        question of an interview practice session."""
        message = ChatMessage(
            session_id=session.id,
            role="assistant",
            content=content,
            metadata_json=metadata,
        )
        self.db.add(message)
        await self.db.flush()
        session.active_root_id = message.id
        await self.db.commit()
        await self.db.refresh(message)
        return message

    async def list_sessions(
        self, user_id: uuid.UUID
    ) -> list[tuple[ChatSession, datetime]]:
        """Sessions of the caller with computed last activity, most recent
        first. `updated_at` only moves on session-row writes (rename), so
        the real recency signal is the newest message timestamp."""
        last_message_at = (
            select(func.max(ChatMessage.created_at))
            .where(ChatMessage.session_id == ChatSession.id)
            .correlate(ChatSession)
            .scalar_subquery()
        )
        rows = await self.db.execute(
            select(ChatSession, last_message_at).where(ChatSession.user_id == user_id)
        )
        items = [
            (session, self._last_activity(session, last_message))
            for session, last_message in rows.all()
        ]
        items.sort(key=lambda item: (item[1], item[0].id), reverse=True)
        return items

    @staticmethod
    def _last_activity(
        session: ChatSession, last_message: Optional[datetime]
    ) -> datetime:
        updated = session.updated_at or session.created_at
        return max(updated, last_message) if last_message else updated

    async def last_activity(self, session: ChatSession) -> datetime:
        """Computed last activity of one session (newest message, else the
        session's own update)."""
        rows = await self.db.execute(
            select(func.max(ChatMessage.created_at)).where(
                ChatMessage.session_id == session.id
            )
        )
        return self._last_activity(session, rows.scalar_one_or_none())

    async def _load_session(self, session_id: uuid.UUID) -> ChatSession:
        rows = await self.db.execute(
            select(ChatSession)
            .options(selectinload(ChatSession.messages))
            .where(ChatSession.id == session_id)
        )
        session = rows.scalars().first()
        if session is None:
            raise NotFoundError("Session not found")
        return session

    async def _owned_session(
        self, user_id: uuid.UUID, session_id: uuid.UUID
    ) -> ChatSession:
        session = await self._load_session(session_id)
        if session.user_id != user_id:
            raise PermissionDeniedError("Not your session")
        return session

    async def get_session(
        self, user_id: uuid.UUID, session_id: uuid.UUID
    ) -> ChatSession:
        """Fetch a session owned by the caller."""
        return await self._owned_session(user_id, session_id)

    async def rename_session(
        self, user_id: uuid.UUID, session_id: uuid.UUID, title: str
    ) -> ChatSession:
        """Rename a session owned by the caller."""
        session = await self._owned_session(user_id, session_id)
        session.title = title
        await self.db.commit()
        await self.db.refresh(session)
        return session

    async def delete_session(self, user_id: uuid.UUID, session_id: uuid.UUID) -> None:
        """Delete a session owned by the caller; messages cascade."""
        session = await self._owned_session(user_id, session_id)
        await self.db.delete(session)
        await self.db.commit()

    async def _all_messages(self, session: ChatSession) -> list[ChatMessage]:
        await self.db.refresh(session, ["messages"])
        return list(session.messages)

    async def messages(
        self, user_id: uuid.UUID, session_id: uuid.UUID
    ) -> list[ChatMessage]:
        """The visible (active-path) messages, variant-decorated."""
        session = await self._owned_session(user_id, session_id)
        all_messages = await self._all_messages(session)
        visible = _walk_active_path(all_messages, session.active_root_id)
        _decorate(visible, all_messages)
        return visible

    async def begin_message(
        self,
        user_id: uuid.UUID,
        session_id: uuid.UUID,
        content: str,
    ) -> tuple[ChatSession, list[dict], uuid.UUID]:
        """Persist the user message at the active tip; returns
        (session, history, message id)."""
        session = await self._owned_session(user_id, session_id)
        all_messages = await self._all_messages(session)
        path = _walk_active_path(all_messages, session.active_root_id)
        history = [
            {"role": m.role, "content": m.content}
            for m in path
            if m.role in ("user", "assistant")
        ]

        message = ChatMessage(session_id=session.id, role="user", content=content)
        self.db.add(message)
        await self.db.flush()

        tip = path[-1] if path else None
        if tip is None:
            session.active_root_id = message.id
        else:
            tip.active_child_id = message.id
        await self.db.flush()
        return session, history, message.id

    async def complete_message(
        self,
        session: ChatSession,
        parent_user_message_id: uuid.UUID,
        reply,
        tool_metadata: dict,
    ) -> ChatMessage:
        """Persist the assistant reply under its user message and point the
        path at it."""
        parent = await self.db.get(ChatMessage, parent_user_message_id)
        if parent is None:
            raise NotFoundError("Parent message not found")
        message = ChatMessage(
            session_id=session.id,
            role="assistant",
            content=reply.answer,
            parent_id=parent.id,
            metadata_json={
                **tool_metadata,
                "referenced_job_codes": reply.referenced_job_codes,
                "referenced_posting_refs": getattr(reply, "referenced_posting_refs", [])
                or tool_metadata.get("refs", []),
            },
        )
        self.db.add(message)
        await self.db.flush()
        parent.active_child_id = message.id
        await self.db.commit()
        await self.db.refresh(message)
        return message

    async def complete_builder_turn(
        self,
        session: ChatSession,
        parent_user_message_id: uuid.UUID,
        answer: str,
        metadata: dict,
    ) -> ChatMessage:
        """Persist a CV-builder copilot reply: plain answer +
        op-trace metadata, under its user message at the active tip."""
        parent = await self.db.get(ChatMessage, parent_user_message_id)
        if parent is None:
            raise NotFoundError("Parent message not found")
        message = ChatMessage(
            session_id=session.id,
            role="assistant",
            content=answer,
            parent_id=parent.id,
            metadata_json=metadata,
        )
        self.db.add(message)
        await self.db.flush()
        parent.active_child_id = message.id
        await self.db.commit()
        await self.db.refresh(message)
        return message

    async def complete_interrupted(
        self,
        session: ChatSession,
        parent_user_message_id: uuid.UUID,
        partial: str,
        metadata: Optional[dict] = None,
        *,
        allow_empty: bool = False,
    ) -> Optional[ChatMessage]:
        """Persist an aborted turn's partial prefix as an interrupted
        assistant message (study pattern, stop feature) — with
        the partial turn trace when the stream runner gathered one.
        `allow_empty` lets a trace-only turn (builder copilot error
        path) persist with no reply text."""
        if not partial.strip() and not allow_empty:
            return None
        parent = await self.db.get(ChatMessage, parent_user_message_id)
        if parent is None:
            return None
        message = ChatMessage(
            session_id=session.id,
            role="assistant",
            content=partial,
            parent_id=parent.id,
            metadata_json={"stream_interrupted": True, **(metadata or {})},
        )
        self.db.add(message)
        await self.db.flush()
        parent.active_child_id = message.id
        await self.db.commit()
        await self.db.refresh(message)
        return message

    async def _get_message(
        self, user_id: uuid.UUID, message_id: uuid.UUID
    ) -> tuple[ChatSession, ChatMessage]:
        message = await self.db.get(ChatMessage, message_id)
        if message is None:
            raise NotFoundError("Message not found")
        session = await self._owned_session(user_id, message.session_id)
        return session, message

    async def edit_message(
        self, user_id: uuid.UUID, message_id: uuid.UUID, content: str
    ) -> tuple[ChatSession, list[dict], uuid.UUID]:
        """Branch a user message: new sibling with the edited content, flip
        the parent's active-child pointer, return context for a fresh turn."""
        session, message = await self._get_message(user_id, message_id)
        if message.role != "user":
            raise DomainError("Only user messages can be edited")
        all_messages = await self._all_messages(session)
        by_id = {m.id: m for m in all_messages}

        edited = ChatMessage(
            session_id=session.id,
            role="user",
            content=content,
            parent_id=message.parent_id,
        )
        self.db.add(edited)
        await self.db.flush()

        if message.parent_id is not None and message.parent_id in by_id:
            by_id[message.parent_id].active_child_id = edited.id
        else:
            session.active_root_id = edited.id
        await self.db.flush()

        path = _walk_active_path(all_messages + [edited], session.active_root_id)
        history = [
            {"role": m.role, "content": m.content}
            for m in path
            if m.id != edited.id and m.role in ("user", "assistant")
        ]
        return session, history, edited.id

    async def regenerate_message(
        self, user_id: uuid.UUID, message_id: uuid.UUID
    ) -> tuple[ChatSession, list[dict], uuid.UUID, str]:
        """Prepare a fresh assistant sibling under this user message."""
        session, message = await self._get_message(user_id, message_id)
        if message.role != "user":
            raise DomainError("Regenerate targets a user message")
        all_messages = await self._all_messages(session)
        by_id = {m.id: m for m in all_messages}
        path = _walk_active_path(all_messages, session.active_root_id)
        if message not in path:
            # Off-path regeneration: activate this branch up to the target.
            self._activate_path_to(by_id, session, message)
            path = _walk_active_path(all_messages, session.active_root_id)
        history = [
            {"role": m.role, "content": m.content}
            for m in path
            if m.id != message.id and m.role in ("user", "assistant")
        ]
        return session, history, message.id, message.content

    def _activate_path_to(
        self,
        by_id: dict[uuid.UUID, ChatMessage],
        session: ChatSession,
        target: ChatMessage,
    ) -> None:
        chain: list[ChatMessage] = []
        current: Optional[ChatMessage] = target
        while current is not None:
            chain.append(current)
            current = by_id.get(current.parent_id) if current.parent_id else None
        chain.reverse()
        if chain and chain[0].parent_id is None:
            session.active_root_id = chain[0].id
        for parent, child in zip(chain, chain[1:]):
            parent.active_child_id = child.id

    async def select_message(
        self, user_id: uuid.UUID, message_id: uuid.UUID
    ) -> list[ChatMessage]:
        """Flip exactly one pointer: the parent's active child (or the
        session's active root for root-level variants). Level-flip
        semantics — no ancestor-chain activation (family contract)."""
        session, message = await self._get_message(user_id, message_id)
        all_messages = await self._all_messages(session)
        by_id = {m.id: m for m in all_messages}
        if message.parent_id is not None and message.parent_id in by_id:
            by_id[message.parent_id].active_child_id = message.id
        else:
            session.active_root_id = message.id
        await self.db.commit()
        visible = _walk_active_path(all_messages, session.active_root_id)
        _decorate(visible, all_messages)
        return visible

    async def tree(self, user_id: uuid.UUID, session_id: uuid.UUID) -> dict[str, Any]:
        """Read-only branch-tree projection for the graph rail."""
        session = await self._owned_session(user_id, session_id)
        all_messages = await self._all_messages(session)
        children: dict[Optional[uuid.UUID], list[uuid.UUID]] = defaultdict(list)
        for message in sorted(all_messages, key=_sort_key):
            children[message.parent_id].append(message.id)
        nodes = [
            {
                "id": message.id,
                "role": message.role,
                "excerpt": (message.content or "")[:EXCERPT_LEN],
                "parent_id": message.parent_id,
                "children": children.get(message.id, []),
                "active_child_id": message.active_child_id,
            }
            for message in sorted(all_messages, key=_sort_key)
        ]
        return {"active_root_id": session.active_root_id, "nodes": nodes}

    async def finish_turn(
        self,
        session: ChatSession,
        history: list[dict],
        parent_user_message_id: uuid.UUID,
        content: str,
        profile: Profile,
    ) -> ChatMessage:
        """Generate + persist a reply under an existing user message
        (used by edit-branch and regenerate, sync mode). CV-builder-bound
        sessions run the copilot loop instead of the generic
        chatbot — same persistence, same branching."""
        context = session.context or {}
        if context.get("surface") == "cv_builder":
            return await self._finish_builder_turn(
                session, history, parent_user_message_id, content
            )
        if context.get("surface") == "interview":
            return await self._finish_interview_turn(
                session, history, parent_user_message_id, content
            )
        reply, tool_metadata = await chat_reply(
            self.db,
            session.user_id,
            profile_summary=await ProfileService(self.db).profile_summary(profile),
            history=history,
            message=content,
            page_context=session.context,
        )
        return await self.complete_message(
            session, parent_user_message_id, reply, tool_metadata
        )

    async def _finish_builder_turn(
        self,
        session: ChatSession,
        history: list[dict],
        parent_user_message_id: uuid.UUID,
        content: str,
    ) -> ChatMessage:
        """Drain one copilot turn (ops + review + persistence)."""
        import uuid as uuid_mod

        from app.ai.agents.cv_builder_chat import builder_turn_events
        from app.services.cv_service import CvService

        cv = await CvService(self.db).get_owned(
            uuid_mod.UUID(str((session.context or {}).get("cv_id"))),
            session.user_id,
        )
        async for _event, _payload in builder_turn_events(
            self.db,
            cv,
            session=session,
            user_id=session.user_id,
            message=content,
            history=history,
            user_message_id=parent_user_message_id,
        ):
            pass
        all_messages = await self._all_messages(session)
        path = _walk_active_path(all_messages, session.active_root_id)
        if not path:
            raise NotFoundError("Turn produced no messages")
        return path[-1]

    async def _finish_interview_turn(
        self,
        session: ChatSession,
        history: list[dict],
        parent_user_message_id: uuid.UUID,
        content: str,
    ) -> ChatMessage:
        """Drain one interview practice turn."""
        import uuid as uuid_mod

        from app.ai.agents.interview_coach import interview_turn_events
        from app.services.interview_service import InterviewService

        interview = await InterviewService(self.db).get(
            session.user_id,
            uuid_mod.UUID(str((session.context or {}).get("interview_id"))),
        )
        async for _event, _payload in interview_turn_events(
            self.db,
            interview,
            session=session,
            user_id=session.user_id,
            message=content,
            history=history,
            user_message_id=parent_user_message_id,
        ):
            pass
        all_messages = await self._all_messages(session)
        path = _walk_active_path(all_messages, session.active_root_id)
        if not path:
            raise NotFoundError("Turn produced no messages")
        return path[-1]

    async def send_message(
        self,
        user_id: uuid.UUID,
        session_id: uuid.UUID,
        content: str,
        profile: Profile,
    ) -> ChatMessage:
        """Append a user message and generate the assistant reply."""
        session, history, message_id = await self.begin_message(
            user_id, session_id, content
        )
        return await self.finish_turn(session, history, message_id, content, profile)
