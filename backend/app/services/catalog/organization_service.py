"""Organizations service: matcher, lifecycle, merge.

Postings and experience items create/propose organizations on ingest;
this module owns the matcher that keeps the entity deduplicated — one
pipeline for every caller (plan 135 decision 12): quality gate →
exclusions → exact keys (slug/alias/initials/domain) → blocked fuzzy →
gray band. The gray band records a pending pair row (the AI arbiter's
queue, plan 135 slice B); nothing auto-links without strong evidence.
Lifecycle mirrors skills (21): proposed → active via admin promotion,
duplicates merged (references re-pointed, aliases folded as rows, loser
deprecated — never deleted).
"""

import re
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.core.errors import NotFoundError, ValidationError
from app.models.company_model import CompanyProfile
from app.models.enums import (
    OrgAliasSource,
    OrgAliasState,
    OrgMatchState,
    OrgPairStatus,
    OrgStatus,
    OrgSuggestionStatus,
)
from app.models.experience_model import (
    ExperienceItem,
    Organization,
    OrganizationAlias,
    OrganizationMatchExclusion,
    OrganizationMatchPair,
    OrganizationMergeSuggestion,
)
from app.models.posting_model import JobPosting
from app.models.settings_model import AppSetting
from app.services.catalog.company_names import (
    alias_key,
    initials_key,
    name_key,
    quality_ok,
    url_company_signal,
)

TRIGRAM = re.compile(r"[a-z0-9]+")

# Fuzzy layer thresholds; DB-overridable via the AppSetting row
# "organization_match_thresholds" ({match, gray_low, llm_auto}) — the
# rules surface edits it, these are the fallback constants.
MATCH_THRESHOLD = 0.9
GRAY_BAND_LOW = 0.45
LLM_AUTO = 0.95
INITIALS_FLOOR = 0.82
THRESHOLDS_SETTING_KEY = "organization_match_thresholds"


def _trigrams(text: str) -> set[str]:
    grams: set[str] = set()
    for token in TRIGRAM.findall(text.lower()):
        padded = f"  {token} "
        grams.update(padded[i : i + 3] for i in range(len(padded) - 2))
    return grams


def trigram_similarity(a: str, b: str) -> float:
    """Jaccard overlap on padded token trigrams (dialect-safe by design)."""
    ga, gb = _trigrams(a), _trigrams(b)
    if not ga or not gb:
        return 0.0
    return len(ga & gb) / len(ga | gb)


@dataclass
class MatchDecision:
    """The matcher's outcome for one raw label (the org_match basis)."""

    kind: str
    org: Organization | None = None
    candidate: Organization | None = None
    layer: str = ""
    score: float = 0.0
    matched_on: str = ""
    reason: str = ""

    def provenance(self) -> dict:
        return {
            "layer": self.layer,
            "score": round(self.score, 4),
            "matched_on": self.matched_on,
        }


class _CandidateIndex:
    """One sync-batch's worth of matchable orgs, loaded once.

    Exact lookups run over these dicts; the fuzzy layer scans only the
    trigram/initials-blocked subset — never all-vs-all. Orgs created
    through the service register here so the same batch links instead of
    re-creating.
    """

    def __init__(self) -> None:
        self.orgs: list[Organization] = []
        self.by_key: dict[str, list[Organization]] = {}
        self.by_name_key: dict[str, list[Organization]] = {}
        self.by_initials: dict[str, list[Organization]] = {}
        self.by_domain: dict[str, Organization] = {}
        self.alias_keys_by_org: dict[UUID, list[str]] = {}
        self.excluded_labels: set[str] = set()
        self.excluded_pairs: set[tuple[str, UUID]] = set()

    def register(self, org: Organization, alias_keys: list[str]) -> None:
        self.orgs.append(org)
        self.by_key.setdefault(org.key, []).append(org)
        self.alias_keys_by_org[org.id] = list(alias_keys)
        for key in {org.name_key, *alias_keys}:
            if key:
                self.by_name_key.setdefault(key, []).append(org)
        if org.initials_key:
            self.by_initials.setdefault(org.initials_key, []).append(org)
        if org.domain:
            self.by_domain.setdefault(org.domain.lower(), org)

    def add_alias_key(self, org: Organization, key: str) -> None:
        self.alias_keys_by_org.setdefault(org.id, []).append(key)
        self.by_name_key.setdefault(key, []).append(org)


