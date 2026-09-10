"""Metric service: registry access + per-user metric profile.

Values carry provenance like `user_skills` (source, confidence,
evidence). Interest affinities (RIASEC) are derived deterministically
from the user's interest tags' taxonomy categories; recomputes are
full-replace within the interest family so removed tags never leave
stale values behind.
"""

import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import ValidationError
from app.models.enums import UserMetricSource
from app.models.job_model import Job, JobSkill
from app.models.metric_model import (
    MetricDimension,
    SkillTransferability,
    UserMetricProfile,
)
from app.models.taxonomy_model import InterestTag, Skill
from app.models.user_model import UserInterest
from app.seeds.metrics import DIMENSIONS, riasec_of_category

INTEREST_DIMENSION_PREFIX = "interest."


class MetricService:
    """Registry reads + user-metric upserts and derivations."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def _ensure_dimensions(self, keys: list[str]) -> None:
        """Self-heal the registry from the canonical code spec.

        The dimension vocabulary is code-referenced (like the block-kind
        and context-source registries), so writes never fail just because
        `seed.sh` has not been re-run after an upgrade. Non-canonical
        keys create nothing — the caller's validation still rejects them.
        """
        if not keys:
            return
        rows = await self.db.execute(
            select(MetricDimension.key).where(MetricDimension.key.in_(keys))
        )
        known = set(rows.scalars().all())
        missing = [key for key in keys if key not in known]
        spec_by_key = {spec["key"]: spec for spec in DIMENSIONS}
        for key in missing:
            spec = spec_by_key.get(key)
            if spec is not None:
                self.db.add(MetricDimension(**spec))
        if missing:
            await self.db.commit()

    async def registry(self) -> list[MetricDimension]:
        """All dimension rows, stable order (group, key)."""
        rows = await self.db.execute(
            select(MetricDimension).order_by(
                MetricDimension.group.asc(), MetricDimension.key.asc()
            )
        )
        return list(rows.scalars().all())

    async def require_dimension(self, key: str) -> MetricDimension:
        row = (
            (
                await self.db.execute(
                    select(MetricDimension).where(MetricDimension.key == key)
                )
            )
            .scalars()
            .first()
        )
        if row is None:
            raise ValidationError(f"Unknown metric dimension: {key}")
        return row

    async def user_metrics(self, user_id: uuid.UUID) -> list[UserMetricProfile]:
        rows = await self.db.execute(
            select(UserMetricProfile)
            .where(UserMetricProfile.user_id == user_id)
            .order_by(UserMetricProfile.dimension_key.asc())
        )
        return list(rows.scalars().all())

    async def upsert_metric(
        self,
        user_id: uuid.UUID,
        key: str,
        value: float,
        *,
        source: UserMetricSource = UserMetricSource.SELF_REPORT,
        confidence: float = 0.6,
        evidence: dict | None = None,
    ) -> UserMetricProfile:
        """Upsert one dimension value (42.B unique user+dimension)."""
        await self._ensure_dimensions([key])
        await self.require_dimension(key)
        if not 1 <= float(value) <= 10:
            raise ValidationError(f"Metric value out of bounds for {key}: {value}")
        row = (
            (
                await self.db.execute(
                    select(UserMetricProfile).where(
                        UserMetricProfile.user_id == user_id,
                        UserMetricProfile.dimension_key == key,
                    )
                )
            )
            .scalars()
            .first()
        )
        if row is None:
            row = UserMetricProfile(user_id=user_id, dimension_key=key)
            self.db.add(row)
        row.value = round(float(value), 2)
        row.source = source.value
        row.confidence = confidence
        row.evidence = evidence or {}
        await self.db.commit()
        await self.db.refresh(row)
        return row

    async def interest_affinity(self, user_id: uuid.UUID) -> dict[str, float]:
        """RIASEC vector from interest tags' categories ({} without signal).

        Deterministic: each tag contributes its 1–5 weight to its
        category's letter; per-letter sums normalize against the strongest
        letter → 1 + 9 × (sum / max), so the profile shape survives
        interest-count changes.
        """
        rows = await self.db.execute(
            select(UserInterest)
            .options(selectinload(UserInterest.tag))
            .where(UserInterest.user_id == user_id)
        )
        sums: dict[str, float] = {}
        for row in rows.scalars().all():
            letter = riasec_of_category(row.tag.category if row.tag else None)
            if letter is None:
                continue
            sums[letter] = sums.get(letter, 0) + float(row.weight or 1)
        if not sums:
            return {}
        peak = max(sums.values())
        return {
            f"interest.{letter}": round(1 + 9 * (total / peak), 2)
            for letter, total in sorted(sums.items())
        }

    async def recompute_interest_affinity(self, user_id: uuid.UUID) -> int:
        """Full-replace the user's interest.* metric rows; returns the count."""
        from app.seeds.metrics import RIASEC_LETTERS

        await self._ensure_dimensions(
            [f"interest.{letter}" for letter in RIASEC_LETTERS]
        )
        await self.db.execute(
            delete(UserMetricProfile).where(
                UserMetricProfile.user_id == user_id,
                UserMetricProfile.dimension_key.like(f"{INTEREST_DIMENSION_PREFIX}%"),
            )
        )
        vector = await self.interest_affinity(user_id)
        for key, value in vector.items():
            self.db.add(
                UserMetricProfile(
                    user_id=user_id,
                    dimension_key=key,
                    value=round(value, 2),
                    source=UserMetricSource.SELF_REPORT.value,
                    confidence=0.6,
                    evidence={"basis": "profile.interests"},
                )
            )
        await self.db.commit()
        return len(vector)

    async def recompute_workstyle(
        self, user_id: uuid.UUID, work_preferences: dict
    ) -> int:
        """Write the 1–5 work-style sliders through as self_report evidence
        (: the sliders stay the capture UI, dimensions are the
        language). Full-replace within the workstyle family."""
        await self._ensure_dimensions([f"workstyle.{key}" for key in work_preferences])
        await self.db.execute(
            delete(UserMetricProfile).where(
                UserMetricProfile.user_id == user_id,
                UserMetricProfile.dimension_key.like("workstyle.%"),
            )
        )
        count = 0
        for key in ("teamwork", "environment", "structure", "pace", "leadership"):
            if key not in work_preferences:
                continue
            self.db.add(
                UserMetricProfile(
                    user_id=user_id,
                    dimension_key=f"workstyle.{key}",
                    value=round(float(work_preferences[key]) * 2, 2),
                    source=UserMetricSource.SELF_REPORT.value,
                    confidence=0.8,
                    evidence={"basis": "profile.work_preferences"},
                )
            )
            count += 1
        await self.db.commit()
        return count

    async def job_riasec_letters(self, job) -> set[str]:
        """Holland letters a job signals via its interest-tag links.

        `job.tag_links` must carry the loaded `tag` relationship
        (JOB_LOAD_OPTIONS), same contract as the fit engine's job_context.
        """
        letters: set[str] = set()
        for link in job.tag_links:
            letter = riasec_of_category(link.tag.category if link.tag else None)
            if letter is not None:
                letters.add(letter)
        return letters

    async def tag_categories(self, tag_ids: set[uuid.UUID]) -> set[str]:
        """Categories for a set of interest-tag ids (engine helper)."""
        if not tag_ids:
            return set()
        rows = await self.db.execute(
            select(InterestTag.category).where(InterestTag.id.in_(tag_ids))
        )
        return {category for (category,) in rows.all() if category}

    async def recompute_skill_transferability(self) -> int:
        """Rebuild the per-skill transferability stats from the join graph.

        Deterministic full-replace: denominator is the number of families
        containing at least one published job; a skill's `share` is the
        fraction of those families whose jobs ask for it.
        """
        total_families = len(
            (
                await self.db.execute(
                    select(Job.family_id).where(Job.status == "published").distinct()
                )
            ).all()
        )
        await self.db.execute(delete(SkillTransferability))
        count = 0
        if total_families:
            rows = await self.db.execute(
                select(
                    JobSkill.skill_id,
                    func.count(func.distinct(JobSkill.job_id)),
                    func.count(func.distinct(Job.family_id)),
                )
                .join(Job, Job.id == JobSkill.job_id)
                .where(Job.status == "published")
                .group_by(JobSkill.skill_id)
            )
            for skill_id, job_count, family_count in rows.all():
                self.db.add(
                    SkillTransferability(
                        skill_id=skill_id,
                        job_count=int(job_count),
                        family_count=int(family_count),
                        total_families=total_families,
                        share=round(family_count / total_families, 4),
                    )
                )
                count += 1
        await self.db.commit()
        return count

    async def transferability_rows(
        self, skill_key: str | None = None, limit: int = 100
    ) -> list[dict]:
        """Transferability stats joined with skill labels (share desc)."""
        query = (
            select(SkillTransferability, Skill)
            .join(Skill, Skill.id == SkillTransferability.skill_id)
            .order_by(
                SkillTransferability.share.desc(),
                SkillTransferability.family_count.desc(),
                Skill.key.asc(),
            )
            .limit(max(1, min(limit, 500)))
        )
        if skill_key:
            query = query.where(Skill.key == skill_key)
        rows = await self.db.execute(query)
        return [
            {
                "skill_key": skill.key,
                "skill_label": skill.label,
                "job_count": stat.job_count,
                "family_count": stat.family_count,
                "total_families": stat.total_families,
                "share": float(stat.share),
            }
            for stat, skill in rows.all()
        ]

    async def apply_revealed_preferences(self, user_id: uuid.UUID, *, now=None) -> dict:
        """Opt-in behavior drift for the RIASEC affinities.

        Engagement signals (seen/saved/applied from/26) build a
        target vector through each posting's catalog job's interest tags;
        existing ``interest.*`` rows move toward it by at most 0.5 per
        call. Never touches the exploration slot — that guard lives in
        the fit engine, untouched here.
        """
        from datetime import datetime, timedelta, timezone

        from app.models.job_model import JobTag
        from app.models.posting_model import JobPosting, PostingInteraction
        from app.models.user_model import Profile

        now = now or datetime.now(timezone.utc)
        profile = (
            (await self.db.execute(select(Profile).where(Profile.user_id == user_id)))
            .scalars()
            .first()
        )
        if profile is None or not revealed_prefs(profile.preferences)["enabled"]:
            return {"applied": False, "reason": "disabled"}

        window_start = now - timedelta(days=REVEALED_WINDOW_DAYS)
        interactions = (
            (
                await self.db.execute(
                    select(PostingInteraction).where(
                        PostingInteraction.user_id == user_id,
                        PostingInteraction.posting_id.is_not(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        posting_ids = [i.posting_id for i in interactions if i.posting_id]
        postings: dict[uuid.UUID, JobPosting] = {}
        if posting_ids:
            posting_rows = (
                (
                    await self.db.execute(
                        select(JobPosting)
                        .options(selectinload(JobPosting.catalog_job))
                        .where(JobPosting.id.in_(posting_ids))
                    )
                )
                .scalars()
                .all()
            )
            postings = {posting.id: posting for posting in posting_rows}
        letter_weights: dict[str, float] = {}
        samples = 0
        for interaction in interactions:
            weight = 0.0
            if interaction.seen_at and interaction.seen_at >= window_start:
                weight += _REVEALED_ENGAGEMENT_WEIGHTS["seen"]
            if interaction.saved_at and interaction.saved_at >= window_start:
                weight += _REVEALED_ENGAGEMENT_WEIGHTS["saved"]
            if interaction.applied_at and interaction.applied_at >= window_start:
                weight += _REVEALED_ENGAGEMENT_WEIGHTS["applied"]
            if weight <= 0:
                continue
            posting = postings.get(interaction.posting_id)
            job = posting.catalog_job if posting is not None else None
            if job is None:
                continue
            samples += 1
            tag_rows = await self.db.execute(
                select(InterestTag.category)
                .join(JobTag, JobTag.interest_tag_id == InterestTag.id)
                .where(JobTag.job_id == job.id)
            )
            for (category,) in tag_rows.all():
                letter = riasec_of_category(category)
                if letter is not None:
                    letter_weights[letter] = letter_weights.get(letter, 0.0) + weight
        if not letter_weights:
            return {"applied": False, "reason": "no_signals"}

        peak = max(letter_weights.values())
        target = {
            f"interest.{letter}": 1 + 9 * (weight / peak)
            for letter, weight in letter_weights.items()
        }
        existing = {
            row.dimension_key: row
            for row in (
                await self.db.execute(
                    select(UserMetricProfile).where(
                        UserMetricProfile.user_id == user_id,
                        UserMetricProfile.dimension_key.like(
                            f"{INTEREST_DIMENSION_PREFIX}%"
                        ),
                    )
                )
            )
            .scalars()
            .all()
        }
        from app.seeds.metrics import RIASEC_LETTERS

        await self._ensure_dimensions(
            [f"interest.{letter}" for letter in RIASEC_LETTERS]
        )
        moved: dict[str, float] = {}
        for key, target_value in target.items():
            row = existing.get(key)
            current = float(row.value) if row is not None else 5.5
            delta = max(
                -REVEALED_STEP_CAP, min(REVEALED_STEP_CAP, target_value - current)
            )
            if abs(delta) < 0.01:
                continue
            new_value = round(min(10.0, max(1.0, current + delta)), 2)
            await self.upsert_metric(
                user_id,
                key,
                new_value,
                source=UserMetricSource.BEHAVIOR,
                confidence=0.4,
                evidence={
                    "basis": "revealed_preferences",
                    "window_days": REVEALED_WINDOW_DAYS,
                    "samples": samples,
                },
            )
            moved[key] = new_value
        return {"applied": True, "samples": samples, "moved": moved}

    async def outcome_funnel(self, user_id: uuid.UUID) -> list[dict]:
        """Application funnel per catalog family — observation only
        : never read by scoring, no self-reinforcing loop."""
        from app.models.job_model import Job, JobFamily
        from app.models.posting_model import JobPosting, PostingInteraction

        rows = await self.db.execute(
            select(PostingInteraction, JobFamily.label)
            .join(JobPosting, JobPosting.id == PostingInteraction.posting_id)
            .join(Job, Job.id == JobPosting.catalog_job_id)
            .join(JobFamily, JobFamily.id == Job.family_id)
            .where(PostingInteraction.user_id == user_id)
        )
        families: dict[str, dict] = {}
        for interaction, family_label in rows.all():
            bucket = families.setdefault(
                family_label,
                {
                    "family": family_label,
                    "saved": 0,
                    "applied": 0,
                    "interview": 0,
                    "offer": 0,
                },
            )
            if interaction.saved_at is not None:
                bucket["saved"] += 1
            if interaction.applied_at is not None:
                bucket["applied"] += 1
            if interaction.stage == "interview":
                bucket["interview"] += 1
            elif interaction.stage == "offer":
                bucket["offer"] += 1
        results = []
        for bucket in families.values():
            applied = bucket["applied"]
            bucket["interview_rate"] = (
                round(bucket["interview"] / applied, 2) if applied else None
            )
            bucket["offer_rate"] = (
                round(bucket["offer"] / applied, 2) if applied else None
            )
            results.append(bucket)
        results.sort(key=lambda item: (-item["applied"], item["family"]))
        return results

    def engine_dimensions(self) -> list[dict]:
        """Both engines' dimension lists from their code-referenced specs
        (: registry-driven reads — one source, no per-UI
        hardcoding)."""
        from app.services.fit.dimensions import fit_dimension_spec
        from app.services.posting_fit_service import posting_fit_dimension_spec

        return [*fit_dimension_spec(), *posting_fit_dimension_spec()]


# ------------------------------------------------------------ residuals

REVEALED_WINDOW_DAYS = 28
REVEALED_STEP_CAP = 0.5  # ≤5% of the 1–10 scale per (weekly) call

_REVEALED_ENGAGEMENT_WEIGHTS = {"seen": 1.0, "saved": 3.0, "applied": 5.0}


def revealed_prefs(preferences: dict | None) -> dict:
    """Normalized revealed-preference settings — **off by default**."""
    raw = (preferences or {}).get("revealed_preferences") or {}
    return {
        "enabled": bool(raw.get("enabled", False)),
        "window_days": REVEALED_WINDOW_DAYS,
    }
