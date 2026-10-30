"""Autopilot flow — the AI-activated search as a LangGraph
StateGraph.

Nodes do one thing each: an LLM step is one audited gateway call
(``AITaskType.AUTOPILOT_RUN``), every other node is deterministic work.
The graph is checkpointed (``thread_id`` = run id), so a worker crash
resumes from the last completed node via ``ainvoke(None, config)``; a
budget abort routes straight to ``deliver`` so partial findings still
ship. Three recall sources feed one pool (keyword variants, a semantic
sweep over stored embeddings, a curated job-relation sweep), every source
behind the same deterministic gates; final ordering is deterministic
(must-term coverage, then fit) — the LLM curates, math ranks. There is no
auto-apply node: findings are suggestions, applying stays a user click.
"""

import json
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, TypedDict
from uuid import UUID

from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.gateway import ainvoke_structured, register_mock_fixture
from app.ai.schemas import Curation, SearchPlan
from app.core.errors import sanitize_error_detail
from app.models.ai_model import AIGeneration
from app.models.enums import AITaskType, AutopilotRunStatus, SkillExpandMode
from app.services.postings.explore_service import (
    ALLOWED_FILTER_KEYS,
    BENEFIT_KIND_VALUES,
    OPEN_STATUSES,
    POSTED_WINDOWS,
    REMOTE_VALUES,
    SCHEDULE_CUE_VALUES,
    SENIORITY_VALUES,
    SKILL_EXPAND_MODES,
    explore,
    parse_explore_filters,
)

logger = logging.getLogger(__name__)

CURATOR_POOL_MIN = 12
CURATOR_POOL_FACTOR = 3
CANDIDATE_CAP = 120
DEFAULT_TOP_N = 5
DEFAULT_COOLDOWN_DAYS = 7
SEARCH_LIMIT = 40
SNIPPET_CHARS = 600
SEMANTIC_K = 60
SEARCH_VARIANTS = 6
REPLAN_LIMIT = 1
GRAPH_SEEDS = 3
GRAPH_NEIGHBORS = 6

PROFILE_SKILL_LIMIT = 12
PLAN_SKILL_LIMIT = 40
PLAN_FAMILY_LIMIT = 40
PLAN_SOURCE_LIMIT = 20
SKILL_GRAPH_HOPS = 1


def curator_pool(top_n: int | None = None) -> int:
    """The curated pool size: wide enough that a must-term-perfect
    candidate at fit-rank 13 is still visible."""
    return max(CURATOR_POOL_MIN, CURATOR_POOL_FACTOR * int(top_n or DEFAULT_TOP_N))


ProgressCb = Callable[[int, str], Awaitable[None]]
CancelCb = Callable[[], Awaitable[bool]]


class AutopilotState(TypedDict, total=False):
    """Checkpointed working state (serializable — a run resumes from it)."""

    user_id: str
    goal_id: str
    run_id: str
    goal_text: str
    constraints: dict
    budget: dict
    started_at: str
    cooldown_cutoff: str
    top_n: int
    profile_context: dict
    plan: dict
    searches: list
    candidates: list
    replan_attempts: int
    replans: list
    progress_pct: int
    curation: dict
    findings: list
    abort_reason: str
    error: str
    tokens_used: int


@dataclass
class GraphDeps:
    """Per-invocation dependencies (never checkpointed)."""

    db: AsyncSession
    progress: ProgressCb | None = None
    cancelled: CancelCb | None = None
    cooldown_ids: set[str] = field(default_factory=set)


# ------------------------------------------------------------------ helpers


def _utcnow() -> datetime:
    return datetime.now(UTC)


async def _report(deps: GraphDeps, pct: int, stage: str) -> None:
    if deps.progress is not None:
        await deps.progress(pct, stage)


async def _is_cancelled(deps: GraphDeps) -> bool:
    if deps.cancelled is None:
        return False
    try:
        return bool(await deps.cancelled())
    except Exception:
        return False


def _constraints(state: AutopilotState) -> dict:
    return state.get("constraints") or {}


async def _ledger_usage(db: AsyncSession, user_id: str, since: datetime) -> tuple[int, int]:
    """(tokens, calls) this user's autopilot task consumed since ``since``.

    The audit ledger is the single source of spend — the same source the
    budgets enforce; the run-level cap is layered over it.
    """
    rows = await db.execute(
        select(
            func.count(AIGeneration.id),
            func.coalesce(func.sum(AIGeneration.tokens_in), 0)
            + func.coalesce(func.sum(AIGeneration.tokens_out), 0),
        ).where(
            AIGeneration.user_id == UUID(user_id),
            AIGeneration.task_type == AITaskType.AUTOPILOT_RUN.value,
            AIGeneration.status == "ok",
            AIGeneration.created_at >= since,
        )
    )
    calls, tokens = rows.one()
    return int(tokens or 0), int(calls or 0)


def _plan_system() -> str:
    return (
        "You are a career-search planner. Design 2-5 diverse search "
        "variants to find vacancies matching the user's goal. Each variant "
        "has optional explore filters drawn ONLY from the allowed filter "
        "keys, and its text goes in `keywords` (a LIST — any of them may "
        "match a title or employer) or `q` (ONE exact phrase matched "
        "against title and employer only); multi-word concepts always go "
        "to `keywords`, never to `q`. "
        f"Allowed filter keys: {', '.join(sorted(ALLOWED_FILTER_KEYS))}. "
        f"seniority values: {', '.join(SENIORITY_VALUES)}; "
        f"remote_policy values: {', '.join(REMOTE_VALUES)}; "
        f"posted_within values: {', '.join(POSTED_WINDOWS)}; "
        f"schedule cues: {', '.join(SCHEDULE_CUE_VALUES)}; "
        f"benefit kinds: {', '.join(BENEFIT_KIND_VALUES)}; "
        f"skill_expand values: {', '.join(SKILL_EXPAND_MODES)}; "
        "skill_mode values: all, any. "
        "Vary scope (broad vs niche, different skill emphases) and prefer "
        "skill keys from the user's own skill neighbourhood. Honor every "
        "never-term (never search for it) and must-term. Respond with JSON "
        "only."
    )


