"""Process-cached metric registry: dimension vocabulary and category anchors.

The metric vocabulary is reference data delivered by the seed-pack lane. The
registry caches the published dimension rows and the published category →
Holland-letter anchors for the life of the process; a pack apply invalidates
it and the test kit resets it per test. A process serves one instance (web
uvicorn worker or the desktop shell), so in-process invalidation is enough.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.metric_model import MetricCategoryAnchor, MetricDimension

PUBLISHED = "published"


@dataclass(frozen=True)
class MetricDimensionSpec:
    """One published dimension, detached from its session."""

    key: str
    label: str
    group: str
    description: str
    scale: str
    reverse_score: bool
    sources: tuple[str, ...]
    consumers: tuple[str, ...]


@dataclass(frozen=True)
class MetricRegistrySnapshot:
    """Published dimensions plus the category → Holland-letter anchors."""

    dimensions: tuple[MetricDimensionSpec, ...]
    anchors: Mapping[str, str]

    @property
    def available(self) -> bool:
        """True once the bank has published at least one dimension."""
        return bool(self.dimensions)

    @property
    def dimension_keys(self) -> frozenset[str]:
        """Every published dimension key."""
        return frozenset(dimension.key for dimension in self.dimensions)

    def dimension(self, key: str) -> MetricDimensionSpec | None:
        """One published dimension by key (None when not in the bank)."""
        return next((dimension for dimension in self.dimensions if dimension.key == key), None)

    def letter_for(self, category: str | None) -> str | None:
        """The Holland letter anchored to an interest category, if any."""
        if not category:
            return None
        return self.anchors.get(str(category).strip())


class MetricRegistry:
    """Async cache over the published metric bank."""

    def __init__(self) -> None:
        self._snapshot: MetricRegistrySnapshot | None = None

    async def snapshot(self, db: AsyncSession) -> MetricRegistrySnapshot:
        """The cached registry, loaded on first read."""
        if self._snapshot is None:
            await self.reload(db)
        snapshot = self._snapshot
        assert snapshot is not None
        return snapshot

    async def reload(self, db: AsyncSession) -> MetricRegistrySnapshot:
        """Re-read the published bank from the database."""
        dimensions = (
            (
                await db.execute(
                    select(MetricDimension)
                    .where(MetricDimension.status == PUBLISHED)
                    .order_by(MetricDimension.group.asc(), MetricDimension.key.asc())
                )
            )
            .scalars()
            .all()
        )
        anchors = (
            await db.execute(
                select(MetricCategoryAnchor.category, MetricCategoryAnchor.letter).where(
                    MetricCategoryAnchor.status == PUBLISHED
                )
            )
        ).all()
        self._snapshot = MetricRegistrySnapshot(
            dimensions=tuple(
                MetricDimensionSpec(
                    key=row.key,
                    label=row.label,
                    group=row.group,
                    description=row.description,
                    scale=row.scale,
                    reverse_score=bool(row.reverse_score),
                    sources=tuple(str(value) for value in (row.sources or [])),
                    consumers=tuple(str(value) for value in (row.consumers or [])),
                )
                for row in dimensions
            ),
            anchors={str(category): str(letter) for category, letter in anchors},
        )
        return self._snapshot

    def invalidate(self) -> None:
        """Drop the cached snapshot (next read reloads from the database)."""
        self._snapshot = None


metric_registry = MetricRegistry()


def reset_metric_registry() -> None:
    """Test-kit hook: a previous test's snapshot must never leak."""
    metric_registry.invalidate()


__all__ = [
    "PUBLISHED",
    "MetricDimensionSpec",
    "MetricRegistry",
    "MetricRegistrySnapshot",
    "metric_registry",
    "reset_metric_registry",
]
