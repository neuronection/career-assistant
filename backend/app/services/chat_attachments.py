"""Chat CV attachments (plan 78): per-message references resolved into
prompt blocks.

Attachments are a property of the QUESTION, not the session: the user
message stores `{kind, cv_id, title}` snapshots; the turn builds a
deterministic reference block per CV (latest version via ``to_ats_text``,
or the no-write render of ``working_content`` for never-compiled CVs —
never compiles on a read path). Follow-ups without their own attachment
inherit the conversation's most recent attachments as an earlier
reference (AD2b).
"""

import uuid

from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationError
from app.models.cv_model import CvDocument, CvVersion
from app.schemas.chat import ChatAttachmentIn

REFERENCE_TEXT_CAP = 6000


async def resolve_attachments(
    db: AsyncSession, user_id: uuid.UUID, items: list[ChatAttachmentIn]
) -> list[dict]:
    """Validate raw attachments and snapshot them for message metadata.

    Foreign or missing CVs raise (the API maps that to 422 — an
    attachment the model cannot honestly reference is never silently
    dropped).
    """
    if len(items) > 2:
        raise ValidationError("At most 2 attachments per message")
    resolved: list[dict] = []
    seen: set[uuid.UUID] = set()
    for item in items:
        rows = await db.execute(
            select(CvDocument).where(
                CvDocument.id == item.cv_id, CvDocument.user_id == user_id
            )
        )
        cv = rows.scalars().first()
        if cv is None:
            raise ValidationError(f"CV {item.cv_id} not found")
        if cv.id in seen:
            continue
        seen.add(cv.id)
        resolved.append({"kind": "cv", "cv_id": str(cv.id), "title": cv.title})
    return resolved


def _clip(text: str) -> str:
    text = text.strip()
    if len(text) <= REFERENCE_TEXT_CAP:
        return text
    return text[:REFERENCE_TEXT_CAP] + "\n[…capped]"


async def cv_reference_text(db: AsyncSession, cv: CvDocument) -> str:
    """Rendered plain text of the CV's CURRENT state (read-only)."""
    from app.services.cv_builder_service import CvBuilderService
    from app.services.cv_export_service import to_ats_text

    rows = await db.execute(
        select(CvVersion)
        .where(CvVersion.cv_document_id == cv.id)
        .order_by(desc(CvVersion.version))
        .limit(1)
    )
    version = rows.scalars().first()
    if version is not None:
        return _clip(to_ats_text(version.content))

    service = CvBuilderService(db)
    try:
        _html, payload, _resolution, _metrics = await service.render_state(cv)
        return _clip(to_ats_text(payload))
    except Exception:  # noqa: BLE001 — empty context, no template: degrade
        return ""


async def effective_attachments(db: AsyncSession, session, user_message) -> list[dict]:
    """The message's own attachments, or the conversation's most recent
    (earlier reference, AD2b) — the effective turn attachments."""
    from app.models.chat_model import ChatMessage

    attachments = (user_message.metadata_json or {}).get("attachments") or []
    if attachments:
        return attachments
    rows = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session.id, ChatMessage.role == "user")
        .order_by(desc(ChatMessage.created_at))
        .limit(20)
    )
    for candidate in rows.scalars():
        if candidate.id == user_message.id:
            continue
        found = (candidate.metadata_json or {}).get("attachments") or []
        if found:
            return found
    return []


async def attachment_cv(
    db: AsyncSession, user_id: uuid.UUID, cv_id
) -> CvDocument | None:
    """The owned CV behind one attachment entry, or None."""
    try:
        parsed = uuid.UUID(str(cv_id))
    except (ValueError, TypeError):
        return None
    rows = await db.execute(
        select(CvDocument).where(CvDocument.id == parsed, CvDocument.user_id == user_id)
    )
    return rows.scalars().first()


async def turn_references(
    db: AsyncSession, session, user_message
) -> tuple[list[dict], list[dict]]:
    """(stored attachment snapshots, prompt reference blocks) for a turn.

    The message's own attachments are the explicit reference; a message
    with none inherits the most recent attached user message on the
    session's active path (earlier reference, AD2b).
    """
    attachments = await effective_attachments(db, session, user_message)
    earlier = not bool(
        (user_message.metadata_json or {}).get("attachments") or []
    ) and bool(attachments)
    if not attachments:
        return [], []

    references: list[dict] = []
    for entry in attachments[:2]:
        cv = await attachment_cv(db, session.user_id, entry.get("cv_id"))
        if cv is None:
            continue
        text = await cv_reference_text(db, cv)
        references.append(
            {
                "cv_id": str(cv.id),
                "title": entry.get("title") or cv.title,
                "text": text or "(empty document)",
                "earlier": earlier,
            }
        )
    return attachments, references


async def build_turn_references(
    db: AsyncSession, session, user_message_id: uuid.UUID
) -> list[dict]:
    """Reference blocks for a turn keyed by its user message row (the
    shared entry for the sync and streaming reply paths)."""
    from app.models.chat_model import ChatMessage

    message = await db.get(ChatMessage, user_message_id)
    if message is None:
        return []
    _attachments, references = await turn_references(db, session, message)
    return references