def _plan_user_prompt(state: AutopilotState, vocabulary: dict | None = None) -> str:
    c = _constraints(state)
    vocab = vocabulary or {}
    return json.dumps(
        {
            "goal": state.get("goal_text", ""),
            "must_terms": c.get("must_terms") or [],
            "never_terms": c.get("never_terms") or [],
            "target_families": c.get("family_keys") or [],
            "remote": c.get("remote"),
            "salary_min": c.get("salary_min"),
            "seniority": c.get("seniority") or [],
            "profile_context": state.get("profile_context") or {},
            "valid_filter_keys": sorted(ALLOWED_FILTER_KEYS),
            "skill_keys": vocab.get("skills") or [],
            "family_keys": vocab.get("families") or [],
            "source_keys": vocab.get("sources") or [],
        },
        ensure_ascii=False,
    )


async def collect_profile_context(db: AsyncSession, user_id: UUID, constraints: dict) -> dict:
    """The planner's small profile dict: skills with levels, education,
    location and the goal's target seniority.

    A dict composer over existing queries — no new profile modeling, the
    same ``SkillService.user_skills`` the profile surfaces read.
    """
    from app.services.catalog.skills_service import SkillService
    from app.services.deps import get_profile_for_user

    profile = await get_profile_for_user(db, user_id)
    basics = profile.basics or {}
    skills = [
        {"key": row.skill.key, "level": int(row.level)}
        for row in await SkillService(db).user_skills(user_id)
        if row.skill is not None
    ][:PROFILE_SKILL_LIMIT]
    return {
        "skills": skills,
        "education_level": basics.get("education_level"),
        "country": basics.get("country") or None,
        "city": basics.get("city") or None,
        "target_seniority": [str(value) for value in constraints.get("seniority") or []],
    }


async def plan_vocabulary(db: AsyncSession, user_id: UUID) -> dict:
    """The planner's skill/family/source vocabulary (plan 158 S1.2).

    The user's own skills and their 1-hop curated graph neighbourhood
    (synonyms + subtree + ``is_a`` children, ``down`` mode) come FIRST,
    then top-by-posting-frequency keys pad the list to ``PLAN_SKILL_LIMIT``.
    """
    from app.models.job_model import JobFamily
    from app.models.posting_model import JobPosting, JobSource, PostingSkill
    from app.models.taxonomy_model import Skill
    from app.services.catalog.skill_relations import SkillRelationService
    from app.services.catalog.skills_service import SkillService

    keys: list[str] = []
    for row in await SkillService(db).user_skills(user_id):
        key = row.skill.key if row.skill is not None else None
        if key and key not in keys:
            keys.append(key)
    own_ids = set((await db.execute(select(Skill.id).where(Skill.key.in_(keys)))).scalars().all())
    if own_ids:
        graph = await SkillRelationService(db).load_graph()
        reached = graph.expand(own_ids, mode=SkillExpandMode.DOWN, hops=SKILL_GRAPH_HOPS)
        for key in sorted(graph.keys_for(reached)):
            if key not in keys:
                keys.append(key)
    families = list(
        (await db.execute(select(JobFamily.key).order_by(JobFamily.key))).scalars().all()
    )
    sources = list(
        (
            await db.execute(
                select(JobSource.key).where(JobSource.enabled.is_(True)).order_by(JobSource.key)
            )
        )
        .scalars()
        .all()
    )
    if len(keys) < PLAN_SKILL_LIMIT:
        open_postings = select(JobPosting.id).where(JobPosting.status.in_(OPEN_STATUSES))
        frequent = await db.execute(
            select(Skill.key)
            .join(PostingSkill, PostingSkill.skill_id == Skill.id)
            .where(PostingSkill.posting_id.in_(open_postings))
            .group_by(Skill.key)
            .order_by(func.count(PostingSkill.posting_id).desc(), Skill.key)
            .limit(PLAN_SKILL_LIMIT)
        )
        for key in frequent.scalars().all():
            if len(keys) >= PLAN_SKILL_LIMIT:
                break
            if key not in keys:
                keys.append(key)
    return {
        "skills": keys[:PLAN_SKILL_LIMIT],
        "families": families[:PLAN_FAMILY_LIMIT],
        "sources": sources[:PLAN_SOURCE_LIMIT],
    }


def _replan_system() -> str:
    return (
        "You are a career-search planner recovering from a thin first pass. "
        "Broaden: relax or drop the text query, widen family/seniority scope, "
        "and keep every never-term (never search for it). Filters stay inside "
        "the explore vocabulary listed here: "
        f"{', '.join(sorted(ALLOWED_FILTER_KEYS))}. "
        f"skill_expand values: {', '.join(SKILL_EXPAND_MODES)}; "
        "skill_mode values: all, any. Put multi-word concepts in "
        "`keywords` (a LIST — any may match a title or employer), never in `q`. "
        "Design 1-3 genuinely different variants for the SAME goal. Respond "
        "with JSON only."
    )


def _replan_user_prompt(
    state: AutopilotState, previous: list[dict], vocabulary: dict | None = None
) -> str:
    c = _constraints(state)
    vocab = vocabulary or {}
    return json.dumps(
        {
            "goal": state.get("goal_text", ""),
            "previous_variants": [
                {
                    "query": entry.get("query") or "",
                    "filters": entry.get("filters") or {},
                    "found": int(entry.get("found") or 0),
                }
                for entry in previous
            ],
            "must_terms": c.get("must_terms") or [],
            "never_terms": c.get("never_terms") or [],
            "target_families": c.get("family_keys") or [],
            "seniority": c.get("seniority") or [],
            "profile_context": state.get("profile_context") or {},
            "valid_filter_keys": sorted(ALLOWED_FILTER_KEYS),
            "skill_keys": vocab.get("skills") or [],
            "family_keys": vocab.get("families") or [],
            "source_keys": vocab.get("sources") or [],
        },
        ensure_ascii=False,
    )


def _curate_system(top_n: int) -> str:
    return (
        f"You are a job-search curator. From the candidate postings, pick "
        f"the best {top_n} for the user's goal and explain each in 1-3 "
        f"sentences. Ground EVERY claim in the candidate's provided fields "
        f"(fit score, breakdown, skills, responsibilities, snippet); never "
        f"invent requirements or benefits. Weigh must_hits against "
        f"must_total: covering the user's must-terms outranks a higher fit "
        f"score without them. Include 1-2 short verbatim quotes copied "
        f"exactly from that candidate's own text (snippet, "
        f"responsibilities). Prefer higher fit_score at equal coverage; "
        f"skip noise. Respond with JSON only."
    )


