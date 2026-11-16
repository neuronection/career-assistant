"""STAR story library endpoints (plan 212 S1.7)."""

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.interview import (
    InterviewStoryIn,
    InterviewStoryOut,
    InterviewStoryPatch,
    StorySuggestionOut,
)
from app.services.chat.story_service import StoryService
from app.services.deps import get_current_user

router = APIRouter(prefix="/me/interview/stories", tags=["interview-stories"])


@router.get("", response_model=list[InterviewStoryOut])
async def list_stories(user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await StoryService(db).list_stories(user.id)


@router.get("/suggestions", response_model=list[StorySuggestionOut])
async def story_suggestions(user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await StoryService(db).suggestions(user.id)


@router.post("", response_model=InterviewStoryOut, status_code=status.HTTP_201_CREATED)
async def create_story(
    payload: InterviewStoryIn,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await StoryService(db).create(user.id, payload)


@router.patch("/{story_id}", response_model=InterviewStoryOut)
async def update_story(
    story_id: uuid.UUID,
    payload: InterviewStoryPatch,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await StoryService(db).update(user.id, story_id, payload)


@router.delete("/{story_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_story(
    story_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await StoryService(db).delete(user.id, story_id)
