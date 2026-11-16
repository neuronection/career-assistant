"""User data export: everything a user owns, packaged as a versioned zip.

The archive is an object (`tenants/<user>/exports/<job-id>.zip`) in every
deployment shape; the download route streams it. Pre-contract rows that
still carry a local `export_path` keep working through the legacy branch in
the download route.
"""

import json
import logging
import tempfile
import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.application_model import Application, ApplicationEvent
from app.models.chat_model import ChatMessage, ChatSession
from app.models.contact_model import Contact, ContactInteraction
from app.models.cv_synth_model import CvSynthItem
from app.models.document_model import Document
from app.models.matching_model import MatchInsight
from app.models.user_model import Profile, User
from app.services.profile.document_storage import document_storage
from app.storage.object_storage import ObjectTooLarge, StorageError

logger = logging.getLogger(__name__)

MANIFEST_SCHEMA_VERSION = 1
EXPORT_FILENAME = "career-assistant-export-{job_id}.zip"


def _row_dict(row) -> dict:
    """Serialize a model row with JSON-safe primitives."""
    return {column.name: _jsonable(getattr(row, column.name)) for column in row.__table__.columns}


def _jsonable(value):
    if isinstance(value, (datetime,)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


def export_dir() -> Path:
    """Legacy local export directory (pre-contract archives only)."""
    path = Path(settings.upload_root) / "exports"
    path.mkdir(parents=True, exist_ok=True)
    return path


async def collect_user_data(db: AsyncSession, user_id: uuid.UUID) -> tuple[dict, list[Document]]:
    """Gather every user-owned entity as plain JSON-ready dicts."""
    profile = (
        (await db.execute(select(Profile).where(Profile.user_id == user_id))).scalars().first()
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
        (await db.execute(select(Document).where(Document.user_id == user_id))).scalars().all()
    )
    messages = (
        (
            await db.execute(
                select(ChatMessage).where(
                    ChatMessage.session_id.in_([s.id for s in sessions] or [uuid.uuid4()])
                )
            )
        )
        .scalars()
        .all()
    )
    synth_rows = (
        (
            await db.execute(
                select(CvSynthItem)
                .where(CvSynthItem.user_id == user_id)
                .order_by(CvSynthItem.created_at)
            )
        )
        .scalars()
        .all()
    )
    applications = (
        (await db.execute(select(Application).where(Application.user_id == user_id)))
        .scalars()
        .all()
    )
    application_events = (
        (
            await db.execute(
                select(ApplicationEvent)
                .join(Application, Application.id == ApplicationEvent.application_id)
                .where(Application.user_id == user_id)
                .order_by(ApplicationEvent.at)
            )
        )
        .scalars()
        .all()
    )
    contacts = (await db.execute(select(Contact).where(Contact.user_id == user_id))).scalars().all()
    contact_interactions = (
        (
            await db.execute(
                select(ContactInteraction)
                .join(Contact, Contact.id == ContactInteraction.contact_id)
                .where(Contact.user_id == user_id)
                .order_by(ContactInteraction.at)
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
        "cv_synth_items": [_row_dict(r) for r in synth_rows],
        "applications": [_row_dict(row) for row in applications],
        "application_events": [_row_dict(row) for row in application_events],
        "contacts": [_row_dict(row) for row in contacts],
        "contact_interactions": [_row_dict(row) for row in contact_interactions],
    }
    return data, list(documents)


async def build_export(db: AsyncSession, user: User, job_id: uuid.UUID) -> str:
    """Build the user's data zip and store it; returns the object key."""
    data, documents = await collect_user_data(db, user.id)

    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "exported_at": datetime.now(UTC).isoformat(),
        "app_version": settings.version,
        "user_id": str(user.id),
        "email": user.email,
        "includes": [
            "profile",
            "match_insights",
            "chat_sessions",
            "documents",
            "cv_synth_items",
            "applications",
            "application_events",
            "contacts",
            "contact_interactions",
        ],
        "excludes": "Catalog jobs, families, taxonomy and universities are "
        "shared instance data and are not part of a personal export.",
    }

    storage = document_storage()
    # Exports are bounded by their own ceiling, not the per-upload cap: one
    # archive bundles every document the user owns. Spool it too—small
    # exports stay in RAM, large ones land in a temp file, and the cap is
    # checked before the bytes are handed to the store.
    cap = settings.export_max_mb * 1024 * 1024
    over_cap = (
        f"export exceeds CAREER_EXPORT_MAX_MB={settings.export_max_mb} ({cap} bytes); "
        "raise the export ceiling or split the account data"
    )
    with tempfile.SpooledTemporaryFile(max_size=min(cap, 8 * 1024 * 1024), mode="w+b") as buffer:
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as bundle:
            bundle.writestr("manifest.json", json.dumps(manifest, indent=2))
            bundle.writestr("profile.json", json.dumps(data["profile"], indent=2, default=str))
            bundle.writestr(
                "match_insights.json",
                json.dumps(data["match_insights"], indent=2, default=str),
            )
            bundle.writestr(
                "chat_sessions.json",
                json.dumps(data["chat_sessions"], indent=2, default=str),
            )
            bundle.writestr(
                "cv_synth_items.json",
                json.dumps(data["cv_synth_items"], indent=2, default=str),
            )
            bundle.writestr("documents.json", json.dumps(data["documents"], indent=2, default=str))
            for document in documents:
                raw = await storage.aread(document)
                if raw is None:
                    continue
                extension = Path(document.filename).suffix or ".bin"
                bundle.writestr(f"documents/{document.id}{extension}", raw)
                if buffer.tell() > cap:
                    raise ObjectTooLarge(over_cap)
        size = buffer.tell()
        if size > cap:
            raise ObjectTooLarge(over_cap)
        buffer.seek(0)
        archive = buffer.read()
    return await storage.aput_export(user.id, job_id, archive)


async def cleanup_old_exports(max_age_days: int = 7) -> int:
    """Delete export archives older than the retention window (store + legacy)."""
    storage = document_storage()
    try:
        removed = await storage.apurge_exports(max_age_days)
    except (StorageError, OSError):
        # A transient provider list failure (or an unreadable local export
        # tree) must never stop worker startup; the next boot retries and
        # provider lifecycle is the backstop.
        logger.warning("Could not purge stored exports", exc_info=True)
        removed = 0
    if not storage.is_local:
        return removed
    cutoff = datetime.now(UTC).timestamp() - max_age_days * 86400
    for file_path in export_dir().glob("*.zip"):
        try:
            if file_path.stat().st_mtime < cutoff:
                file_path.unlink()
                removed += 1
        except OSError:
            logger.warning("Could not remove old export %s", file_path)
    return removed