def _curate_user_prompt(state: AutopilotState, pool: list[dict]) -> str:
    c = _constraints(state)
    must_total = len(_must_terms(state))
    return json.dumps(
        {
            "goal": state.get("goal_text", ""),
            "must_terms": c.get("must_terms") or [],
            "never_terms": c.get("never_terms") or [],
            "candidates": [
                {
                    "index": index,
                    "title": cand.get("title"),
                    "org": cand.get("org"),
                    "location": cand.get("location") or {},
                    "seniority": cand.get("seniority"),
                    "salary_min": cand.get("salary_min"),
                    "salary_currency": cand.get("salary_currency"),
                    "posted_at": cand.get("posted_at"),
                    "fit_score": cand.get("fit"),
                    "fit_breakdown": cand.get("breakdown") or {},
                    "must_hits": int(cand.get("must_hits") or 0),
                    "must_total": must_total,
                    "skills": cand.get("skills") or [],
                    "responsibilities": cand.get("responsibilities") or [],
                    "description_snippet": cand.get("snippet") or "",
                }
                for index, cand in enumerate(pool)
            ],
        },
        ensure_ascii=False,
    )


def _deterministic_why(candidate: dict) -> str:
    """LLM-free fallback explanation grounded in the fit breakdown."""
    parts = []
    for name, dim in list((candidate.get("breakdown") or {}).items())[:3]:
        if isinstance(dim, dict) and dim.get("score") is not None:
            parts.append(f"{str(name).replace('_', ' ')} {float(dim['score']):.1f}/10")
    why = f"Fit {float(candidate.get('fit') or 0):.1f}/10"
    if parts:
        why += f" ({', '.join(parts)})"
    skills = [s.get("key", "") for s in candidate.get("skills") or [] if isinstance(s, dict)]
    top = [key for key in skills[:3] if key]
    if top:
        why += f"; looking for {', '.join(top)}"
    return why[:1200]


def _must_terms(state: AutopilotState) -> list[str]:
    return [
        str(term).strip().casefold()
        for term in _constraints(state).get("must_terms") or []
        if str(term).strip()
    ]


def _candidate_texts(candidate: dict) -> str:
    """All text a quote may come from (the quote-verification corpus)."""
    skills = " ".join(
        str(s.get("key", "")) for s in candidate.get("skills") or [] if isinstance(s, dict)
    )
    duties = " ".join(str(r) for r in candidate.get("responsibilities") or [])
    return " ".join(
        filter(
            None,
            [
                candidate.get("title") or "",
                candidate.get("org") or "",
                candidate.get("snippet") or "",
                skills,
                duties,
            ],
        )
    ).casefold()


def _verify_quotes(candidate: dict, quotes: list) -> list[str]:
    corpus = _candidate_texts(candidate)
    verified = []
    for quote in quotes or []:
        text = " ".join(str(quote).split())
        if text and text.casefold() in corpus:
            verified.append(text)
    return verified[:5]


def _serialize_candidate(item: dict) -> dict | None:
    """JSON-safe candidate dict (checkpoint state) with evidence fields."""
    posting = item.get("posting")
    if posting is None or item.get("fit") is None:
        return None
    extract = posting.extract or {}
    skills = [
        {
            "key": s.get("key") or s.get("skill_key"),
            "level": s.get("level") or s.get("required_level"),
            "priority": s.get("priority"),
        }
        for s in extract.get("skills") or []
        if isinstance(s, dict)
    ][:10]
    responsibilities = [
        (r.get("text") if isinstance(r, dict) else str(r)) or ""
        for r in extract.get("responsibilities") or []
    ][:5]
    salary_min = posting.salary_min
    salary_max = posting.salary_max
    if salary_min is None and isinstance(extract.get("salary"), dict):
        salary_min = extract["salary"].get("min")
        salary_max = extract["salary"].get("max")
    description = str((posting.raw or {}).get("description") or "")
    interaction = item.get("interaction")
    application = item.get("application")
    return {
        "posting_id": str(posting.id),
        "catalog_job_id": str(posting.catalog_job_id) if posting.catalog_job_id else None,
        "ref": posting.ref,
        "title": posting.title,
        "org": posting.org,
        "location": posting.location or {},
        "url": posting.url or "",
        "seniority": posting.seniority,
        "salary_min": float(salary_min) if salary_min is not None else None,
        "salary_max": float(salary_max) if salary_max is not None else None,
        "salary_currency": posting.salary_currency,
        "posted_at": posting.posted_at.isoformat() if posting.posted_at else None,
        "fit": round(float(item["fit"]), 2),
        "skills": skills,
        "responsibilities": responsibilities,
        "snippet": " ".join(description.split())[:SNIPPET_CHARS],
        "extracted": posting.extract_version is not None,
        "seen_at": (
            interaction.seen_at.isoformat()
            if interaction is not None and interaction.seen_at
            else None
        ),
        "applied_at": (
            application.applied_at.isoformat()
            if application is not None and application.applied_at
            else None
        ),
        "hidden_at": (
            interaction.hidden_at.isoformat()
            if interaction is not None and interaction.hidden_at
            else None
        ),
    }


# -------------------------------------------------------------------- nodes


