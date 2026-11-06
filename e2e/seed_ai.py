"""Seed the e2e mock AI carrier.

The first-run gate (plan 118) redirects an unconfigured instance to
`/onboarding/setup`, so the smoke suite boots with the mock provider
already configured — the very carrier `ensure_dev_bootstrap` would create
on the first AI call, seeded up front and idempotently. The first-run spec
deliberately unconfigures the instance and reconnects through the wizard.
"""

import asyncio

from app.ai.providers.resolution import ensure_dev_bootstrap
from app.core.database import AsyncSessionLocal


async def seed() -> None:
    async with AsyncSessionLocal() as db:
        await ensure_dev_bootstrap(db)


if __name__ == "__main__":
    asyncio.run(seed())
