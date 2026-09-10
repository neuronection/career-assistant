import re
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.gateway import transcribe_audio
from app.ai.transcribe import TranscriptionUnsupported
from app.core.database import get_db
from app.core.errors import AINotConfiguredError, DomainError
from app.services.deps import get_current_user

router = APIRouter(tags=["ai"])

_LANGUAGE_RE = re.compile(r"^[a-zA-Z]{2,3}(-[a-zA-Z0-9]{2,8})*$")
MAX_AUDIO_BYTES = 25 * 1024 * 1024


class TranscribeOut(BaseModel):
    text: str
    model: str


@router.get("/ai/skill-packs", response_model=list[dict])
async def list_skill_packs(
    user=Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[dict]:
    """Published bank skill packs: task-steering
    instruction packs, versioned and audited per call."""
    from sqlalchemy import select

    from app.models.skill_pack_model import AISkillPack

    rows = await db.execute(
        select(AISkillPack)
        .where(
            AISkillPack.status == "published",
            AISkillPack.author_key == "bank",
        )
        .order_by(AISkillPack.task, AISkillPack.version.desc())
    )
    return [
        {
            "key": pack.key,
            "version": pack.version,
            "title": pack.title,
            "task": pack.task,
            "instructions": pack.instructions,
        }
        for pack in rows.scalars().all()
    ]


@router.post("/ai/transcribe", response_model=TranscribeOut)
async def transcribe(
    file: Annotated[UploadFile, File()],
    language: Annotated[Optional[str], Form()] = None,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TranscribeOut:
    """Dictation speech-to-text through the transcribe task."""
    if language is not None:
        language = language.strip() or None
        if language is not None and not _LANGUAGE_RE.match(language):
            raise HTTPException(
                status_code=422,
                detail="language must be an ISO language code like 'en' or 'de'",
            )
    mime = (file.content_type or "").split(";")[0].strip().lower()
    if not mime.startswith("audio/") and mime != "video/webm":
        raise HTTPException(status_code=422, detail="file must be an audio recording")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=422, detail="audio file is empty")
    if len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="audio file too large (max 25 MB)")
    try:
        text, model = await transcribe_audio(
            db, user_id=user.id, data=data, mime=mime, language=language
        )
    except AINotConfiguredError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except TranscriptionUnsupported as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except DomainError as exc:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(exc)) from exc
    return TranscribeOut(text=text, model=model)