async def _gated_rows(
    deps: GraphDeps,
    state: AutopilotState,
    *,
    posting_ids: list[UUID] | None = None,
    catalog_job_ids: list[UUID] | None = None,
    exclude_ids: set[str] | None = None,
) -> list[tuple]:
    """Postings (with the caller's interaction/application) that pass the
    deterministic gates every recall source shares: open status, the
    exclude-seen axes, the per-goal cooldown. Never-terms are judged on
    the serialized candidate text (``_candidate_texts``).
    """
    from app.models.application_model import Application
    from app.models.posting_model import JobPosting, PostingInteraction

    if not posting_ids and not catalog_job_ids:
        return []
    user_id = UUID(state["user_id"])
    exclude_seen = _constraints(state).get("exclude_seen", True)
    query = select(JobPosting, PostingInteraction, Application).outerjoin(
        PostingInteraction,
        (PostingInteraction.posting_id == JobPosting.id) & (PostingInteraction.user_id == user_id),
    )
    query = query.outerjoin(
        Application,
        (Application.posting_id == JobPosting.id) & (Application.user_id == user_id),
    )
    if posting_ids:
        query = query.where(JobPosting.id.in_(posting_ids))
    if catalog_job_ids:
        query = query.where(JobPosting.catalog_job_id.in_(catalog_job_ids))
    rows = (await deps.db.execute(query)).all()
    excluded = exclude_ids or set()
    fresh: list[tuple] = []
    for posting, interaction, application in rows:
        if posting.status not in OPEN_STATUSES:
            continue
        if str(posting.id) in excluded or str(posting.id) in deps.cooldown_ids:
            continue
        if exclude_seen and (
            (interaction is not None and (interaction.seen_at or interaction.hidden_at))
            or application is not None
        ):
            continue
        fresh.append((posting, interaction, application))
    return fresh


async def _scored_candidates(
    deps: GraphDeps, state: AutopilotState, rows: list[tuple]
) -> list[dict]:
    """Serialize loaded rows into candidates: batch-cached fit, no
    never-term hits, must-term coverage."""
    from app.services.postings.posting_fit_service import get_posting_fits_batch

    if not rows:
        return []
    fits = await get_posting_fits_batch(deps.db, UUID(state["user_id"]), [row[0] for row in rows])
    never_terms = [str(term).casefold() for term in _constraints(state).get("never_terms") or []]
    must_terms = _must_terms(state)
    scored: list[dict] = []
    for posting, interaction, application in rows:
        fit = fits.get(posting.id) or {}
        candidate = _serialize_candidate(
            {
                "posting": posting,
                "interaction": interaction,
                "application": application,
                "fit": fit.get("score"),
            }
        )
        if candidate is None:
            continue
        if fit.get("breakdown") is not None:
            candidate["breakdown"] = fit["breakdown"]
        haystack = _candidate_texts(candidate)
        if any(term and term in haystack for term in never_terms):
            continue
        candidate["must_hits"] = sum(1 for term in must_terms if term in haystack)
        scored.append(candidate)
    return scored


def _merge_candidates(best: dict[str, dict], candidates: list[dict]) -> int:
    """Dedupe by posting id, keeping the higher fit; returns the number of
    newly added postings."""
    merged = 0
    for candidate in candidates:
        key = str(candidate["posting_id"])
        existing = best.get(key)
        if existing is None:
            best[key] = candidate
            merged += 1
        elif float(candidate.get("fit") or 0) > float(existing.get("fit") or 0):
            best[key] = candidate
    return merged


def _cap_candidates(candidates: list[dict]) -> list[dict]:
    """Bound the checkpointed working set: the merge pool can reach a few
    hundred postings, and candidates ride every checkpoint write. The cap
    sits far above the curator pool, so the cut is invisible to curation."""
    if len(candidates) <= CANDIDATE_CAP:
        return candidates
    ordered = sorted(
        candidates,
        key=lambda c: (float(c.get("fit") or 0), str(c.get("posting_id") or "")),
        reverse=True,
    )
    return ordered[:CANDIDATE_CAP]


async def _semantic_sweep(deps: GraphDeps, state: AutopilotState, best: dict[str, dict]) -> dict:
    """One prediction-free recall pass over the stored posting embeddings.

    A candidate GENERATOR, never a filter: every hit passes the same
    deterministic gates as the lexical variants before it enters the pool,
    and any embedding failure degrades to lexical-only (ADR-0012 §13).
    """
    entry = {
        "step": "search",
        "query": "",
        "filters": {},
        "rationale": "semantic sweep over stored posting embeddings",
        "found": 0,
        "examined": 0,
        "error": "",
    }
    try:
        from app.services.embedding_service import KIND_POSTING, EmbeddingService

        query = " ".join([state.get("goal_text") or "", *_must_terms(state)]).strip()
        hits = await EmbeddingService(deps.db).search_similar(
            query, kind=KIND_POSTING, limit=SEMANTIC_K
        )
        ids = [UUID(hit["entity_id"]) for hit in hits if float(hit.get("score") or 0) > 0]
        rows = await _gated_rows(deps, state, posting_ids=ids)
        entry["examined"] = len(rows)
        candidates = await _scored_candidates(deps, state, rows)
        entry["found"] = _merge_candidates(best, candidates)
    except Exception as exc:
        logger.warning("autopilot semantic sweep degraded", exc_info=True)
        entry["error"] = sanitize_error_detail(f"{type(exc).__name__}: {exc}")
    return entry


def make_plan_node(deps: GraphDeps):
    async def plan(state: AutopilotState) -> dict:
        """LLM step 1: goal + constraints + profile context + the explore
        vocabulary → SearchPlan."""
        try:
            try:
                vocabulary = await plan_vocabulary(deps.db, UUID(state["user_id"]))
            except Exception:
                logger.warning("autopilot vocabulary collection failed", exc_info=True)
                vocabulary = {}
            result = await ainvoke_structured(
                deps.db,
                AITaskType.AUTOPILOT_RUN,
                SearchPlan,
                system=_plan_system(),
                user=_plan_user_prompt(state, vocabulary),
                user_id=UUID(state["user_id"]),
            )
            return {"plan": result.model_dump(mode="json")}
        except Exception as exc:
            lowered = str(exc).lower()
            reason = "budget" if "budget" in lowered or "rate limit" in lowered else "error"
            return {"abort_reason": reason, "error": f"{type(exc).__name__}: {exc}"}

    return plan


def make_guard_node(deps: GraphDeps):
    async def budget_guard(state: AutopilotState) -> dict:
        """Cancellation + the run-level cap, layered over ai_budgets."""
        if await _is_cancelled(deps):
            return {"abort_reason": "cancelled"}
        budget = state.get("budget") or {}
        max_tokens = int(budget.get("max_tokens") or 0)
        max_calls = int(budget.get("max_calls") or 0)
        if not max_tokens and not max_calls:
            return {}
        try:
            since = datetime.fromisoformat(state["started_at"])
        except (KeyError, ValueError):
            return {}
        tokens, calls = await _ledger_usage(deps.db, state["user_id"], since)
        over = (max_tokens and tokens > max_tokens) or (max_calls and calls >= max_calls)
        if over:
            return {"abort_reason": "budget", "tokens_used": tokens}
        return {"tokens_used": tokens}

    return budget_guard


