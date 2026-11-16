"""Reusable screening answers (plan 212 S1.5).

Flat user-owned CRUD; the kit is the only reader. A save is explicit —
there is no AI generation here and no auto-fill of an application form.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.models.profile_entities_model import SavedAnswer
from app.schemas.profile_answers import SavedAnswerIn, SavedAnswerPatch

ANSWERS_LIST_CAP = 200


class SavedAnswerService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list(self, user_id: uuid.UUID) -> list[SavedAnswer]:
        rows = await self.db.execute(
            select(SavedAnswer)
            .where(SavedAnswer.user_id == user_id)
            .order_by(SavedAnswer.question_key)
            .limit(ANSWERS_LIST_CAP)
        )
        return list(rows.scalars().all())

    async def upsert(self, user_id: uuid.UUID, payload: SavedAnswerIn) -> SavedAnswer:
        row = (
            (
                await self.db.execute(
                    select(SavedAnswer).where(
                        SavedAnswer.user_id == user_id,
                        SavedAnswer.question_key == payload.question_key,
                    )
                )
            )
            .scalars()
            .first()
        )
        if row is None:
            row = SavedAnswer(user_id=user_id, question_key=payload.question_key)
            self.db.add(row)
        row.question_text = payload.question_text
        row.answer_text = payload.answer_text
        row.evidence_refs = payload.evidence_refs
        await self.db.commit()
        await self.db.refresh(row)
        return row

    async def update(
        self, user_id: uuid.UUID, answer_id: uuid.UUID, patch: SavedAnswerPatch
    ) -> SavedAnswer:
        row = await self._owned(user_id, answer_id)
        data = patch.model_dump(exclude_unset=True)
        for field, value in data.items():
            setattr(row, field, value)
        await self.db.commit()
        await self.db.refresh(row)
        return row

    async def delete(self, user_id: uuid.UUID, answer_id: uuid.UUID) -> None:
        await self.db.delete(await self._owned(user_id, answer_id))
        await self.db.commit()

    async def _owned(self, user_id: uuid.UUID, answer_id: uuid.UUID) -> SavedAnswer:
        row = (
            (
                await self.db.execute(
                    select(SavedAnswer).where(
                        SavedAnswer.id == answer_id,
                        SavedAnswer.user_id == user_id,
                    )
                )
            )
            .scalars()
            .first()
        )
        if row is None:
            raise NotFoundError("Saved answer not found")
        return row
