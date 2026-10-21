"""Seed the fictional posting the cover-letter spec drives.

Postings enter the product through connector syncs, which are out of scope
for a browser smoke run — the scratch e2e database therefore ships one
deterministic posting so posting-grounded surfaces (posting detail, cover
letters) are reachable. Idempotent; run by `scripts/run-e2e.sh` after the
catalog seed.
"""

import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.core.database import AsyncSessionLocal, engine
from app.models.posting_model import JobPosting, JobSource

SOURCE_KEY = "e2e-postings"
POSTING_REF = "E2E00001"


async def seed() -> None:
    async with AsyncSessionLocal() as db:
        source = (
            (await db.execute(select(JobSource).where(JobSource.key == SOURCE_KEY)))
            .scalars()
            .first()
        )
        if source is None:
            source = JobSource(
                key=SOURCE_KEY,
                connector_key="csv",
                config={"url": "https://example.invalid/e2e.csv"},
                sync_state={},
                enabled=False,
            )
            db.add(source)
            await db.flush()
        posting = (
            (await db.execute(select(JobPosting).where(JobPosting.ref == POSTING_REF)))
            .scalars()
            .first()
        )
        if posting is None:
            db.add(
                JobPosting(
                    source_id=source.id,
                    external_id=POSTING_REF,
                    ref=POSTING_REF,
                    title="Junior DevOps Engineer",
                    org="E2E Labs",
                    location={"city": "Berlin", "country": "DE", "remote": True},
                    url="https://example.invalid/jobs/e2e-0001",
                    posted_at=datetime.now(UTC) - timedelta(days=1),
                    content_hash="e2e-posting-0001",
                    raw={"title": "Junior DevOps Engineer", "org": "E2E Labs"},
                )
            )
        await db.commit()
        print(f"e2e posting ready: {POSTING_REF}")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