def make_search_node(deps: GraphDeps):
    async def search(state: AutopilotState) -> dict:
        """Deterministic: execute each planned variant through the same
        explore code the API uses, then one semantic sweep over the stored
        posting embeddings; every source feeds the same candidate pool."""
        variants = (state.get("plan") or {}).get("variants") or []
        exclude_seen = _constraints(state).get("exclude_seen", True)
        timeline: list[dict] = list(state.get("searches") or [])
        best: dict[str, dict] = {
            str(candidate["posting_id"]): candidate for candidate in state.get("candidates") or []
        }
        progress = int(state.get("progress_pct") or 0)
        searched = 0
        for variant in variants[:SEARCH_VARIANTS]:
            if await _is_cancelled(deps):
                return {"abort_reason": "cancelled"}
            raw_filters = dict(variant.get("filters") or {})
            if variant.get("query"):
                raw_filters["q"] = variant["query"]
            if exclude_seen:
                raw_filters.setdefault("seen", False)
                raw_filters.setdefault("applied", False)
                raw_filters.setdefault("hidden", False)
            entry = {
                "step": "search",
                "query": variant.get("query") or "",
                "filters": raw_filters,
                "rationale": (variant.get("rationale") or "")[:400],
                "found": 0,
                "examined": 0,
                "error": "",
            }
            try:
                filters = parse_explore_filters(raw_filters)
                result = await explore(
                    deps.db,
                    UUID(state["user_id"]),
                    filters,
                    sort="fit",
                    limit=SEARCH_LIMIT,
                    with_facets=False,
                )
                entry["found"] = int(result.get("total") or 0)
                entry["examined"] = len(result.get("items") or [])
                for item in result.get("items") or []:
                    candidate = _serialize_candidate(item)
                    if candidate is None:
                        continue
                    key = str(candidate["posting_id"])
                    existing = best.get(key)
                    if existing is None or float(candidate.get("fit") or 0) > float(
                        existing.get("fit") or 0
                    ):
                        best[key] = candidate
            except Exception as exc:
                logger.warning("autopilot candidate evaluation failed", exc_info=True)
                entry["error"] = sanitize_error_detail(f"{type(exc).__name__}: {exc}")
            timeline.append(entry)
            searched += 1
            progress = max(
                progress,
                min(55, 15 + int(40 * searched / max(len(variants), 1))),
            )
            await _report(
                deps,
                progress,
                f"searched {searched}/{max(len(variants), 1)} variants",
            )
        timeline.append(await _semantic_sweep(deps, state, best))
        return {
            "searches": timeline,
            "candidates": _cap_candidates(list(best.values())),
            "progress_pct": progress,
        }

    return search


def make_filter_node(deps: GraphDeps):
    async def filter_node(state: AutopilotState) -> dict:
        """Deterministic: seen/applied/hidden, never-terms, per-goal
        cooldown; counts land in the transparency timeline. Every survivor
        carries its must-term coverage — coverage is ranked downstream,
        never a gate."""
        constraints = _constraints(state)
        never_terms = [str(t).casefold() for t in constraints.get("never_terms") or []]
        must_terms = _must_terms(state)
        exclude_seen = constraints.get("exclude_seen", True)
        candidates = state.get("candidates") or []
        kept: list[dict] = []
        dropped = {"seen": 0, "never": 0, "cooldown": 0}
        for candidate in candidates:
            haystack = _candidate_texts(candidate)
            if any(term and term in haystack for term in never_terms):
                dropped["never"] += 1
                continue
            if exclude_seen and (
                candidate.get("seen_at")
                or candidate.get("applied_at")
                or candidate.get("hidden_at")
            ):
                dropped["seen"] += 1
                continue
            if str(candidate["posting_id"]) in deps.cooldown_ids:
                dropped["cooldown"] += 1
                continue
            kept.append(
                {
                    **candidate,
                    "must_hits": sum(1 for term in must_terms if term in haystack),
                }
            )
        await _report(deps, 62, "filtered candidates")
        return {
            "candidates": kept,
            "progress_pct": max(int(state.get("progress_pct") or 0), 62),
            "searches": [
                *(state.get("searches") or []),
                {"step": "filter", **dropped, "kept": len(kept)},
            ],
        }

    return filter_node


def _pool_order(candidate: dict) -> tuple[int, float, str]:
    """The deterministic ranking: constraints are promises, fit is
    preference — must-term coverage first, then fit, then recency."""
    return (
        int(candidate.get("must_hits") or 0),
        float(candidate.get("fit") or 0),
        str(candidate.get("posted_at") or ""),
    )


def make_evaluate_node(deps: GraphDeps):
    async def evaluate(state: AutopilotState) -> dict:
        """Deterministic: canonical posting_fit breakdowns +
        ``(must_hits, fit)`` ordering, cut to the curator pool."""
        candidates = state.get("candidates") or []
        if not candidates:
            await _report(deps, 70, "evaluated fit")
            return {"progress_pct": max(int(state.get("progress_pct") or 0), 70)}
        from app.models.posting_model import JobPosting
        from app.services.postings.posting_fit_service import get_posting_fits_batch

        ids = [UUID(c["posting_id"]) for c in candidates]
        rows = await deps.db.execute(select(JobPosting).where(JobPosting.id.in_(ids)))
        postings = {str(p.id): p for p in rows.scalars().all()}
        fits = await get_posting_fits_batch(
            deps.db, UUID(state["user_id"]), list(postings.values())
        )
        enriched: list[dict] = []
        for candidate in candidates:
            fit = fits.get(UUID(candidate["posting_id"])) or {}
            breakdown = fit.get("breakdown")
            if breakdown is None:
                breakdown = candidate.get("breakdown") or {}
            posting = postings.get(candidate["posting_id"])
            enriched.append(
                {
                    **candidate,
                    "fit": round(float(fit.get("score", candidate.get("fit") or 0)), 2),
                    "breakdown": breakdown,
                    "posted_at": (
                        posting.posted_at.isoformat()
                        if posting is not None and posting.posted_at
                        else candidate.get("posted_at")
                    ),
                }
            )
        enriched.sort(key=_pool_order, reverse=True)
        await _report(deps, 70, "evaluated fit")
        return {
            "candidates": enriched[: curator_pool(state.get("top_n"))],
            "progress_pct": max(int(state.get("progress_pct") or 0), 70),
        }

    return evaluate


