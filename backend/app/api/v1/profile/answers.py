"""Saved screening answers (plan 212 S1.5)."""

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.profile_answers import SavedAnswerIn, SavedAnswerOut, SavedAnswerPatch
from app.services.deps import get_current_user
from app.services.profile.answers_service import SavedAnswerService

router = APIRouter(prefix="/me/answers", tags=["answers"])


@router.get("", response_model=list[SavedAnswerOut])
async def list_answers(user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await SavedAnswerService(db).list(user.id)


@router.post("", response_model=SavedAnswerOut, status_code=status.HTTP_201_CREATED)
async def upsert_answer(
    payload: SavedAnswerIn,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await SavedAnswerService(db).upsert(user.id, payload)


@router.patch("/{answer_id}", response_model=SavedAnswerOut)
async def update_answer(
    answer_id: uuid.UUID,
    payload: SavedAnswerPatch,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await SavedAnswerService(db).update(user.id, answer_id, payload)


@router.delete("/{answer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_answer(
    answer_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await SavedAnswerService(db).delete(user.id, answer_id)