class OrganizationService:
    """Matcher + lifecycle over one shared organizations table."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self._index: _CandidateIndex | None = None
        self._thresholds: dict[str, float] | None = None

    async def _candidate_index(self) -> _CandidateIndex:
        if self._index is not None:
            return self._index
        index = _CandidateIndex()
        orgs = list(
            (
                await self.db.execute(
                    select(Organization).where(Organization.status != OrgStatus.DEPRECATED.value)
                )
            )
            .scalars()
            .all()
        )
        alias_rows: list[OrganizationAlias] = []
        if orgs:
            alias_rows = list(
                (
                    await self.db.execute(
                        select(OrganizationAlias).where(
                            OrganizationAlias.org_id.in_([org.id for org in orgs]),
                            OrganizationAlias.state == OrgAliasState.ACTIVE.value,
                        )
                    )
                )
                .scalars()
                .all()
            )
        aliases_by_org: dict[UUID, list[str]] = {}
        for row in alias_rows:
            aliases_by_org.setdefault(row.org_id, []).append(row.alias_key)
        for org in orgs:
            index.register(org, aliases_by_org.get(org.id, []))
        exclusions = (await self.db.execute(select(OrganizationMatchExclusion))).scalars().all()
        for exclusion in exclusions:
            if exclusion.org_id is None:
                index.excluded_labels.add(exclusion.label_key)
            else:
                index.excluded_pairs.add((exclusion.label_key, exclusion.org_id))
        self._index = index
        return index

    async def thresholds(self) -> dict[str, float]:
        if self._thresholds is not None:
            return self._thresholds
        row = (
            await self.db.execute(
                select(AppSetting).where(AppSetting.key == THRESHOLDS_SETTING_KEY)
            )
        ).scalar_one_or_none()
        data = dict(row.value or {}) if row is not None else {}
        self._thresholds = {
            "match": float(data.get("match", MATCH_THRESHOLD)),
            "gray_low": float(data.get("gray_low", GRAY_BAND_LOW)),
            "llm_auto": float(data.get("llm_auto", LLM_AUTO)),
        }
        return self._thresholds

    async def _tie_break(self, orgs: list[Organization]) -> Organization:
        """Deterministic winner when several orgs claim one key:
        active > proposed, then most live postings, then oldest."""
        if len(orgs) == 1:
            return orgs[0]
        actives = [org for org in orgs if org.status == OrgStatus.ACTIVE.value]
        pool = actives or orgs
        if len(pool) == 1:
            return pool[0]
        counts = dict(
            (
                await self.db.execute(
                    select(JobPosting.org_id, func.count())
                    .where(JobPosting.org_id.in_([org.id for org in pool]))
                    .group_by(JobPosting.org_id)
                )
            ).all()
        )
        return max(
            pool,
            key=lambda org: (int(counts.get(org.id, 0)), -org.created_at.timestamp()),
        )

    async def _resolve_link(self, label: str, url: str | None = None) -> MatchDecision:
        """The layered matcher: quality → exclusions → exact → fuzzy → gray."""
        label = (label or "").strip()
        index = await self._candidate_index()
        thresholds = await self.thresholds()

        def allowed(org: Organization) -> bool:
            return (name_key(label), org.id) not in index.excluded_pairs

        reason = quality_ok(label)
        if reason is not None:
            return MatchDecision(kind="reject", layer="quality", reason=reason)
        label_key = name_key(label)
        if label_key in index.excluded_labels:
            return MatchDecision(kind="reject", layer="exclusion", reason="excluded_label")

        signal = url_company_signal(url)
        if signal is not None:
            domain_org = index.by_domain.get(signal["domain"])
            if domain_org is not None and allowed(domain_org):
                return MatchDecision(
                    kind="link",
                    org=domain_org,
                    layer="domain",
                    score=1.0,
                    matched_on=f"domain:{signal['domain']}",
                )

        from app.services.profile.experience_service import slugify_org

        slug = slugify_org(label)
        key_hits = [org for org in index.by_key.get(slug, []) if allowed(org)]
        if key_hits:
            return MatchDecision(
                kind="link", org=key_hits[0], layer="key", score=1.0, matched_on="key"
            )

        alias_hits = [org for org in index.by_name_key.get(label_key, []) if allowed(org)]
        if alias_hits:
            winner = await self._tie_break(alias_hits)
            return MatchDecision(
                kind="link", org=winner, layer="alias", score=1.0, matched_on="alias"
            )

        label_initials = initials_key(label)
        if label_initials:
            initials_hits = [
                org for org in index.by_initials.get(label_initials, []) if allowed(org)
            ]
            if initials_hits:
                candidate = await self._tie_break(initials_hits)
                corroborated = (
                    signal is not None
                    and candidate.domain is not None
                    and candidate.domain.lower() == signal["domain"]
                )
                if corroborated:
                    return MatchDecision(
                        kind="link",
                        org=candidate,
                        layer="initials",
                        score=thresholds["match"],
                        matched_on="initials+domain",
                    )
                return MatchDecision(
                    kind="gray",
                    candidate=candidate,
                    layer="initials",
                    score=INITIALS_FLOOR,
                    matched_on="initials",
                    reason="initials_need_corroboration",
                )

        label_grams = _trigrams(label_key)
        blocked: list[tuple[Organization, float]] = []
        for org in index.orgs:
            if not allowed(org):
                continue
            keys = [org.name_key, *index.alias_keys_by_org.get(org.id, [])]
            best = 0.0
            for key in keys:
                if not key:
                    continue
                shares_block = bool(_trigrams(key) & label_grams) or (
                    bool(label_initials) and org.initials_key == label_initials
                )
                if not shares_block:
                    continue
                best = max(best, trigram_similarity(label_key, key))
            if best > 0:
                blocked.append((org, best))
        if blocked:
            blocked.sort(key=lambda pair: (-pair[1], pair[0].created_at.timestamp()))
            best_org, best_score = blocked[0]
            if best_score >= thresholds["match"]:
                return MatchDecision(
                    kind="link",
                    org=best_org,
                    layer="fuzzy",
                    score=best_score,
                    matched_on="fuzzy",
                )
            if best_score >= thresholds["gray_low"]:
                return MatchDecision(
                    kind="gray",
                    candidate=best_org,
                    layer="fuzzy",
                    score=best_score,
                    matched_on="fuzzy",
                    reason="gray_band",
                )

        return MatchDecision(kind="create", layer="create", score=0.0, matched_on="no_match")

    async def resolve(self, name: str) -> Organization | None:
        """The org a raw label belongs to (None when nothing matches)."""
        decision = await self._resolve_link(name)
        return decision.org

    async def find_or_propose(
        self,
        name: str,
        *,
        url: str | None = None,
        provenance: dict | None = None,
    ) -> tuple[Organization | None, bool]:
        """Matcher-first find-or-propose (never duplicates on ingest).

        Returns (None, False) for gray-band and rejected labels — the gray
        band records a pending pair row, junk creates nothing.
        """
        decision = await self._resolve_link(name, url)
        if decision.kind == "link" and decision.org is not None:
            await self._learn_alias(decision.org, (name or "").strip())
            return decision.org, False
        if decision.kind == "create":
            return await self._create_org((name or "").strip(), provenance, url), True
        if decision.kind == "gray":
            await self._record_pending_pair((name or "").strip(), decision, url)
        return None, False

    async def _learn_alias(self, org: Organization, label: str) -> None:
        """Persist a matched variant as an alias row (learned provenance)."""
        await self.write_alias(org, label, OrgAliasSource.LEARNED.value)

    async def write_alias(
        self, org: Organization, label: str, source: str
    ) -> OrganizationAlias | None:
        """Insert one alias row unless the key is already claimed (idempotent;
        an excluded row keeps its state — negative evidence wins)."""
        label = (label or "").strip()[:200]
        if not label or label.lower() == (org.name or "").strip().lower():
            return None
        key = alias_key(label)
        if not key:
            return None
        existing = (
            await self.db.execute(
                select(OrganizationAlias).where(
                    OrganizationAlias.org_id == org.id,
                    OrganizationAlias.alias_key == key,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return None
        row = OrganizationAlias(org_id=org.id, alias=label, alias_key=key, source=source)
        self.db.add(row)
        await self.db.flush()
        if self._index is not None:
            self._index.add_alias_key(org, key)
        return row

    async def _key_exists(self, key: str) -> bool:
        row = (
            await self.db.execute(select(Organization.id).where(Organization.key == key).limit(1))
        ).scalar_one_or_none()
        return row is not None

    async def _create_org(
        self, label: str, provenance: dict | None, url: str | None
    ) -> Organization:
        from app.services.profile.experience_service import slugify_org

        label = (label or "").strip()[:200]
        base = slugify_org(label)
        key = base
        suffix = 2
        while await self._key_exists(key):
            key = f"{base}-{suffix}"
            suffix += 1
        signal = url_company_signal(url)
        org = Organization(
            key=key,
            name=label,
            status=OrgStatus.PROPOSED.value,
            provenance=provenance or {},
            name_key=name_key(label),
            initials_key=initials_key(label),
            domain=signal["domain"] if signal is not None else None,
        )
        self.db.add(org)
        await self.db.flush()
        if self._index is not None:
            self._index.register(org, [])
        return org

    async def create_org(
        self, label: str, *, provenance: dict | None = None, url: str | None = None
    ) -> Organization:
        """Create one organization for a label (slug collision-safe)."""
        return await self._create_org(label, provenance, url)

    async def maybe_promote(self, org: Organization, *, strong: bool = False) -> bool:
        """proposed → active on strong evidence (plan 135 decision 8).

        Strong = a URL-domain match or an LLM `same` with corroboration, or
        postings from at least two distinct sources. Everything else stays
        proposed and visible in the matcher-review list."""
        if org.status != OrgStatus.PROPOSED.value:
            return False
        if not strong:
            distinct = (
                await self.db.execute(
                    select(func.count(func.distinct(JobPosting.source_id))).where(
                        JobPosting.org_id == org.id
                    )
                )
            ).scalar_one()
            if int(distinct) < 2:
                return False
        org.status = OrgStatus.ACTIVE.value
        await self.db.flush()
        return True

    async def _record_pending_pair(
        self, label: str, decision: MatchDecision, url: str | None
    ) -> None:
        """Enqueue one gray-band label/candidate pair for the arbiter."""
        if decision.candidate is None:
            return
        label = (label or "").strip()[:200]
        label_key = name_key(label)
        existing = (
            await self.db.execute(
                select(OrganizationMatchPair).where(
                    OrganizationMatchPair.label_key == label_key,
                    OrganizationMatchPair.org_id == decision.candidate.id,
                )
            )
        ).scalar_one_or_none()
        signal = url_company_signal(url) or {}
        evidence = {"domain": signal.get("domain"), "slug": signal.get("slug")}
        if existing is not None:
            if existing.status == OrgPairStatus.PENDING.value:
                existing.evidence = {**(existing.evidence or {}), **evidence}
            return
        self.db.add(
            OrganizationMatchPair(
                label=label,
                label_key=label_key,
                org_id=decision.candidate.id,
                evidence=evidence,
                status=OrgPairStatus.PENDING.value,
            )
        )
        await self.db.flush()

    async def attach_to_posting(self, posting: JobPosting, *, run_id=None, mode=None) -> None:
        """Match the raw label → org_id (ingest hook; raw + provenance
        kept). Journals `company_match` — org link + state projection,
        ids/knobs only — in the caller's transaction."""
        from app.services.postings.change_journal import (
            ORG_MATCH_FIELDS,
            PostingChangeJournal,
            snapshot,
        )

        label = (posting.org or "").strip()
        if not label:
            return
        before = snapshot(posting, ORG_MATCH_FIELDS)
        decision = await self._resolve_link(label, posting.url)
        match = decision.provenance()
        state: str | None
        if decision.kind == "link" and decision.org is not None:
            org = decision.org
            posting.org_id = org.id
            signal = url_company_signal(posting.url)
            if posting.url and not org.domain and signal is not None:
                org.domain = signal["domain"]
            await self.maybe_promote(org, strong=decision.layer == "domain")
            state = OrgMatchState.LINKED.value
        elif decision.kind == "create":
            org = await self._create_org(
                label, {"source": "posting", "posting_id": str(posting.id)}, posting.url
            )
            posting.org_id = org.id
            state = OrgMatchState.LINKED.value
        elif decision.kind == "gray":
            await self._record_pending_pair(label, decision, posting.url)
            posting.org_id = None
            state = OrgMatchState.PENDING.value
        else:
            posting.org_id = None
            state = OrgMatchState.REJECTED.value
            match["reason"] = decision.reason
        match["state"] = state
        posting.org_match = match
        posting.org_match_state = state
        flag_modified(posting, "org_match")
        actor_ref: dict = {}
        if run_id is not None:
            actor_ref["run_id"] = str(run_id)
        if mode is not None:
            actor_ref["mode"] = mode
        PostingChangeJournal.record(
            self.db,
            posting.id,
            "company_match",
            actor_ref=actor_ref or None,
            operation={"decision": decision.kind, "layer": decision.layer},
            before=before,
            after=snapshot(posting, ORG_MATCH_FIELDS),
        )

    async def backfill_postings(self) -> dict:
        """Run the current matcher over postings it has not judged yet
        (`org_match` empty — the pre-matcher backlog and each new layer's
        first pass). Idempotent: judged postings are never re-judged.
        The emptiness check is Python-side: JSON columns store None as
        JSON null (none_as_null=False), so SQL IS NULL sees only half."""
        rows = await self.db.execute(
            select(JobPosting).where(func.length(func.trim(JobPosting.org)) > 0)
        )
        postings = [posting for posting in rows.scalars().all() if not posting.org_match]
        linked = pending = rejected = 0
        for posting in postings:
            await self.attach_to_posting(posting, mode="backfill")
            state = (posting.org_match or {}).get("state")
            if state == OrgMatchState.LINKED.value:
                linked += 1
            elif state == OrgMatchState.PENDING.value:
                pending += 1
            else:
                rejected += 1
        await self.db.commit()
        return {
            "matched": linked,
            "pending": pending,
            "rejected": rejected,
            "scanned": len(postings),
        }

    async def backfill_experience_items(self) -> dict:
        """Re-resolve experience items through the same pipeline (one-shot)."""
        rows = await self.db.execute(
            select(ExperienceItem).where(
                ExperienceItem.org_id.is_(None),
                func.length(func.trim(ExperienceItem.org_name)) > 0,
            )
        )
        items = list(rows.scalars().all())
        linked = created = unmatched = 0
        for item in items:
            org, was_created = await self.find_or_propose(
                item.org_name, provenance={"source": "experience_backfill"}
            )
            if org is not None:
                item.org_id = org.id
                created += int(was_created)
                linked += 1
            else:
                unmatched += 1
        await self.db.commit()
        return {"linked": linked, "created": created, "unmatched": unmatched}

    async def list_orgs(
        self,
        *,
        status: str | None = None,
        q: str | None = None,
    ) -> list[dict]:
        """Admin listing with live posting counts (top-hiring visibility)."""
        query = select(Organization).order_by(Organization.created_at.desc())
        if status:
            query = query.where(Organization.status == status)
        if q:
            query = query.where(Organization.name.ilike(f"%{q}%"))
        rows = list((await self.db.execute(query)).scalars().all())
        counts = dict(
            (
                await self.db.execute(
                    select(JobPosting.org_id, func.count())
                    .where(JobPosting.org_id.is_not(None))
                    .group_by(JobPosting.org_id)
                )
            ).all()
        )
        alias_strings = await self.alias_strings([org.id for org in rows])
        return [
            {
                "id": str(org.id),
                "key": org.key,
                "name": org.name,
                "domain": org.domain,
                "aliases": alias_strings.get(org.id, []),
                "status": org.status,
                "posting_count": int(counts.get(org.id, 0)),
            }
            for org in rows
        ]

    async def alias_strings(self, org_ids: list[UUID]) -> dict[UUID, list[str]]:
        if not org_ids:
            return {}
        rows = (
            (
                await self.db.execute(
                    select(OrganizationAlias)
                    .where(
                        OrganizationAlias.org_id.in_(org_ids),
                        OrganizationAlias.state == OrgAliasState.ACTIVE.value,
                    )
                    .order_by(OrganizationAlias.created_at)
                )
            )
            .scalars()
            .all()
        )
        out: dict[UUID, list[str]] = {}
        for row in rows:
            out.setdefault(row.org_id, []).append(row.alias)
        return out

    async def get_org(self, org_id: UUID) -> Organization:
        org = (
            (await self.db.execute(select(Organization).where(Organization.id == org_id)))
            .scalars()
            .first()
        )
        if org is None:
            raise NotFoundError("Organization not found")
        return org

    async def promote(self, org_id: UUID) -> Organization:
        """proposed → active (the only promotion path, like skills)."""
        org = await self.get_org(org_id)
        if org.status != "proposed":
            raise ValidationError("Only proposed organizations can be promoted")
        org.status = "active"
        self.db.add(org)
        await self.db.commit()
        await self.db.refresh(org)
        return org

    async def add_alias(self, org_id: UUID, alias: str) -> Organization:
        org = await self.get_org(org_id)
        alias = (alias or "").strip()[:200]
        if not alias:
            raise ValidationError("Alias is required")
        key = alias_key(alias)
        existing = (
            await self.db.execute(
                select(OrganizationAlias).where(
                    OrganizationAlias.org_id == org.id,
                    OrganizationAlias.alias_key == key,
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            self.db.add(
                OrganizationAlias(
                    org_id=org.id,
                    alias=alias,
                    alias_key=key,
                    source=OrgAliasSource.MANUAL.value,
                )
            )
            await self.db.commit()
        await self.db.refresh(org)
        return org

    async def org_aliases(self, org_id: UUID) -> list[str]:
        return (await self.alias_strings([org_id])).get(org_id, [])

    async def alias_rows(self, org_id: UUID) -> list[dict]:
        """The rules surface's alias list (provenance + state visible)."""
        rows = (
            (
                await self.db.execute(
                    select(OrganizationAlias)
                    .where(OrganizationAlias.org_id == org_id)
                    .order_by(OrganizationAlias.created_at)
                )
            )
            .scalars()
            .all()
        )
        return [
            {
                "id": str(row.id),
                "alias": row.alias,
                "alias_key": row.alias_key,
                "source": row.source,
                "state": row.state,
                "created_by": row.created_by,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ]

    async def _get_alias_row(self, org_id: UUID, alias_id: UUID) -> OrganizationAlias:
        row = (
            await self.db.execute(
                select(OrganizationAlias).where(
                    OrganizationAlias.id == alias_id,
                    OrganizationAlias.org_id == org_id,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundError("Alias not found")
        return row

    async def remove_alias(self, org_id: UUID, alias_id: UUID) -> None:
        row = await self._get_alias_row(org_id, alias_id)
        await self.db.delete(row)
        await self.db.commit()

    async def set_alias_state(self, org_id: UUID, alias_id: UUID, state: str) -> OrganizationAlias:
        if state not in {OrgAliasState.ACTIVE.value, OrgAliasState.EXCLUDED.value}:
            raise ValidationError("Unknown alias state")
        row = await self._get_alias_row(org_id, alias_id)
        row.state = state
        await self.db.commit()
        await self.db.refresh(row)
        return row

    async def list_exclusions(self, *, kind: str | None = None) -> list[dict]:
        query = select(OrganizationMatchExclusion).order_by(
            OrganizationMatchExclusion.created_at.desc()
        )
        if kind == "global":
            query = query.where(OrganizationMatchExclusion.org_id.is_(None))
        elif kind == "pair":
            query = query.where(OrganizationMatchExclusion.org_id.is_not(None))
        rows = (await self.db.execute(query)).scalars().all()
        org_ids = [row.org_id for row in rows if row.org_id is not None]
        orgs = {}
        if org_ids:
            orgs = {
                org.id: org
                for org in (
                    (
                        await self.db.execute(
                            select(Organization).where(Organization.id.in_(org_ids))
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
                "label_key": row.label_key,
                "org_id": str(row.org_id) if row.org_id else None,
                "org": (
                    {
                        "id": str(orgs[row.org_id].id),
                        "key": orgs[row.org_id].key,
                        "name": orgs[row.org_id].name,
                    }
                    if row.org_id in orgs
                    else None
                ),
                "reason": row.reason,
                "source": row.source,
                "created_by": row.created_by,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ]

    async def create_exclusion(
        self,
        label: str,
        *,
        org_id: UUID | None = None,
        reason: str = "",
        created_by: str = "admin",
    ) -> dict:
        label = (label or "").strip()[:200]
        if not label:
            raise ValidationError("Exclusion label is required")
        reason = (reason or "").strip()[:300]
        if org_id is not None:
            await self.get_org(org_id)
        key = alias_key(label)
        existing = (
            await self.db.execute(
                select(OrganizationMatchExclusion).where(
                    OrganizationMatchExclusion.label_key == key,
                    OrganizationMatchExclusion.org_id == org_id
                    if org_id is not None
                    else OrganizationMatchExclusion.org_id.is_(None),
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise ValidationError("That exclusion already exists")
        row = OrganizationMatchExclusion(
            label=label,
            label_key=key,
            org_id=org_id,
            reason=reason,
            source="manual",
            created_by=created_by[:120],
        )
        self.db.add(row)
        await self.db.commit()
        await self.db.refresh(row)
        org_id_value = str(row.org_id) if row.org_id else None
        return {
            "id": str(row.id),
            "label": row.label,
            "org_id": org_id_value,
        }

    async def delete_exclusion(self, exclusion_id: UUID) -> None:
        row = (
            await self.db.execute(
                select(OrganizationMatchExclusion).where(
                    OrganizationMatchExclusion.id == exclusion_id
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundError("Exclusion not found")
        await self.db.delete(row)
        await self.db.commit()

    async def get_thresholds(self) -> dict[str, float]:
        return await self.thresholds()

    async def set_thresholds(self, data: dict) -> dict[str, float]:
        current = await self.thresholds()
        values = dict(current)
        for key, low, high in (
            ("match", 0.5, 1.0),
            ("gray_low", 0.0, 0.99),
            ("llm_auto", 0.5, 1.0),
        ):
            if key not in data or data[key] is None:
                continue
            try:
                value = float(data[key])
            except (TypeError, ValueError) as exc:
                raise ValidationError(f"{key} must be a number") from exc
            if not (low <= value <= high):
                raise ValidationError(f"{key} must be between {low} and {high}")
            values[key] = value
        if values["gray_low"] >= values["match"]:
            raise ValidationError("the gray band must sit below the match threshold")
        row = (
            await self.db.execute(
                select(AppSetting).where(AppSetting.key == THRESHOLDS_SETTING_KEY)
            )
        ).scalar_one_or_none()
        if row is None:
            row = AppSetting(
                key=THRESHOLDS_SETTING_KEY,
                value=dict(values),
                description="Company matcher thresholds",
            )
            self.db.add(row)
        else:
            row.value = dict(values)
        await self.db.commit()
        self._thresholds = dict(values)
        return dict(values)

    async def merge(self, org_id: UUID, target_id: UUID, *, actor_user_id=None) -> Organization:
        """Re-point references to the target and deprecate the duplicate.

        A 1:1 company profile rides along (re-pointed, flagged for
        review) unless the target has one too — two reviewed profiles
        never merge silently. The refusal fires before any mutation.
        Each re-pointed posting journals as `company_match`.
        """
        if org_id == target_id:
            raise ValidationError("Cannot merge an organization into itself")
        source = await self.get_org(org_id)
        target = await self.get_org(target_id)
        if target.status == "deprecated":
            raise ValidationError("Cannot merge into a deprecated organization")
        source_profile = (
            await self.db.execute(
                select(CompanyProfile).where(CompanyProfile.organization_id == source.id)
            )
        ).scalar_one_or_none()
        if source_profile is not None:
            target_profile = (
                await self.db.execute(
                    select(CompanyProfile).where(CompanyProfile.organization_id == target.id)
                )
            ).scalar_one_or_none()
            if target_profile is not None:
                raise ValidationError(
                    "Both organizations carry company profiles — reconcile them before merging"
                )
        rows = await self.db.execute(select(JobPosting).where(JobPosting.org_id == source.id))
        postings = list(rows.scalars().all())
        from app.services.postings.change_journal import (
            ORG_MATCH_FIELDS,
            PostingChangeJournal,
            snapshot,
        )

        for posting in postings:
            before = snapshot(posting, ORG_MATCH_FIELDS)
            posting.org_id = target.id
            actor_ref = {"user_id": str(actor_user_id)} if actor_user_id is not None else None
            PostingChangeJournal.record(
                self.db,
                posting.id,
                "company_match",
                actor_ref=actor_ref,
                operation={"merged_org": str(source.id), "into_org": str(target.id)},
                before=before,
                after=snapshot(posting, ORG_MATCH_FIELDS),
            )
        if source_profile is not None:
            source_profile.organization_id = target.id
            source_profile.needs_review = True
        await self._fold_alias_rows(source, target)
        await self._repoint_match_rows(source, target)
        source.status = "deprecated"
        provenance = dict(source.provenance or {})
        provenance["merged_into"] = str(target.id)
        source.provenance = provenance
        self.db.add(target)
        self.db.add(source)
        await self.db.commit()
        await self.db.refresh(target)
        return target

    async def _fold_alias_rows(self, source: Organization, target: Organization) -> None:
        """The source's names become target alias rows (merge provenance)."""
        incoming = [source.name, *(await self.org_aliases(source.id))]
        existing_keys = await self._alias_key_set(target.id)
        new_keys: list[str] = []
        for alias in incoming:
            alias = (alias or "").strip()[:200]
            if not alias:
                continue
            key = alias_key(alias)
            if not key or key in existing_keys:
                continue
            existing_keys.add(key)
            new_keys.append(key)
            self.db.add(
                OrganizationAlias(
                    org_id=target.id,
                    alias=alias,
                    alias_key=key,
                    source=OrgAliasSource.MERGE.value,
                )
            )
        if self._index is not None:
            for key in new_keys:
                self._index.add_alias_key(target, key)

    async def _alias_key_set(self, org_id: UUID) -> set[str]:
        rows = await self.db.execute(
            select(OrganizationAlias.alias_key).where(OrganizationAlias.org_id == org_id)
        )
        return set(rows.scalars().all())

    async def _repoint_match_rows(self, source: Organization, target: Organization) -> None:
        """Gray-band pairs follow the merge; open suggestions involving the
        source are dismissed (the merge answers them)."""
        pairs = list(
            (
                await self.db.execute(
                    select(OrganizationMatchPair).where(OrganizationMatchPair.org_id == source.id)
                )
            )
            .scalars()
            .all()
        )
        for pair in pairs:
            clash = (
                await self.db.execute(
                    select(OrganizationMatchPair).where(
                        OrganizationMatchPair.label_key == pair.label_key,
                        OrganizationMatchPair.org_id == target.id,
                    )
                )
            ).scalar_one_or_none()
            if clash is None:
                pair.org_id = target.id
            else:
                await self.db.delete(pair)
        suggestions = list(
            (
                await self.db.execute(
                    select(OrganizationMergeSuggestion).where(
                        OrganizationMergeSuggestion.status == OrgSuggestionStatus.OPEN.value,
                        (OrganizationMergeSuggestion.org_a == source.id)
                        | (OrganizationMergeSuggestion.org_b == source.id),
                    )
                )
            )
            .scalars()
            .all()
        )
        for suggestion in suggestions:
            suggestion.status = OrgSuggestionStatus.DISMISSED.value
            suggestion.decided_by = "merge"