def make_replan_node(deps: GraphDeps):
    async def replan(state: AutopilotState) -> dict:
        """LLM step: one bounded broaden after a thin pass. Returns ONLY the
        new variants (the search node keeps the merged pool); a budget that
        is already spent skips the call instead of overspending."""
        previous = [entry for entry in state.get("searches") or [] if entry.get("step") == "search"]
        entry = {
            "step": "replan",
            "queries": [],
            "rationale": "broadened the search after a thin first pass",
            "found": 0,
            "error": "",
        }
        record = {"previous_variants": entry["queries"], "reason": ""}
        budget = state.get("budget") or {}
        max_tokens = int(budget.get("max_tokens") or 0)
        max_calls = int(budget.get("max_calls") or 0)
        spent = 0
        if max_tokens or max_calls:
            try:
                since = datetime.fromisoformat(state["started_at"])
                tokens, calls = await _ledger_usage(deps.db, state["user_id"], since)
                spent = tokens if max_tokens and tokens > max_tokens else 0
                if max_calls and calls >= max_calls:
                    spent = spent or 1
            except (KeyError, ValueError):
                spent = 0
        if spent:
            record["reason"] = "run budget reached"
            return {
                "replan_attempts": 1,
                "plan": {"variants": []},
                "replans": [*(state.get("replans") or []), record],
                "searches": [*(state.get("searches") or []), entry],
            }
        try:
            try:
                vocabulary = await plan_vocabulary(deps.db, UUID(state["user_id"]))
            except Exception:
                logger.warning("autopilot vocabulary collection failed", exc_info=True)
                vocabulary = {}
            result = await ainvoke_structured(
                deps.db,
                AITaskType.AUTOPILOT_RUN,
                SearchPlan,
                system=_replan_system(),
                user=_replan_user_prompt(state, previous, vocabulary),
                user_id=UUID(state["user_id"]),
            )
            variants = [variant.model_dump(mode="json") for variant in result.variants]
        except Exception as exc:
            logger.warning("autopilot replan failed", exc_info=True)
            entry["error"] = sanitize_error_detail(f"{type(exc).__name__}: {exc}")
            variants = []
        entry["queries"] = [
            str(variant.get("query") or "")
            or ", ".join(str(k) for k in (variant.get("filters") or {}).get("keywords") or [])
            for variant in variants
        ]
        record["previous_variants"] = [item.get("query") or "" for item in previous]
        record["new_variants"] = entry["queries"]
        return {
            "replan_attempts": int(state.get("replan_attempts") or 0) + 1,
            "plan": {"variants": variants},
            "replans": [*(state.get("replans") or []), record],
            "searches": [*(state.get("searches") or []), entry],
            "progress_pct": int(state.get("progress_pct") or 0),
        }

    return replan


def make_graph_sweep_node(deps: GraphDeps):
    async def graph_sweep(state: AutopilotState) -> dict:
        """Deterministic: expand the pool over the catalog's curated
        ``similar_to``/``alternative_to`` edges — role adjacency no text
        signal encodes. No embeddings, no AI; degrades to a no-op entry."""
        entry = {
            "step": "search",
            "query": "",
            "filters": {},
            "rationale": "curated graph expansion (no mapped seeds)",
            "found": 0,
            "examined": 0,
            "error": "",
        }
        pool = list(state.get("candidates") or [])
        try:
            from app.models.enums import JobStatus, RelationType
            from app.models.job_model import Job, JobRelation

            seeds = [
                candidate
                for candidate in sorted(pool, key=_pool_order, reverse=True)
                if candidate.get("catalog_job_id")
            ][:GRAPH_SEEDS]
            if not seeds:
                return {"candidates": pool, "searches": [*(state.get("searches") or []), entry]}
            titles = [str(seed.get("title") or "") for seed in seeds]
            entry["rationale"] = f"curated graph expansion from {', '.join(titles)}"[:400]
            seed_ids = {UUID(str(seed["catalog_job_id"])) for seed in seeds}
            rows = await deps.db.execute(
                select(JobRelation)
                .where(
                    JobRelation.relation_type.in_(
                        [RelationType.SIMILAR_TO.value, RelationType.ALTERNATIVE_TO.value]
                    ),
                    or_(
                        JobRelation.from_job_id.in_(seed_ids),
                        JobRelation.to_job_id.in_(seed_ids),
                    ),
                )
                .order_by(JobRelation.weight.desc(), JobRelation.id)
            )
            related: list[UUID] = []
            for relation in rows.scalars().all():
                other = (
                    relation.to_job_id if relation.from_job_id in seed_ids else relation.from_job_id
                )
                if other in seed_ids or other in related:
                    continue
                related.append(other)
            published = set(
                (
                    await deps.db.execute(
                        select(Job.id).where(
                            Job.id.in_(related), Job.status == JobStatus.PUBLISHED.value
                        )
                    )
                )
                .scalars()
                .all()
            )
            targets = [job_id for job_id in related if job_id in published][:GRAPH_NEIGHBORS]
            if targets:
                known = {str(candidate["posting_id"]) for candidate in pool}
                gated = await _gated_rows(deps, state, catalog_job_ids=targets, exclude_ids=known)
                entry["examined"] = len(gated)
                merged = {str(candidate["posting_id"]): candidate for candidate in pool}
                entry["found"] = _merge_candidates(
                    merged, await _scored_candidates(deps, state, gated)
                )
                pool = sorted(merged.values(), key=_pool_order, reverse=True)[
                    : curator_pool(state.get("top_n"))
                ]
        except Exception as exc:
            logger.warning("autopilot graph sweep degraded", exc_info=True)
            entry["error"] = sanitize_error_detail(f"{type(exc).__name__}: {exc}")
        return {"candidates": pool, "searches": [*(state.get("searches") or []), entry]}

    return graph_sweep


