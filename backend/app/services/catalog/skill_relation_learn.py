"""The skill-relation discovery job (plan 138, step 5).

Deterministic candidate pass (zero AI) → batched LLM verdicts → the single
write seam (:class:`SkillRelationService`). The LLM is the offline teacher:
every edge it earns lands ``proposed`` and is **invisible to expansion**
(``load_graph`` loads approved rows only) until a human approves — an
approved ``synonym`` row is 0-cost identity in the walk, an approved
``is_a``/``related_to``/``part_of`` row costs one learned hop, and the
curated tree subtree stays free (the cost model of ``skill_graph``).

Pair-level adjudication (decision 6, v4): any ``skill_relations`` row for a
pair — any relation, any status — settles that pair for this job forever,
so a redirected verdict can never re-bill the same pair. The seam keeps its
per-(pair, relation) UNIQUE; manual rows for one pair are unaffected.

The delta watermark lives on the run ledger (``background_jobs.result``),
not in a table: a run only re-examines evidence newer than the last
succeeded run's watermark, and a run that capped out or had failed batches
holds the floor so its uncovered pairs are re-picked instead of lost.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from itertools import combinations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.agents.skill_relation_suggest import (
    MAX_PAIRS_PER_CALL,
    SkillEdgeVerdict,
    SkillEdgeVerdictSet,
    suggest_skill_edges,
)
from app.ai.gateway import RunRef
from app.ai.prompt_versions import prompt_version
from app.core.errors import AINotConfiguredError, NotFoundError, ValidationError
from app.models.background_job_model import BackgroundJob
from app.models.enums import (
    AITaskType,
    BackgroundJobStatus,
    BackgroundJobType,
    SkillOrigin,
    SkillRelationSource,
    SkillRelationStatus,
    SkillRelationType,
    SkillStatus,
)
from app.models.job_model import JobSkill
from app.models.posting_model import PostingSkill
from app.models.settings_model import AppSetting
from app.models.taxonomy_model import Skill, SkillRelation
from app.services.catalog.skill_relations import SkillRelationService

SETTINGS_KEY = "skill_relation_learn.thresholds"


@dataclass(frozen=True)
class Thresholds:
    """Job knobs; admin-overridable via one ``AppSetting`` JSON row."""

    min_support: int = 2
    batch_size: int = MAX_PAIRS_PER_CALL
    max_pairs_per_run: int = 200
    min_negative_confidence: float = 0.6


async def load_thresholds(db: AsyncSession) -> Thresholds:
    """Thresholds from ``app_settings`` (constant fallbacks, invalid ignored)."""
    row = (
        (await db.execute(select(AppSetting).where(AppSetting.key == SETTINGS_KEY)))
        .scalars()
        .first()
    )
    raw = row.value if row is not None and isinstance(row.value, dict) else {}
    defaults = Thresholds()
    parsed: dict[str, int | float] = {}
    for name, cast in (
        ("min_support", int),
        ("batch_size", int),
        ("max_pairs_per_run", int),
        ("min_negative_confidence", float),
    ):
        value = raw.get(name)
        try:
            parsed[name] = getattr(defaults, name) if value is None else cast(value)
        except (TypeError, ValueError):
            parsed[name] = getattr(defaults, name)
    return Thresholds(
        min_support=max(1, int(parsed["min_support"])),
        batch_size=max(1, min(int(parsed["batch_size"]), MAX_PAIRS_PER_CALL)),
        max_pairs_per_run=max(1, int(parsed["max_pairs_per_run"])),
        min_negative_confidence=max(0.0, min(float(parsed["min_negative_confidence"]), 1.0)),
    )


@dataclass(frozen=True)
class SkillInfo:
    """The catalog facts one prompt pair carries per endpoint."""

    id: uuid.UUID
    key: str
    label: str
    aliases: tuple[str, ...]
    category: str
    parent_key: str | None
    status: str
    origin: str
    created_at: datetime | None
    provenance: dict = field(default_factory=dict)


@dataclass
class RelationCandidate:
    """One adjudicable pair with its deterministic evidence."""

    pair_ref: str
    first: SkillInfo
    second: SkillInfo
    hypothesis: SkillRelationType
    signals: dict
    strength: float
    last_seen: datetime | None = None


def _norm(value: str) -> str:
    return " ".join((value or "").lower().replace("-", " ").replace("_", " ").split())


def _initialism(value: str) -> str:
    return "".join(token[0] for token in _norm(value).split())


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


async def _load_skills(db: AsyncSession) -> dict[uuid.UUID, SkillInfo]:
    rows = (await db.execute(select(Skill))).scalars().all()
    keys = {row.id: row.key for row in rows}
    return {
        row.id: SkillInfo(
            id=row.id,
            key=row.key,
            label=row.label,
            aliases=tuple(row.aliases or []),
            category=row.category,
            parent_key=keys.get(row.parent_id) if row.parent_id else None,
            status=row.status,
            origin=row.origin,
            created_at=_aware(row.created_at),
            provenance=row.provenance or {},
        )
        for row in rows
    }


async def _settled_pairs(db: AsyncSession) -> set[frozenset[uuid.UUID]]:
    rows = (await db.execute(select(SkillRelation.from_skill_id, SkillRelation.to_skill_id))).all()
    return {frozenset((row.from_skill_id, row.to_skill_id)) for row in rows}


async def _cooccurrence(
    db: AsyncSession,
) -> tuple[
    dict[tuple[uuid.UUID, uuid.UUID], dict],
    dict[uuid.UUID, list[tuple[uuid.UUID, datetime | None]]],
]:
    pairs: dict[tuple[uuid.UUID, uuid.UUID], dict] = {}
    postings: dict[uuid.UUID, list[tuple[uuid.UUID, datetime | None]]] = {}
    for model, doc_name, count_key in (
        (PostingSkill, "posting_id", "postings"),
        (JobSkill, "job_id", "jobs"),
    ):
        doc_col = getattr(model, doc_name)
        rows = (
            await db.execute(select(doc_col, model.skill_id, model.created_at, model.updated_at))
        ).all()
        by_doc: dict[uuid.UUID, list[tuple[uuid.UUID, datetime | None]]] = {}
        for row in rows:
            by_doc.setdefault(row[0], []).append(
                (row[1], max(filter(None, (row[2], row[3])), default=None))
            )
        if doc_name == "posting_id":
            postings = by_doc
        for tagged in by_doc.values():
            for (skill_a, ts_a), (skill_b, ts_b) in combinations(tagged, 2):
                if skill_a == skill_b:
                    continue
                key = (skill_a, skill_b) if str(skill_a) <= str(skill_b) else (skill_b, skill_a)
                stats = pairs.setdefault(key, {"postings": 0, "jobs": 0, "last_seen": None})
                stats[count_key] += 1
                for ts in (ts_a, ts_b):
                    ts = _aware(ts)
                    if ts is not None and (stats["last_seen"] is None or ts > stats["last_seen"]):
                        stats["last_seen"] = ts
    return pairs, postings


def _label_pairs(
    skills: dict[uuid.UUID, SkillInfo],
    postings: dict[uuid.UUID, list[tuple[uuid.UUID, datetime | None]]],
) -> list[tuple[SkillInfo, SkillInfo, dict, float, datetime | None]]:
    proposed = [
        s
        for s in skills.values()
        if s.status == SkillStatus.PROPOSED.value
        and s.origin == SkillOrigin.AI.value
        and s.provenance
    ]
    active = [s for s in skills.values() if s.status == SkillStatus.ACTIVE.value]
    out: list[tuple[SkillInfo, SkillInfo, dict, float, datetime | None]] = []
    for candidate in proposed:
        cand_strings = {_norm(candidate.key), _norm(candidate.label)} - {""}
        seen: set[uuid.UUID] = set()
        for skill in active:
            skill_strings = {
                _norm(skill.key),
                _norm(skill.label),
                *(_norm(a) for a in skill.aliases),
            } - {""}
            if cand_strings & skill_strings:
                out.append(
                    (
                        candidate,
                        skill,
                        {"label_match": {"kind": "equal"}},
                        3.0,
                        candidate.created_at,
                    )
                )
                seen.add(skill.id)
            elif _initialism_match(cand_strings, skill_strings):
                out.append(
                    (
                        candidate,
                        skill,
                        {"label_match": {"kind": "initialism"}},
                        2.5,
                        candidate.created_at,
                    )
                )
                seen.add(skill.id)
        posting_id = str(candidate.provenance.get("posting_id") or "")
        try:
            origin_doc = uuid.UUID(posting_id)
        except ValueError:
            continue
        for tagged_id, ts in postings.get(origin_doc, []):
            tagged = skills.get(tagged_id)
            if tagged is None or tagged.id == candidate.id or tagged.id in seen:
                continue
            last_seen = max(filter(None, (candidate.created_at, _aware(ts))), default=None)
            out.append(
                (
                    candidate,
                    tagged,
                    {"label_match": {"kind": "co_tag"}},
                    2.0,
                    last_seen,
                )
            )
    return out


def _initialism_match(first: set[str], second: set[str]) -> bool:
    for a in first:
        for b in second:
            if a == b:
                continue
            a_tokens, b_tokens = a.split(), b.split()
            if len(a_tokens) == 1 and len(b_tokens) >= 2 and _initialism(b) == a:
                return True
            if len(b_tokens) == 1 and len(a_tokens) >= 2 and _initialism(a) == b:
                return True
    return False


async def collect_candidates(
    db: AsyncSession,
    *,
    since: datetime | None = None,
    thresholds: Thresholds | None = None,
) -> tuple[list[RelationCandidate], bool]:
    """Ranked, adjudicable (pair, hypothesis) candidates; ``capped`` flag.

    Signals: co-occurrence (hypothesis ``related_to``), proposed-label
    matching (``synonym``), both bounded by ``min_support``/freshness and
    ordered by evidence strength. Pairs with any existing relation row are
    never returned (pair-level adjudication).
    """
    thresholds = thresholds or Thresholds()
    skills = await _load_skills(db)
    settled = await _settled_pairs(db)
    cooccurrence, postings = await _cooccurrence(db)

    merged: dict[frozenset[uuid.UUID], RelationCandidate] = {}

    def offer(first: SkillInfo, second: SkillInfo, hypothesis, signals, strength, last_seen):
        key = frozenset((first.id, second.id))
        if len(key) < 2 or key in settled:
            return
        last_seen = _aware(last_seen)
        existing = merged.get(key)
        if existing is None:
            merged[key] = RelationCandidate(
                pair_ref="",
                first=first,
                second=second,
                hypothesis=hypothesis,
                signals=signals,
                strength=strength,
                last_seen=last_seen,
            )
            return
        existing.signals.update(signals)
        if strength > existing.strength:
            existing.hypothesis = hypothesis
            existing.strength = strength
        if last_seen is not None and (existing.last_seen is None or last_seen > existing.last_seen):
            existing.last_seen = last_seen

    for (id_a, id_b), stats in cooccurrence.items():
        support = stats["postings"] + stats["jobs"]
        if support < thresholds.min_support:
            continue
        first, second = sorted((skills[id_a], skills[id_b]), key=lambda s: s.key)
        offer(
            first,
            second,
            SkillRelationType.RELATED_TO,
            {"cooccurrence": {"postings": stats["postings"], "jobs": stats["jobs"]}},
            1.0 + 0.1 * support,
            stats["last_seen"],
        )

    for cand, skill, signals, strength, last_seen in _label_pairs(skills, postings):
        first, second = sorted((cand, skill), key=lambda s: s.key)
        offer(first, second, SkillRelationType.SYNONYM, signals, strength, last_seen)

    fresh = [
        candidate
        for candidate in merged.values()
        if since is None or candidate.last_seen is None or candidate.last_seen > since
    ]
    ranked = sorted(fresh, key=lambda c: (-c.strength, c.first.key, c.second.key))
    capped = len(ranked) > thresholds.max_pairs_per_run
    kept = ranked[: thresholds.max_pairs_per_run]
    for index, candidate in enumerate(kept):
        candidate.pair_ref = f"p{index + 1}"
    return kept, capped


async def materialize_parent_edges(db: AsyncSession) -> int:
    """Curated ``parent_id`` links → auto-approved ``is_a`` edges (import).

    Skipped whenever an ``is_a`` row already exists for the pair in any
    status (a rejection is final). Expansion-neutral: the curated subtree
    already reaches these pairs at zero cost.
    """
    service = SkillRelationService(db)
    skills = await _load_skills(db)
    by_key = {info.key: info for info in skills.values()}
    existing = (
        await db.execute(
            select(SkillRelation.from_skill_id, SkillRelation.to_skill_id).where(
                SkillRelation.relation == SkillRelationType.IS_A.value
            )
        )
    ).all()
    covered = {frozenset((row.from_skill_id, row.to_skill_id)) for row in existing}
    count = 0
    for info in sorted(skills.values(), key=lambda s: s.key):
        parent = by_key.get(info.parent_key) if info.parent_key else None
        if parent is None:
            continue
        if frozenset((info.id, parent.id)) in covered:
            continue
        try:
            await service.add(
                info.id,
                parent.id,
                SkillRelationType.IS_A,
                source=SkillRelationSource.IMPORT,
                evidence={"signals": {"parent_chain": {"parent_key": parent.key}}},
            )
        except (NotFoundError, ValidationError):
            continue
        covered.add(frozenset((info.id, parent.id)))
        count += 1
    return count


def _evidence(verdict: SkillEdgeVerdict | None, signals: dict) -> dict:
    payload: dict = {"signals": signals}
    if verdict is not None:
        payload["rationale"] = verdict.rationale
    payload["prompt_version"] = prompt_version(AITaskType.SKILL_RELATION_SUGGEST.value)
    return payload


def _prompt_pair(candidate: RelationCandidate) -> dict:
    return {
        "pair_ref": candidate.pair_ref,
        "hypothesis": candidate.hypothesis.value,
        "signals": candidate.signals,
        "skills": [
            {
                "key": info.key,
                "label": info.label,
                "aliases": list(info.aliases),
                "category": info.category,
                "parent_key": info.parent_key,
            }
            for info in (candidate.first, candidate.second)
        ],
    }


async def apply_verdicts(
    db: AsyncSession,
    candidates: list[RelationCandidate],
    verdicts: list[SkillEdgeVerdict],
    *,
    thresholds: Thresholds | None = None,
) -> dict:
    """Land one batch of verdicts through the write seam.

    Non-``none`` verdicts land ``proposed`` llm rows (the verdict's relation
    wins over the hypothesis — the redirect); ``none`` pins the cheap early
    negative for the *hypothesized* relation above the confidence bar.
    Verdicts that fail semantic validation are dropped, never trusted.
    """
    thresholds = thresholds or Thresholds()
    service = SkillRelationService(db)
    by_ref = {candidate.pair_ref: candidate for candidate in candidates}
    stats = {"edges_proposed": 0, "negatives": 0, "dropped": 0, "below_bar": 0}
    seen: set[str] = set()
    for verdict in verdicts:
        candidate = by_ref.get(verdict.pair_ref)
        if candidate is None or verdict.pair_ref in seen:
            stats["dropped"] += 1
            continue
        seen.add(verdict.pair_ref)
        if verdict.relation == "none":
            if verdict.confidence < thresholds.min_negative_confidence:
                stats["below_bar"] += 1
                continue
            try:
                await service.add(
                    candidate.first.id,
                    candidate.second.id,
                    candidate.hypothesis,
                    source=SkillRelationSource.LLM,
                    status=SkillRelationStatus.REJECTED,
                    confidence=verdict.confidence,
                    evidence=_evidence(verdict, candidate.signals),
                )
            except ValidationError:
                stats["dropped"] += 1
                continue
            stats["negatives"] += 1
            continue
        kind = SkillRelationType(verdict.relation)
        if kind.is_directed:
            if verdict.subject_key == candidate.first.key:
                source_skill, target_skill = candidate.first, candidate.second
            elif verdict.subject_key == candidate.second.key:
                source_skill, target_skill = candidate.second, candidate.first
            else:
                stats["dropped"] += 1
                continue
        else:
            source_skill, target_skill = candidate.first, candidate.second
        try:
            await service.add(
                source_skill.id,
                target_skill.id,
                kind,
                source=SkillRelationSource.LLM,
                confidence=verdict.confidence,
                evidence=_evidence(verdict, candidate.signals),
            )
        except ValidationError:
            stats["dropped"] += 1
            continue
        stats["edges_proposed"] += 1
    return stats


async def apply_derived(db: AsyncSession, candidates: list[RelationCandidate]) -> int:
    """The unconfigured fallback: deterministic candidates still flow."""
    service = SkillRelationService(db)
    count = 0
    for candidate in candidates:
        try:
            await service.add(
                candidate.first.id,
                candidate.second.id,
                candidate.hypothesis,
                source=SkillRelationSource.DERIVED,
                evidence=_evidence(None, candidate.signals),
            )
        except ValidationError:
            continue
        count += 1
    return count


async def _load_watermark(db: AsyncSession) -> datetime | None:
    row = (
        (
            await db.execute(
                select(BackgroundJob)
                .where(
                    BackgroundJob.job_type == BackgroundJobType.SKILL_RELATION_LEARN.value,
                    BackgroundJob.status == BackgroundJobStatus.SUCCEEDED.value,
                )
                .order_by(BackgroundJob.created_at.desc())
                .limit(1)
            )
        )
        .scalars()
        .first()
    )
    if row is None:
        return None
    raw = (row.result or {}).get("watermark")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw))
    except ValueError:
        return None


async def run_skill_relation_learn(
    db: AsyncSession,
    *,
    run_id: uuid.UUID | None = None,
    cancelled: Callable[[], Awaitable[bool]] | None = None,
) -> dict:
    """One discovery run: materialize, collect, judge, write, report.

    Never raises for AI problems: an unconfigured provider falls back to
    derived proposals; failed, incomplete or cancelled batches are left
    unadjudicated and the held watermark re-picks them next run.
    """
    thresholds = await load_thresholds(db)
    since = await _load_watermark(db)
    collected_at = datetime.now(UTC)
    materialized = await materialize_parent_edges(db)
    candidates, capped = await collect_candidates(db, since=since, thresholds=thresholds)
    batch_size = thresholds.batch_size
    batches = [candidates[i : i + batch_size] for i in range(0, len(candidates), batch_size)]
    run_ref = RunRef(id=run_id, stage="skill_relation_learn.verdict") if run_id else None
    judged = failed = uncovered = 0
    unconfigured = False
    applied = {"edges_proposed": 0, "negatives": 0, "dropped": 0, "below_bar": 0}
    for batch in batches:
        if cancelled is not None and await cancelled():
            break
        try:
            verdict_set: SkillEdgeVerdictSet | None = await suggest_skill_edges(
                db, [_prompt_pair(candidate) for candidate in batch], run=run_ref
            )
        except AINotConfiguredError:
            unconfigured = True
            break
        if verdict_set is None:
            failed += 1
            continue
        judged += 1
        batch_stats = await apply_verdicts(db, batch, verdict_set.verdicts, thresholds=thresholds)
        for key, value in batch_stats.items():
            applied[key] += value
        answered = {verdict.pair_ref for verdict in verdict_set.verdicts}
        uncovered += sum(1 for candidate in batch if candidate.pair_ref not in answered)
    derived = 0
    if unconfigured and judged == 0:
        derived = await apply_derived(db, candidates)
    leftover = capped or failed > 0 or uncovered > 0 or (unconfigured and judged > 0)
    watermark = since if leftover else collected_at
    return {
        "materialized": materialized,
        "candidates": len(candidates),
        "batches": len(batches),
        "judged_batches": judged,
        "failed_batches": failed,
        "uncovered": uncovered,
        "derived": derived,
        **applied,
        "capped": capped,
        "watermark": watermark.isoformat() if watermark else None,
    }
