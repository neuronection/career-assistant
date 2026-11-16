"""STAR story library (plan 212 S1.7).

User-owned CRUD plus deterministic suggestions from the experience
items that are not already linked to a story. No AI, no auto-generation:
the suggestion prefills a title and a hint; the user writes the STAR.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import NotFoundError
from app.models.experience_model import ExperienceItem
from app.models.interview_model import InterviewStory
from app.schemas.interview import InterviewStoryIn, InterviewStoryPatch, StorySuggestionOut

STORIES_LIST_CAP = 200

MAX_SUGGESTIONS = 20


class StoryService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_stories(self, user_id: uuid.UUID) -> list[InterviewStory]:
        rows = await self.db.execute(
            select(InterviewStory)
            .where(InterviewStory.user_id == user_id)
            .order_by(InterviewStory.updated_at.desc())
            .limit(STORIES_LIST_CAP)
        )
        return list(rows.scalars().all())

    async def get_many(
        self, user_id: uuid.UUID, story_ids: list[uuid.UUID]
    ) -> list[InterviewStory]:
        if not story_ids:
            return []
        rows = await self.db.execute(
            select(InterviewStory).where(
                InterviewStory.user_id == user_id,
                InterviewStory.id.in_(story_ids),
            )
        )
        by_id = {row.id: row for row in rows.scalars().all()}
        return [by_id[story_id] for story_id in story_ids if story_id in by_id]

    async def _validate_experience(
        self, user_id: uuid.UUID, experience_item_id: uuid.UUID | None
    ) -> None:
        if experience_item_id is None:
            return
        item = await self.db.get(ExperienceItem, experience_item_id)
        if item is None or item.user_id != user_id:
            raise NotFoundError("Experience item not found")

    async def create(self, user_id: uuid.UUID, payload: InterviewStoryIn) -> InterviewStory:
        await self._validate_experience(user_id, payload.experience_item_id)
        row = InterviewStory(user_id=user_id, **payload.model_dump())
        self.db.add(row)
        await self.db.commit()
        await self.db.refresh(row)
        return row

    async def update(
        self, user_id: uuid.UUID, story_id: uuid.UUID, patch: InterviewStoryPatch
    ) -> InterviewStory:
        row = await self._owned(user_id, story_id)
        data = patch.model_dump(exclude_unset=True)
        if "experience_item_id" in data:
            await self._validate_experience(user_id, data["experience_item_id"])
        for field, value in data.items():
            setattr(row, field, value)
        await self.db.commit()
        await self.db.refresh(row)
        return row

    async def delete(self, user_id: uuid.UUID, story_id: uuid.UUID) -> None:
        await self.db.delete(await self._owned(user_id, story_id))
        await self.db.commit()

    async def suggestions(self, user_id: uuid.UUID) -> list[StorySuggestionOut]:
        linked = select(InterviewStory.experience_item_id).where(
            InterviewStory.user_id == user_id,
            InterviewStory.experience_item_id.is_not(None),
        )
        rows = await self.db.execute(
            select(ExperienceItem)
            .where(
                ExperienceItem.user_id == user_id,
                ExperienceItem.status == "active",
                ExperienceItem.id.not_in(linked),
            )
            .order_by(ExperienceItem.updated_at.desc())
            .options(selectinload(ExperienceItem.achievements))
            .limit(MAX_SUGGESTIONS)
        )
        suggestions: list[StorySuggestionOut] = []
        for item in rows.scalars().all():
            achievements = [str(row.text) for row in (item.achievements or []) if row.text]
            hint = " ".join(
                (achievements[0] if achievements else str(item.description or "")).split()
            )[:180]
            suggestions.append(
                StorySuggestionOut(
                    experience_item_id=item.id,
                    title=item.title,
                    org=item.org_name or "",
                    hint=hint,
                )
            )
        return suggestions

    async def _owned(self, user_id: uuid.UUID, story_id: uuid.UUID) -> InterviewStory:
        row = (
            (
                await self.db.execute(
                    select(InterviewStory).where(
                        InterviewStory.id == story_id,
                        InterviewStory.user_id == user_id,
                    )
                )
            )
            .scalars()
            .first()
        )
        if row is None:
            raise NotFoundError("Story not found")
        return row
