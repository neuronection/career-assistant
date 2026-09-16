"""Auto titles for chat sessions (plan 93).

After a session's first user message is persisted, a tiny FAST-tier task
titles the session from that message. AI unconfigured (the production
default) or any failure degrades to a deterministic truncation of the
message, so sessions never stay titled "New chat".
"""

from pydantic import BaseModel, Field

from app.ai.gateway import ainvoke_structured, register_mock_fixture
from app.models.enums import AITaskType

FALLBACK_MAX_CHARS = 60


class ChatTitleOut(BaseModel):
    title: str = Field(max_length=80)


SYSTEM = (
    "You write chat-session titles. Return a short specific title (3-6 "
    "words) for the conversation the user is starting, in the user's "
    "language. No quotes, no trailing period."
)


def fallback_title(content: str) -> str:
    """Deterministic title: first line of the message, trimmed hard."""
    line = content.strip().splitlines()[0] if content.strip() else ""
    line = line.strip()
    if len(line) > FALLBACK_MAX_CHARS:
        line = line[: FALLBACK_MAX_CHARS - 1].rstrip() + "…"
    return line


async def generate_session_title(db, user_id, first_message: str) -> str:
    """Title from the LLM task, or the deterministic fallback."""
    try:
        out = await ainvoke_structured(
            db,
            AITaskType.CHAT_TITLE,
            ChatTitleOut,
            SYSTEM,
            first_message,
            user_id=user_id,
        )
        title = out.title.strip()
        if title:
            return title[:80]
    except Exception:  # noqa: BLE001 - titles must never break a chat turn
        pass
    return fallback_title(first_message)


def _mock_title(schema: type[ChatTitleOut], user: str) -> ChatTitleOut:
    return schema(title="Mock generated title")


register_mock_fixture(AITaskType.CHAT_TITLE, _mock_title)
