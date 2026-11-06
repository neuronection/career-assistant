"""Duplicate catalog job-type merge/retire (plan 202 AD9).

Mirrors ``TaxonomyService.merge``'s retire-not-delete shape: every
dependent row is repointed or field-merged by explicit rules, the source
row stays with ``status=retired`` and ``ai_metadata.retired_into``, and one
``admin.job_type.merge`` audit event is the trail (a zero-posting source
still leaves one).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import attributes, selectinload

from app.models.career_path_model import CareerPath
from app.models.enums import JobStatus
from app.models.growth_model import GrowthPlan
from app.models.job_model import Job, JobRelation, JobSkill, JobTag
from app.models.market_model import MarketSnapshot
from app.models.matching_model import MatchInsight
from app.models.posting_model import JobPosting
from app.models.university_model import JobDepartmentLink
from app.services.catalog.job_audit import record_job_audit
from app.services.postings.change_journal import (
    RETAG_FIELDS,
    PostingChangeJournal,
    snapshot,
)
from app.services.postings.job_proposal_service import JobTypeNotPublishedError
from app.services.postings.job_type_text import normalize_job_type_title

IMPORTANCE_RANK = {"core": 3, "important": 2, "bonus": 1}


class JobTypeMergeError(Exception):
    code = "merge_refused"
    status_code = 409


class JobTypeMergeService:
    """Merge one published duplicate job type into a survivor."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def duplicate_groups(self) -> list[dict]:
        """Published types sharing a normalized title, with posting counts."""
        rows = (
            (
                await self.db.execute(
                    select(Job)
                    .options(selectinload(Job.family))
                    .where(Job.status == JobStatus.PUBLISHED.value)
                    .order_by(Job.title, Job.code)
                )
            )
            .scalars()
            .all()
        )
        groups: dict[str, list[Job]] = {}
        for job in rows:
            groups.setdefault(normalize_job_type_title(job.title), []).append(job)
        counts = {}
        if rows:
            from sqlalchemy import func

            count_rows = await self.db.execute(
                select(JobPosting.catalog_job_id, func.count(JobPosting.id)).group_by(
                    JobPosting.catalog_job_id
                )
            )
            counts = {job_id: int(count) for job_id, count in count_rows if job_id}
        out: list[dict] = []
        for normalized, jobs in groups.items():
            if len(jobs) < 2:
                continue
            out.append(
                {
                    "normalized_title": normalized,
                    "jobs": [
                        {
                            "id": str(job.id),
                            "code": job.code,
                            "title": job.title,
                            "family_key": job.family.key if job.family else "",
                            "created_at": job.created_at.isoformat() if job.created_at else None,
                            "posting_count": counts.get(job.id, 0),
                        }
                        for job in jobs
                    ],
                }
            )
        out.sort(key=lambda group: group["normalized_title"])
        return out

    async def merge(self, duplicate_id: uuid.UUID, target_id: uuid.UUID, *, actor) -> dict:
        source = (
            (await self.db.execute(select(Job).where(Job.id == duplicate_id))).scalars().first()
        )
        target = (await self.db.execute(select(Job).where(Job.id == target_id))).scalars().first()
        if source is None or target is None:
            raise LookupError("Job type not found")
        if source.id == target.id:
            raise JobTypeMergeError("Cannot merge a job type into itself")
        if source.status == JobStatus.RETIRED.value:
            raise JobTypeNotPublishedError(
                "The source job type is already retired",
                payload={"job_code": source.code, "title": source.title, "status": source.status},
            )
        if source.status != JobStatus.PUBLISHED.value or target.status != JobStatus.PUBLISHED.value:
            raise JobTypeNotPublishedError(
                "Both job types must be published",
                payload={"job_code": source.code, "title": source.title, "status": source.status},
            )
        if normalize_job_type_title(source.title) != normalize_job_type_title(target.title):
            raise JobTypeMergeError("Only exact normalized duplicate titles can be merged")

        report: dict[str, Any] = {
            "postings": 0,
            "remap_queued": 0,
            "skills": 0,
            "tags": 0,
            "relations": 0,
            "departments": 0,
            "match_insights": 0,
            "career_paths": 0,
            "growth_plans": 0,
            "snapshots": 0,
        }
        posting_ids: list[uuid.UUID] = []
        postings = (
            (
                await self.db.execute(
                    select(JobPosting).where(JobPosting.catalog_job_id == source.id)
                )
            )
            .scalars()
            .all()
        )
        for posting in postings:
            before = snapshot(posting, RETAG_FIELDS)
            previous_method = posting.mapping_method
            posting.catalog_job_id = target.id
            posting.mapping_method = None
            posting.mapping_confidence = 0.0
            posting.mapping_reason = "re-deciding after job-type merge"
            posting.status = "new" if posting.status == "mapped" else posting.status
            PostingChangeJournal.record(
                self.db,
                posting.id,
                "manual",
                actor_ref={"user_id": str(actor.id)} if actor is not None else None,
                operation={
                    "job_type_merge": {
                        "source": source.code,
                        "target": target.code,
                        "previous_mapping_method": previous_method,
                    }
                },
                before=before,
                after=snapshot(posting, RETAG_FIELDS),
            )
            posting_ids.append(posting.id)
            report["postings"] += 1

        await self.db.flush()
        report["skills"] = await self._merge_skills(source, target)
        report["tags"] = await self._merge_tags(source, target)
        report["departments"] = await self._merge_departments(source, target)
        report["relations"] = await self._merge_relations(source, target)
        report["match_insights"] = await self._merge_match_insights(source, target)
        report["career_paths"] = await self._repoint_career_paths(source, target)
        report["growth_plans"] = await self._repoint_growth_plans(source, target)
        report["snapshots"] = await self._merge_snapshots(source, target)

        source.status = JobStatus.RETIRED.value
        metadata = dict(source.ai_metadata or {})
        metadata.update(
            {
                "retired_into": target.code,
                "retired_into_title": target.title,
                "retired_at": datetime.now(UTC).isoformat(),
                "retired_reason": "duplicate job type",
            }
        )
        source.ai_metadata = metadata
        attributes.flag_modified(source, "ai_metadata")

        event = record_job_audit(
            self.db,
            actor=str(actor.id) if actor is not None else "system",
            action="admin.job_type.merge",
            resource=(
                f"job:{source.code};target={target.code};postings={report['postings']};"
                f"skills={report['skills']};relations={report['relations']}"
            ),
        )
        await self.db.flush()
        report["audit_event"] = str(event.id)
        await self.db.commit()

        from app.services.catalog.job_service import enqueue_job_index
        from app.services.postings.mapping_remap import enqueue_semantic_redecision

        for posting_id in posting_ids:
            job = await enqueue_semantic_redecision(self.db, posting_id)
            if job is not None:
                report["remap_queued"] += 1
        await enqueue_job_index(self.db, target)
        return report

    async def _merge_skills(self, source: Job, target: Job) -> int:
        target_links = {
            link.skill_id: link
            for link in (
                (await self.db.execute(select(JobSkill).where(JobSkill.job_id == target.id)))
                .scalars()
                .all()
            )
        }
        merged = 0
        source_links = (
            (await self.db.execute(select(JobSkill).where(JobSkill.job_id == source.id)))
            .scalars()
            .all()
        )
        for link in source_links:
            counterpart = target_links.get(link.skill_id)
            if counterpart is None:
                link.job_id = target.id
                target_links[link.skill_id] = link
                merged += 1
                continue
            source_rank = (IMPORTANCE_RANK.get(link.importance, 0), link.required_level)
            target_rank = (
                IMPORTANCE_RANK.get(counterpart.importance, 0),
                counterpart.required_level,
            )
            if source_rank > target_rank:
                counterpart.importance = link.importance
                counterpart.required_level = link.required_level
            if not counterpart.rationale:
                counterpart.rationale = link.rationale
            await self.db.delete(link)
            merged += 1
        return merged

    async def _merge_tags(self, source: Job, target: Job) -> int:
        target_tags = {
            link.interest_tag_id
            for link in (
                (await self.db.execute(select(JobTag).where(JobTag.job_id == target.id)))
                .scalars()
                .all()
            )
        }
        merged = 0
        for link in (
            (await self.db.execute(select(JobTag).where(JobTag.job_id == source.id)))
            .scalars()
            .all()
        ):
            if link.interest_tag_id in target_tags:
                await self.db.delete(link)
            else:
                link.job_id = target.id
                target_tags.add(link.interest_tag_id)
            merged += 1
        return merged

    async def _merge_departments(self, source: Job, target: Job) -> int:
        target_links = {
            link.department_id: link
            for link in (
                (
                    await self.db.execute(
                        select(JobDepartmentLink).where(JobDepartmentLink.job_id == target.id)
                    )
                )
                .scalars()
                .all()
            )
        }
        merged = 0
        for link in (
            (
                await self.db.execute(
                    select(JobDepartmentLink).where(JobDepartmentLink.job_id == source.id)
                )
            )
            .scalars()
            .all()
        ):
            counterpart = target_links.get(link.department_id)
            if counterpart is None:
                link.job_id = target.id
                target_links[link.department_id] = link
                merged += 1
                continue
            if link.relevance > counterpart.relevance:
                counterpart.relevance = link.relevance
            for field in ("rationale", "typical_position"):
                if not getattr(counterpart, field):
                    setattr(counterpart, field, getattr(link, field))
            if not counterpart.required_subjects:
                counterpart.required_subjects = list(link.required_subjects or [])
            if counterpart.salary_band is None:
                counterpart.salary_band = link.salary_band
            if counterpart.employment_rate_pct is None:
                counterpart.employment_rate_pct = link.employment_rate_pct
            await self.db.delete(link)
            merged += 1
        return merged

    async def _merge_relations(self, source: Job, target: Job) -> int:
        merged = 0
        relations = (
            (
                await self.db.execute(
                    select(JobRelation).where(
                        (JobRelation.from_job_id == source.id)
                        | (JobRelation.to_job_id == source.id)
                    )
                )
            )
            .scalars()
            .all()
        )
        for relation in relations:
            new_from = target.id if relation.from_job_id == source.id else relation.from_job_id
            new_to = target.id if relation.to_job_id == source.id else relation.to_job_id
            if new_from == new_to:
                await self.db.delete(relation)
                merged += 1
                continue
            conflict = (
                (
                    await self.db.execute(
                        select(JobRelation).where(
                            JobRelation.from_job_id == new_from,
                            JobRelation.to_job_id == new_to,
                            JobRelation.relation_type == relation.relation_type,
                            JobRelation.id != relation.id,
                        )
                    )
                )
                .scalars()
                .first()
            )
            if conflict is not None:
                conflict.weight = max(conflict.weight, relation.weight)
                conflict.confidence = max(conflict.confidence, relation.confidence)
                if not conflict.rationale:
                    conflict.rationale = relation.rationale
                await self.db.delete(relation)
            else:
                relation.from_job_id = new_from
                relation.to_job_id = new_to
            merged += 1
        return merged

    async def _merge_match_insights(self, source: Job, target: Job) -> int:
        merged = 0
        target_rows = {
            row.user_id: row
            for row in (
                (
                    await self.db.execute(
                        select(MatchInsight).where(MatchInsight.job_id == target.id)
                    )
                )
                .scalars()
                .all()
            )
        }
        for row in (
            (await self.db.execute(select(MatchInsight).where(MatchInsight.job_id == source.id)))
            .scalars()
            .all()
        ):
            counterpart = target_rows.get(row.user_id)
            if counterpart is None:
                row.job_id = target.id
                target_rows[row.user_id] = row
                merged += 1
                continue
            counterpart.user_score = _max_non_null(counterpart.user_score, row.user_score)
            if counterpart.status is None:
                counterpart.status = row.status
            if not counterpart.user_notes:
                counterpart.user_notes = row.user_notes
            elif row.user_notes and counterpart.user_notes != row.user_notes:
                counterpart.user_notes = (
                    f"{counterpart.user_notes}\n\n[merged from {source.code}] {row.user_notes}"
                )
            counterpart.seen_at = _earliest(counterpart.seen_at, row.seen_at)
            counterpart.saved_at = _earliest(counterpart.saved_at, row.saved_at)
            counterpart.hidden_at = _earliest(counterpart.hidden_at, row.hidden_at)
            for field in (
                "ai_score",
                "ai_confidence",
                "ai_summary",
                "ai_positives",
                "ai_negatives",
                "prerequisites",
                "ai_model",
                "ai_generated_at",
                "fit_score",
                "fit_breakdown",
                "fit_version",
            ):
                if getattr(counterpart, field) in (None, "", [], {}):
                    setattr(counterpart, field, getattr(row, field))
            await self.db.delete(row)
            merged += 1
        return merged

    async def _repoint_career_paths(self, source: Job, target: Job) -> int:
        paths = (
            (await self.db.execute(select(CareerPath).where(CareerPath.job_id == source.id)))
            .scalars()
            .all()
        )
        for path in paths:
            path.job_id = target.id
        return len(paths)

    async def _repoint_growth_plans(self, source: Job, target: Job) -> int:
        plans = (
            (await self.db.execute(select(GrowthPlan).where(GrowthPlan.target_job_id == source.id)))
            .scalars()
            .all()
        )
        target_users = {
            user_id
            for (user_id,) in (
                await self.db.execute(
                    select(GrowthPlan.user_id).where(GrowthPlan.target_job_id == target.id)
                )
            ).all()
        }
        repointed = 0
        for plan in plans:
            if plan.user_id in target_users:
                continue
            plan.target_job_id = target.id
            repointed += 1
        return repointed

    async def _merge_snapshots(self, source: Job, target: Job) -> int:
        target_key = f"job:{target.id}"
        merged = 0
        snapshots = (
            (
                await self.db.execute(
                    select(MarketSnapshot).where(MarketSnapshot.job_id == source.id)
                )
            )
            .scalars()
            .all()
        )
        for market_snapshot in snapshots:
            conflict = (
                (
                    await self.db.execute(
                        select(MarketSnapshot).where(
                            MarketSnapshot.scope_kind == market_snapshot.scope_kind,
                            MarketSnapshot.scope_key == target_key,
                            MarketSnapshot.capture_date == market_snapshot.capture_date,
                            MarketSnapshot.id != market_snapshot.id,
                        )
                    )
                )
                .scalars()
                .first()
            )
            if conflict is not None:
                await self.db.delete(market_snapshot)
            else:
                market_snapshot.job_id = target.id
                market_snapshot.scope_key = target_key
            merged += 1
        return merged


def _max_non_null(first, second):
    values = [value for value in (first, second) if value is not None]
    return max(values) if values else None


def _earliest(first, second):
    values = [value for value in (first, second) if value is not None]
    return min(values) if values else None


__all__ = ["JobTypeMergeError", "JobTypeMergeService"]
