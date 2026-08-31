"""User data export: everything a user owns, packaged as a versioned zip."""

import json
import logging
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.chat_model import ChatMessage, ChatSession
from app.models.document_model import Document
from app.models.matching_model import MatchInsight
from app.models.user_model import Profile, User
from app.services.document_service import DocumentService

logger = logging.getLogger(__name__)

MANIFEST_SCHEMA_VERSION = 1


def _row_dict(row) -> dict:
    """Serialize a model row with JSON-safe primitives."""
    return {
        column.name: _jsonable(getattr(row, column.name))
        for column in row.__table__.columns
    }


def _jsonable(value):
    if isinstance(value, (datetime,)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


def export_dir() -> Path:
    path = Path(settings.UPLOAD_DIR) / "exports"
    path.mkdir(parents=True, exist_ok=True)
    return path


async def collect_user_data(
    db: AsyncSession, user_id: uuid.UUID
) -> tuple[dict, list[Document]]:
    """Gather every user-owned entity as plain JSON-ready dicts."""
    profile = (
        (await db.execute(select(Profile).where(Profile.user_id == user_id)))
        .scalars()
        .first()
    )
    insights = (
        (await db.execute(select(MatchInsight).where(MatchInsight.user_id == user_id)))
        .scalars()
        .all()
    )
    sessions = (
        (
            await db.execute(
                select(ChatSession)
                .where(ChatSession.user_id == user_id)
                .order_by(ChatSession.created_at)
            )
        )
        .scalars()
        .all()
    )
    documents = (
        (await db.execute(select(Document).where(Document.user_id == user_id)))
        .scalars()
        .all()
    )
    messages = (
        (
            await db.execute(
                select(ChatMessage).where(
                    ChatMessage.session_id.in_(
                        [s.id for s in sessions] or [uuid.uuid4()]
                    )
                )
            )
        )
        .scalars()
        .all()
    )
    data = {
        "profile": _row_dict(profile) if profile else None,
        "match_insights": [_row_dict(i) for i in insights],
        "chat_sessions": [
            {
                **_row_dict(s),
                "messages": [_row_dict(m) for m in messages if m.session_id == s.id],
            }
            for s in sessions
        ],
        "documents": [_row_dict(d) for d in documents],
    }
    return data, list(documents)


async def build_export(db: AsyncSession, user: User, job_id: uuid.UUID) -> Path:
    """Write the user's data as a zip; returns the archive path."""
    data, documents = await collect_user_data(db, user.id)

    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "app_version": settings.VERSION,
        "user_id": str(user.id),
        "email": user.email,
        "includes": [
            "profile",
            "match_insights",
            "chat_sessions",
            "documents",
        ],
        "excludes": "Catalog jobs, families, taxonomy and universities are "
        "shared instance data and are not part of a personal export.",
    }

    archive_path = export_dir() / f"career-assistant-export-{job_id}.zip"
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("manifest.json", json.dumps(manifest, indent=2))
        bundle.writestr(
            "profile.json", json.dumps(data["profile"], indent=2, default=str)
        )
        bundle.writestr(
            "match_insights.json",
            json.dumps(data["match_insights"], indent=2, default=str),
        )
        bundle.writestr(
            "chat_sessions.json",
            json.dumps(data["chat_sessions"], indent=2, default=str),
        )
        bundle.writestr(
            "documents.json", json.dumps(data["documents"], indent=2, default=str)
        )
        for document in documents:
            file_path = DocumentService.upload_file_path(document)
            if file_path is not None and file_path.is_file():
                bundle.write(file_path, arcname=f"documents/{file_path.name}")
    return archive_path


def cleanup_old_exports(max_age_days: int = 7) -> int:
    """Delete export archives older than the retention window."""
    cutoff = datetime.now(timezone.utc).timestamp() - max_age_days * 86400
    removed = 0
    for file_path in export_dir().glob("*.zip"):
        try:
            if file_path.stat().st_mtime < cutoff:
                file_path.unlink()
                removed += 1
        except OSError:
            logger.warning("Could not remove old export %s", file_path)
    return removed
