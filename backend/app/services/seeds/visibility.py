"""User visibility overlays for the provider catalog (plan 218 §3.12).

Two user-scoped mechanisms narrow what a person sees:
``source_prefs.hidden`` is a hard deny (it wins over every other filter), and
``provider_subscriptions.mode='selected'`` narrows the visible source set to
the selected providers (plus sources with no provider, e.g. manual/extension
sources). A missing user means the instance default: nothing hidden and no
provider narrowing. Background jobs carry their owner's user id.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.posting_model import JobSource
from app.models.seed_model import ProviderSubscription, SourcePref


@dataclass(frozen=True)
class Visibility:
    hidden_source_ids: frozenset[uuid.UUID] = field(default_factory=frozenset)
    allowed_source_ids: frozenset[uuid.UUID] | None = None

    def posting_conditions(self) -> list:
        from app.models.posting_model import JobPosting

        conditions: list = []
        if self.hidden_source_ids:
            conditions.append(JobPosting.source_id.not_in(sorted(self.hidden_source_ids)))
        if self.allowed_source_ids is not None:
            conditions.append(JobPosting.source_id.in_(sorted(self.allowed_source_ids)))
        return conditions


async def load_visibility(db: AsyncSession, user_id: uuid.UUID | None) -> Visibility:
    """Resolve one user's hidden sources and provider allowlist."""
    if user_id is None:
        return Visibility()
    hidden = (
        (
            await db.execute(
                select(SourcePref.job_source_id).where(
                    SourcePref.user_id == user_id,
                    SourcePref.hidden.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )
    subscriptions = (
        await db.execute(
            select(ProviderSubscription.seed_source_id, ProviderSubscription.mode).where(
                ProviderSubscription.user_id == user_id,
                ProviderSubscription.enabled.is_(True),
            )
        )
    ).all()
    allowed: frozenset[uuid.UUID] | None = None
    if subscriptions and all(mode == "selected" for _provider, mode in subscriptions):
        provider_ids = [provider for provider, _mode in subscriptions]
        source_ids = (
            (
                await db.execute(
                    select(JobSource.id).where(
                        or_(
                            JobSource.seed_source_id.in_(provider_ids),
                            JobSource.seed_source_id.is_(None),
                        )
                    )
                )
            )
            .scalars()
            .all()
        )
        allowed = frozenset(source_ids)
    return Visibility(hidden_source_ids=frozenset(hidden), allowed_source_ids=allowed)


__all__ = ["Visibility", "load_visibility"]
