"""Company triage + merge suggestions (plan 135 slice B).

The gray-band queue's consumer: batches pending label/candidate pairs
through the AI arbiter (``app.ai.agents.company_triage``), applies the
verdicts (alias + link, exclusion + create, or a human suggestion) and
owns the suggestion lifecycle (accept merges into the candidate, dismiss
writes the pair exclusion — the correction loop closes itself).

Verdicts persist on the pair row (paid once, never re-asked); alias rows
are written only when a link actually happens. Without a configured
provider, pending pairs become suggestions instead of blocking ingest
(family AI-with-fallback law). Never on the ingest hot path.
"""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.ai.agents.company_triage import PairVerdict, triage_pairs
from app.core.errors import NotFoundError, ValidationError
from app.models.background_job_model import BackgroundJob
from app.models.enums import (
    BackgroundJobStatus,
    BackgroundJobType,
    OrgAliasSource,
    OrgExclusionSource,
    OrgMatchState,
    OrgPairStatus,
    OrgSuggestionStatus,
)
from app.models.experience_model import (
    Organization,
    OrganizationMatchExclusion,
    OrganizationMatchPair,
    OrganizationMergeSuggestion,
)
from app.models.posting_model import JobPosting
from app.services.catalog.company_names import initials_key, name_key, quality_ok
from app.services.catalog.organization_service import (
    LLM_AUTO,
    OrganizationService,
)

BATCH_SIZE = 40
MAX_BATCHES = 3
MAX_QUEUED_JOBS = 1


