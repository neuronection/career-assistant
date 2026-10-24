"""Account-level operations: data export enqueue.

Account deletion is the auth-kit's §12 surface now
(`DELETE /api/v1/me` — password-confirmed cascade delete).
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_model import User
from app.services.job_worker import enqueue


async def request_export(db: AsyncSession, user: User) -> uuid.UUID:
    """Queue a data_export background job; returns the job id."""
    job = await enqueue(db, "data_export", {}, user_id=user.id, max_attempts=1)
    return job.id