def make_curate_node(deps: GraphDeps):
    async def curate(state: AutopilotState) -> dict:
        """LLM step 2: top candidates → explained shortlist (audited)."""
        pool = (state.get("candidates") or [])[: curator_pool(state.get("top_n"))]
        if not pool:
            return {}
        try:
            result = await ainvoke_structured(
                deps.db,
                AITaskType.AUTOPILOT_RUN,
                Curation,
                system=_curate_system(int(state.get("top_n") or DEFAULT_TOP_N)),
                user=_curate_user_prompt(state, pool),
                user_id=UUID(state["user_id"]),
            )
            return {"curation": result.model_dump(mode="json")}
        except Exception as exc:
            lowered = str(exc).lower()
            reason = "budget" if "budget" in lowered or "rate limit" in lowered else "error"
            return {
                "abort_reason": state.get("abort_reason") or reason,
                "error": f"{type(exc).__name__}: {exc}",
            }

    return curate


def make_deliver_node(deps: GraphDeps):
    async def deliver(state: AutopilotState) -> dict:
        """Deterministic: persist findings + run outcome, emit one
        notification. LLM explanations ship only after quote
        verification; the fallback `why` is pure fit math."""
        from app.models.autopilot_model import (
            AutopilotFinding,
            AutopilotGoal,
            AutopilotRun,
        )
        from app.services.notification_service import NotificationService

        top_n = int(state.get("top_n") or DEFAULT_TOP_N)
        pool = state.get("candidates") or []
        by_id = {str(c["posting_id"]): c for c in pool}
        curation = state.get("curation") or {}
        curated: dict[str, dict] = {}
        valid_indices = set(range(len(pool)))
        for entry in curation.get("findings") or []:
            index = entry.get("index")
            if index not in valid_indices:
                continue
            candidate = pool[index]
            curated[str(candidate["posting_id"])] = {
                "why": str(entry.get("why") or "")[:1200],
                "quotes": _verify_quotes(candidate, entry.get("quotes") or []),
            }
        picked = curated.keys() if curated else [str(c["posting_id"]) for c in pool]
        ordered = sorted(
            (by_id[pid] for pid in picked if pid in by_id),
            key=_pool_order,
            reverse=True,
        )[:top_n]
        must_total = len(_must_terms(state))
        now = _utcnow()
        findings: list[dict] = []
        for candidate in ordered:
            explanation = curated.get(str(candidate["posting_id"])) or {}
            why = explanation.get("why") or _deterministic_why(candidate)
            row = AutopilotFinding(
                run_id=UUID(state["run_id"]),
                posting_id=UUID(candidate["posting_id"]),
                score=round(float(candidate.get("fit") or 0), 2),
                why=why,
                evidence={
                    "quotes": explanation.get("quotes") or [],
                    "breakdown": candidate.get("breakdown") or {},
                    "verified": bool(explanation.get("quotes")),
                    "must_coverage": {
                        "hits": int(candidate.get("must_hits") or 0),
                        "total": must_total,
                    },
                },
            )
            deps.db.add(row)
            findings.append(
                {
                    "posting_id": candidate["posting_id"],
                    "ref": candidate.get("ref"),
                    "title": candidate.get("title"),
                    "org": candidate.get("org"),
                    "score": row.score,
                    "why": why,
                }
            )
        tokens = state.get("tokens_used") or 0
        try:
            since = datetime.fromisoformat(state["started_at"])
            token_total, _calls = await _ledger_usage(deps.db, state["user_id"], since)
            tokens = token_total or tokens
        except (ValueError, KeyError):
            pass
        run = await deps.db.get(AutopilotRun, UUID(state["run_id"]))
        if run is not None:
            run.searches_executed = list(state.get("searches") or [])
            run.tokens_used = tokens
            run.finished_at = now
            if state.get("abort_reason") == "budget":
                run.status = AutopilotRunStatus.BUDGET_ABORTED.value
            elif state.get("abort_reason") == "cancelled":
                run.status = AutopilotRunStatus.CANCELLED.value
            elif state.get("error") and not findings:
                run.status = AutopilotRunStatus.FAILED.value
                run.error = state["error"][:1000]
            else:
                run.status = AutopilotRunStatus.COMPLETED.value
        goal = await deps.db.get(AutopilotGoal, UUID(state["goal_id"]))
        if goal is not None:
            goal.last_run_at = now
        await deps.db.flush()
        status = run.status if run is not None else AutopilotRunStatus.COMPLETED.value
        if findings and status in (
            AutopilotRunStatus.COMPLETED.value,
            AutopilotRunStatus.BUDGET_ABORTED.value,
        ):
            await NotificationService(deps.db).emit(
                "autopilot_findings",
                [UUID(state["user_id"])],
                title=(
                    f"Autopilot found {len(findings)} match{'es' if len(findings) != 1 else ''}"
                ),
                body=(state.get("goal_text") or "")[:300],
                payload={
                    "goal_id": state["goal_id"],
                    "run_id": state["run_id"],
                    "count": len(findings),
                    "status": status,
                    "link": "/autopilot",
                },
                source_ref={"goal_id": state["goal_id"], "run_id": state["run_id"]},
                dedup_key=f"autopilot:{state['run_id']}",
            )
        await _report(deps, 100, "delivered")
        return {"findings": findings, "tokens_used": tokens}

    return deliver


# ------------------------------------------------------------------- wiring


def route_by_abort(state: AutopilotState) -> str:
    """After plan/guard/evaluate: budget/cancel jumps straight to deliver."""
    return "deliver" if state.get("abort_reason") else "continue"


def route_after_filter(state: AutopilotState) -> str:
    """A pool thinner than the shortlist gets ONE broaden pass — never
    after an abort, and never more than ``REPLAN_LIMIT`` times."""
    if state.get("abort_reason"):
        return "evaluate"
    kept = len(state.get("candidates") or [])
    attempts = int(state.get("replan_attempts") or 0)
    if kept < int(state.get("top_n") or DEFAULT_TOP_N) and attempts < REPLAN_LIMIT:
        return "replan"
    return "evaluate"


