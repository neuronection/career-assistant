"""Account-level operations: data export enqueue + full account deletion."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationError
from app.core.security import verify_password
from app.models.user_model import User
from app.services.document_service import DocumentService
from app.services.job_worker import enqueue


async def request_export(db: AsyncSession, user: User) -> uuid.UUID:
    """Queue a data_export background job; returns the job id."""
    job = await enqueue(db, "data_export", {}, user_id=user.id, max_attempts=1)
    return job.id


async def delete_account(db: AsyncSession, user: User, password: str) -> None:
    """Delete the caller's account and all personal data (cascade + files).

    The last admin of a multi-user instance cannot self-delete: there would be
    no admin left to configure the instance.
    """
    if not verify_password(password, user.password_hash):
        raise ValidationError("Password confirmation failed")

    if user.is_admin:
        user_count = (await db.execute(select(func.count(User.id)))).scalar() or 0
        admin_count = (
            await db.execute(select(func.count(User.id)).where(User.is_admin.is_(True)))
        ).scalar() or 0
        if user_count > 1 and admin_count <= 1:
            raise ValidationError(
                "The last admin cannot delete their account while other users "
                "exist. Promote another admin first."
            )

    # Remove uploaded files before the rows disappear with the user.
    from app.models.document_model import Document

    documents = (
        (await db.execute(select(Document).where(Document.user_id == user.id)))
        .scalars()
        .all()
    )
    for document in documents:
        file_path = DocumentService.upload_file_path(document)
        if file_path is not None and file_path.is_file():
            try:
                file_path.unlink()
            except OSError:
                pass

    # DB-level ON DELETE CASCADE removes profile, insights, chats, documents,
    # user-scoped AI config and background jobs (FK pragma on SQLite).
    await db.delete(user)
    await db.commit()