class CompanyTriageService:
    """Gray-band arbiter runs + suggestion lifecycle."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.orgs = OrganizationService(db)

    async def run(self) -> dict:
        """Drain bounded batches of pending pairs; re-enqueue if more remain."""
        stats = {
            "batches": 0,
            "pairs": 0,
            "linked": 0,
            "created": 0,
            "suggested": 0,
            "excluded": 0,
            "unconfigured": False,
        }
        for _ in range(MAX_BATCHES):
            pairs = await self._pending_pairs(BATCH_SIZE)
            if not pairs:
                break
            aliases = await self.orgs.alias_strings(list({pair.org_id for pair, _org in pairs}))
            prompts = [self._pair_prompt(pair, org, aliases.get(org.id, [])) for pair, org in pairs]
            verdicts = await triage_pairs(self.db, prompts)
            stats["batches"] += 1
            stats["pairs"] += len(pairs)
            if verdicts is None:
                stats["unconfigured"] = True
                for pair, org in pairs:
                    await self._suggest_only(pair, org, reason="arbiter-unavailable")
                    stats["suggested"] += 1
                await self.db.commit()
                continue
            by_id = {verdict.pair_id: verdict for verdict in verdicts}
            for pair, org in pairs:
                verdict = by_id.get(str(pair.id))
                outcome = await self._apply(pair, org, verdict)
                stats[outcome] = stats[outcome] + 1
            await self.db.commit()
            if len(pairs) < BATCH_SIZE:
                break
        remaining = await self.pending_pair_count()
        if remaining and not stats["unconfigured"]:
            await self.enqueue_job()
        stats["remaining"] = remaining
        return stats

    async def _pending_pairs(self, limit: int) -> list[tuple[OrganizationMatchPair, Organization]]:
        rows = (
            await self.db.execute(
                select(OrganizationMatchPair, Organization)
                .join(Organization, Organization.id == OrganizationMatchPair.org_id)
                .where(OrganizationMatchPair.status == OrgPairStatus.PENDING.value)
                .order_by(OrganizationMatchPair.created_at)
                .limit(limit)
            )
        ).all()
        return [(pair, org) for pair, org in rows]

    async def pending_pair_count(self) -> int:
        return int(
            (
                await self.db.execute(
                    select(func.count()).where(
                        OrganizationMatchPair.status == OrgPairStatus.PENDING.value
                    )
                )
            ).scalar_one()
        )

    def _pair_prompt(
        self, pair: OrganizationMatchPair, org: Organization, aliases: list[str]
    ) -> dict:
        evidence = dict(pair.evidence or {})
        hint = evidence.get("domain") or evidence.get("slug") or ""
        return {
            "pair_id": str(pair.id),
            "label": pair.label,
            "candidate_name": org.name,
            "aliases": aliases,
            "domain": org.domain or evidence.get("domain"),
            "url_hint": hint,
        }

    async def _apply(
        self, pair: OrganizationMatchPair, org: Organization, verdict: PairVerdict | None
    ) -> str:
        """Apply one verdict; returns the stats key it counted for."""
        thresholds = await self.orgs.thresholds()
        if verdict is None:
            await self._suggest_only(pair, org, reason="no-verdict")
            return "suggested"
        self._record_verdict(pair, verdict)
        strong_verdict = verdict.confidence >= thresholds.get("llm_auto", LLM_AUTO)
        if verdict.verdict == "same" and strong_verdict and self._corroborated(pair, org):
            await self.orgs.write_alias(org, pair.label, OrgAliasSource.LLM.value)
            await self._relink_pending(pair.label_key, org, layer="llm")
            await self.orgs.maybe_promote(org, strong=True)
            self._resolve_pair(pair, decided_by="llm")
            return "linked"
        if verdict.verdict == "different" and strong_verdict:
            await self._write_exclusion(
                pair.label,
                pair.label_key,
                org,
                OrgExclusionSource.LLM.value,
                reason="llm:different",
            )
            created = await self._create_for_label(pair, url_hint=pair.evidence or {})
            if created is not None:
                await self._relink_pending(pair.label_key, created, layer="llm-different")
                self._resolve_pair(pair, decided_by="llm")
                return "created"
            self._resolve_pair(pair, decided_by="llm")
            return "excluded"
        await self._suggest_only(pair, org, reason=f"llm:{verdict.verdict}")
        return "suggested"

    def _corroborated(self, pair: OrganizationMatchPair, org: Organization) -> bool:
        evidence = dict(pair.evidence or {})
        domain = str(evidence.get("domain") or "").lower()
        if domain and org.domain and domain == org.domain.lower():
            return True
        label_initials = initials_key(pair.label)
        return bool(
            label_initials
            and label_initials == org.initials_key
            and set(name_key(pair.label).split()) & set((org.name_key or "").split())
        )

    def _record_verdict(self, pair: OrganizationMatchPair, verdict: PairVerdict) -> None:
        pair.verdict = verdict.verdict
        pair.confidence = verdict.confidence
        if verdict.canonical_name:
            pair.canonical_name = verdict.canonical_name[:200]

    def _resolve_pair(self, pair: OrganizationMatchPair, *, decided_by: str) -> None:
        pair.status = OrgPairStatus.RESOLVED.value
        pair.decided_by = decided_by

    async def _write_exclusion(
        self,
        label: str,
        label_key: str,
        org: Organization,
        source: str,
        *,
        reason: str,
    ) -> None:
        existing = (
            await self.db.execute(
                select(OrganizationMatchExclusion).where(
                    OrganizationMatchExclusion.label_key == label_key,
                    OrganizationMatchExclusion.org_id == org.id,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return
        self.db.add(
            OrganizationMatchExclusion(
                label=label,
                label_key=label_key,
                org_id=org.id,
                reason=reason[:300],
                source=source,
                created_by="triage",
            )
        )
        await self.db.flush()

    async def _create_for_label(
        self, pair: OrganizationMatchPair, *, url_hint: dict | None = None
    ) -> Organization | None:
        """Create the label's own organization when the name passes the gate."""
        if quality_ok(pair.label) is not None:
            return None
        evidence = dict(url_hint or {})
        signal_domain = evidence.get("domain")
        org = await self.orgs.create_org(
            pair.label,
            provenance={"source": "triage", "label_key": pair.label_key},
        )
        if signal_domain and not org.domain:
            org.domain = str(signal_domain)[:200]
        await self.db.flush()
        return org

    async def _suggest_only(
        self, pair: OrganizationMatchPair, org: Organization, *, reason: str
    ) -> None:
        """No confident verdict: create the label's org and ask a human."""
        created = await self._create_for_label(pair, url_hint=pair.evidence or {})
        if created is not None:
            await self._relink_pending(pair.label_key, created, layer="gray")
            await self._ensure_suggestion(pair, created, org, reason=reason)
        self._resolve_pair(pair, decided_by="suggestion")

    async def _relink_pending(self, label_key: str, org: Organization, *, layer: str) -> int:
        """Postings parked at `pending` for this label join the resolved org."""
        rows = (
            (await self.db.execute(select(JobPosting).where(JobPosting.org_id.is_(None))))
            .scalars()
            .all()
        )
        moved = 0
        for posting in rows:
            match = posting.org_match or {}
            if match.get("state") != OrgMatchState.PENDING.value:
                continue
            if name_key(posting.org) != label_key:
                continue
            posting.org_id = org.id
            posting.org_match = {
                **match,
                "layer": layer,
                "state": OrgMatchState.LINKED.value,
                "matched_on": "triage",
            }
            flag_modified(posting, "org_match")
            moved += 1
        return moved

    async def _ensure_suggestion(
        self,
        pair: OrganizationMatchPair,
        new_org: Organization,
        candidate: Organization,
        *,
        reason: str,
    ) -> OrganizationMergeSuggestion | None:
        if new_org.id == candidate.id:
            return None
        existing = (
            await self.db.execute(
                select(OrganizationMergeSuggestion).where(
                    OrganizationMergeSuggestion.org_a == new_org.id,
                    OrganizationMergeSuggestion.org_b == candidate.id,
                    OrganizationMergeSuggestion.label_key == pair.label_key,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing
        suggestion = OrganizationMergeSuggestion(
            org_a=new_org.id,
            org_b=candidate.id,
            label=pair.label,
            label_key=pair.label_key,
            score=float(pair.confidence or 0.0),
            reason=reason[:300],
            evidence={
                "verdict": pair.verdict,
                "confidence": pair.confidence,
                "canonical_name": pair.canonical_name,
                "pair_id": str(pair.id),
            },
            status=OrgSuggestionStatus.OPEN.value,
        )
        self.db.add(suggestion)
        await self.db.flush()
        return suggestion

    async def list_suggestions(self, *, status: str | None = "open") -> list[dict]:
        query = select(OrganizationMergeSuggestion).order_by(
            OrganizationMergeSuggestion.created_at.desc()
        )
        if status:
            query = query.where(OrganizationMergeSuggestion.status == status)
        rows = (await self.db.execute(query)).scalars().all()
        orgs = {
            org.id: org
            for org in (
                (
                    await self.db.execute(
                        select(Organization).where(
                            Organization.id.in_(
                                [row.org_a for row in rows] + [row.org_b for row in rows]
                            )
                        )
                    )
                )
                .scalars()
                .all()
            )
        }
        return [
            {
                "id": str(row.id),
                "label": row.label,
                "score": row.score,
                "reason": row.reason,
                "status": row.status,
                "evidence": row.evidence or {},
                "org_a": self._org_brief(orgs.get(row.org_a)),
                "org_b": self._org_brief(orgs.get(row.org_b)),
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ]

    def _org_brief(self, org: Organization | None) -> dict | None:
        if org is None:
            return None
        return {"id": str(org.id), "key": org.key, "name": org.name, "status": org.status}

    async def get_suggestion(self, suggestion_id: UUID) -> OrganizationMergeSuggestion:
        row = (
            await self.db.execute(
                select(OrganizationMergeSuggestion).where(
                    OrganizationMergeSuggestion.id == suggestion_id
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundError("Merge suggestion not found")
        return row

    async def accept_suggestion(
        self, suggestion_id: UUID, *, decided_by: str = "admin"
    ) -> Organization:
        """Accept = merge the label's org into the established candidate."""
        suggestion = await self.get_suggestion(suggestion_id)
        if suggestion.status != OrgSuggestionStatus.OPEN.value:
            raise ValidationError("Only open suggestions can be accepted")
        suggestion.status = OrgSuggestionStatus.ACCEPTED.value
        suggestion.decided_by = decided_by
        await self.db.flush()
        return await self.orgs.merge(suggestion.org_a, suggestion.org_b)

    async def dismiss_suggestion(
        self, suggestion_id: UUID, *, decided_by: str = "admin"
    ) -> OrganizationMergeSuggestion:
        """Dismiss = these are different employers; write the pair exclusion."""
        suggestion = await self.get_suggestion(suggestion_id)
        if suggestion.status != OrgSuggestionStatus.OPEN.value:
            raise ValidationError("Only open suggestions can be dismissed")
        org = await self.orgs.get_org(suggestion.org_b)
        await self._write_exclusion(
            suggestion.label,
            suggestion.label_key,
            org,
            OrgExclusionSource.DISMISS.value,
            reason="suggestion dismissed",
        )
        suggestion.status = OrgSuggestionStatus.DISMISSED.value
        suggestion.decided_by = decided_by
        await self.db.commit()
        await self.db.refresh(suggestion)
        return suggestion

    async def list_pairs(self, *, status: str | None = "pending") -> list[dict]:
        query = (
            select(OrganizationMatchPair, Organization)
            .join(Organization, Organization.id == OrganizationMatchPair.org_id)
            .order_by(OrganizationMatchPair.created_at.desc())
        )
        if status:
            query = query.where(OrganizationMatchPair.status == status)
        rows = (await self.db.execute(query)).all()
        return [
            {
                "id": str(pair.id),
                "label": pair.label,
                "status": pair.status,
                "verdict": pair.verdict,
                "confidence": pair.confidence,
                "evidence": pair.evidence or {},
                "candidate": self._org_brief(org),
                "created_at": pair.created_at.isoformat() if pair.created_at else None,
            }
            for pair, org in rows
        ]

    async def enqueue_job(self) -> bool:
        """Queue one triage run unless one is already waiting (depth cap)."""
        return await enqueue_company_triage(self.db)


async def enqueue_company_triage(db: AsyncSession, *, max_queued: int = MAX_QUEUED_JOBS) -> bool:
    """Queue a triage run when pending pairs exist and the queue is shallow."""
    active = int(
        (
            await db.execute(
                select(func.count()).where(
                    BackgroundJob.job_type == BackgroundJobType.COMPANY_TRIAGE.value,
                    BackgroundJob.status.in_(
                        [
                            BackgroundJobStatus.QUEUED.value,
                            BackgroundJobStatus.RUNNING.value,
                        ]
                    ),
                )
            )
        ).scalar_one()
    )
    if active >= max_queued:
        return False
    pending = int(
        (
            await db.execute(
                select(func.count()).where(
                    OrganizationMatchPair.status == OrgPairStatus.PENDING.value
                )
            )
        ).scalar_one()
    )
    if not pending:
        return False
    from app.services.job_worker import enqueue

    await enqueue(
        db,
        BackgroundJobType.COMPANY_TRIAGE.value,
        {"requested_at": datetime.now(UTC).isoformat()},
        max_attempts=2,
    )
    return True


async def run_company_triage(db: AsyncSession) -> dict:
    """Job handler body: one bounded drain pass of the gray-band queue."""
    try:
        return await CompanyTriageService(db).run()
    except Exception:
        await db.rollback()
        raise