def build_autopilot_graph(deps: GraphDeps, checkpointer: Any | None = None):
    """Compile plan → search → filter (⇄ replan, bounded) → evaluate →
    graph_sweep → budget_guard → curate → deliver. The guard sits between
    the deterministic pipeline and the last LLM call: at budget the searched
    candidates still ship with deterministic explanations (partial
    findings). Tests pass an ``InMemorySaver``; production passes the app
    checkpointer (thread_id = run id)."""
    builder = StateGraph(AutopilotState)
    retry = RetryPolicy(max_attempts=2)
    builder.add_node("plan", make_plan_node(deps), retry_policy=retry)
    builder.add_node("budget_guard", make_guard_node(deps))
    builder.add_node("search", make_search_node(deps))
    builder.add_node("filter", make_filter_node(deps))
    builder.add_node("replan", make_replan_node(deps), retry_policy=retry)
    builder.add_node("evaluate", make_evaluate_node(deps))
    builder.add_node("graph_sweep", make_graph_sweep_node(deps))
    builder.add_node("curate", make_curate_node(deps), retry_policy=retry)
    builder.add_node("deliver", make_deliver_node(deps))

    builder.add_edge(START, "plan")
    builder.add_conditional_edges(
        "plan", route_by_abort, {"deliver": "deliver", "continue": "search"}
    )
    builder.add_edge("search", "filter")
    builder.add_conditional_edges(
        "filter",
        route_after_filter,
        {"replan": "replan", "evaluate": "evaluate"},
    )
    builder.add_edge("replan", "search")
    builder.add_conditional_edges(
        "evaluate", route_by_abort, {"deliver": "deliver", "continue": "graph_sweep"}
    )
    builder.add_edge("graph_sweep", "budget_guard")
    builder.add_conditional_edges(
        "budget_guard",
        route_by_abort,
        {"deliver": "deliver", "continue": "curate"},
    )
    builder.add_edge("curate", "deliver")
    builder.add_edge("deliver", END)
    return builder.compile(checkpointer=checkpointer)


def initial_state(
    *,
    user_id: UUID,
    goal_id: UUID,
    run_id: UUID,
    goal_text: str,
    constraints: dict,
    budget: dict,
    top_n: int | None = None,
    cooldown_days: int | None = None,
    profile_context: dict | None = None,
) -> AutopilotState:
    """The first checkpoint's payload (everything a resumed run needs)."""
    now = _utcnow()
    days = int(cooldown_days if cooldown_days is not None else DEFAULT_COOLDOWN_DAYS)
    return AutopilotState(
        user_id=str(user_id),
        goal_id=str(goal_id),
        run_id=str(run_id),
        goal_text=goal_text,
        constraints=constraints or {},
        budget=budget or {},
        started_at=now.isoformat(),
        cooldown_cutoff=(now - timedelta(days=max(days, 0))).isoformat(),
        top_n=int(top_n or DEFAULT_TOP_N),
        profile_context=profile_context or {},
        searches=[],
        candidates=[],
        replan_attempts=0,
        replans=[],
        progress_pct=0,
    )


# ------------------------------------------------------------- mock fixture


def _mock_autopilot(schema: type, user_prompt: str) -> dict:
    """Deterministic mock outputs for both autopilot gateway calls.

    The planner returns goal-derived explore-vocabulary variants; the
    curator picks by fit_score and quotes candidate text verbatim so the
    service-side quote verification passes honestly.
    """
    try:
        ctx = json.loads(user_prompt)
    except json.JSONDecodeError:
        ctx = {}
    if schema is SearchPlan and ctx.get("previous_variants") is not None:
        goal = str(ctx.get("goal") or "matching roles")
        tokens = [
            token for token in re.findall(r"[A-Za-z][A-Za-z0-9+#.-]+", goal) if len(token) > 3
        ][:2]
        variants = [{"rationale": "broadened to every open posting", "query": "", "filters": {}}]
        if tokens:
            variants.insert(
                0,
                {
                    "rationale": "relaxed keyword variant for the same goal",
                    "query": "",
                    "filters": {"keywords": tokens},
                },
            )
        return {"variants": variants[:3]}
    if schema is SearchPlan:
        goal = str(ctx.get("goal") or "matching roles")
        tokens = [
            token for token in re.findall(r"[A-Za-z][A-Za-z0-9+#.-]+", goal) if len(token) > 3
        ][:4]
        variants: list[dict] = []
        if tokens:
            variants.append(
                {
                    "rationale": "keyword sweep over the goal's core terms",
                    "query": "",
                    "filters": {"keywords": tokens},
                }
            )
        skills = [str(key) for key in (ctx.get("skill_keys") or [])][:2]
        if skills:
            variants.append(
                {
                    "rationale": "skill keys from the user's own neighbourhood",
                    "query": "",
                    "filters": {"skills": skills},
                }
            )
        must = [str(t) for t in (ctx.get("must_terms") or [])][:2]
        if must:
            variants.append(
                {
                    "rationale": "focused on must-have terms",
                    "query": "",
                    "filters": {"keywords": must},
                }
            )
        if ctx.get("seniority"):
            variants.append(
                {
                    "rationale": "seniority-scoped variant",
                    "query": "",
                    "filters": {"seniority": list(ctx["seniority"])[:3]},
                }
            )
        if ctx.get("target_families"):
            variants.append(
                {
                    "rationale": "target families only",
                    "query": "",
                    "filters": {"mapped_family": [str(k) for k in ctx["target_families"][:3]]},
                }
            )
        variants.append(
            {
                "rationale": "broad net across every connected source",
                "query": "",
                "filters": {},
            }
        )
        return {"variants": variants[:5]}
    if schema is Curation:
        candidates = [c for c in ctx.get("candidates") or [] if isinstance(c, dict)]
        ranked = sorted(
            candidates,
            key=lambda c: float(c.get("fit_score") or 0),
            reverse=True,
        )[:5]
        findings = []
        for candidate in ranked:
            snippet = " ".join(str(candidate.get("description_snippet") or "").split())
            quote = snippet[:80].strip()
            skills = [s.get("key") for s in candidate.get("skills") or [] if isinstance(s, dict)]
            skill_bit = f" Seeks {skills[0]}." if skills else ""
            why = (
                f"{candidate.get('title')} at {candidate.get('org')} scores "
                f"{candidate.get('fit_score')}/10 on your profile.{skill_bit}"
            )
            findings.append(
                {
                    "index": candidates.index(candidate),
                    "why": why[:1200],
                    "quotes": [quote] if quote else [],
                }
            )
        return {"findings": findings}
    return {}


register_mock_fixture(AITaskType.AUTOPILOT_RUN, _mock_autopilot)
