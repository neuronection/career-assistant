"""Autopilot flow — the AI-activated search as a LangGraph
StateGraph.

Nodes do one thing each: an LLM step is one audited gateway call
(``AITaskType.AUTOPILOT_RUN``), every other node is deterministic work.
The graph is checkpointed (``thread_id`` = run id), so a worker crash
resumes from the last completed node via ``ainvoke(None, config)``; a
budget abort routes straight to ``deliver`` so partial findings still
ship. Final ordering is deterministic (fit sort) — the LLM curates, math
ranks. There is no auto-apply node: findings are suggestions, applying
stays a user click.
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Optional, TypedDict
from uuid import UUID

from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.gateway import ainvoke_structured, register_mock_fixture
from app.ai.schemas import Curation, SearchPlan
from app.models.ai_model import AIGeneration
from app.models.enums import AITaskType, AutopilotRunStatus
from app.services.explore_service import explore, parse_explore_filters

logger = logging.getLogger(__name__)

CURATOR_POOL = 12
DEFAULT_TOP_N = 5
DEFAULT_COOLDOWN_DAYS = 7
SEARCH_LIMIT = 25
SNIPPET_CHARS = 600

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
    curation: dict
    findings: list
    abort_reason: str
    error: str
    tokens_used: int


@dataclass
class GraphDeps:
    """Per-invocation dependencies (never checkpointed)."""

    db: AsyncSession
    progress: Optional[ProgressCb] = None
    cancelled: Optional[CancelCb] = None
    cooldown_ids: set[str] = field(default_factory=set)


# ------------------------------------------------------------------ helpers


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def _report(deps: GraphDeps, pct: int, stage: str) -> None:
    if deps.progress is not None:
        await deps.progress(pct, stage)


async def _is_cancelled(deps: GraphDeps) -> bool:
    if deps.cancelled is None:
        return False
    try:
        return bool(await deps.cancelled())
    except Exception:  # noqa: BLE001 — cancel checks never break the flow
        return False


def _constraints(state: AutopilotState) -> dict:
    return state.get("constraints") or {}


async def _ledger_usage(
    db: AsyncSession, user_id: str, since: datetime
) -> tuple[int, int]:
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
        "has a short query plus optional explore filters drawn ONLY from "
        "the allowed filter keys. Vary scope (broad vs niche, different "
        "skill emphases). Honor every never-term (never search for it) "
        "and must-term. Respond with JSON only."
    )


def _plan_user_prompt(state: AutopilotState) -> str:
    c = _constraints(state)
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
        },
        ensure_ascii=False,
    )


def _curate_system(top_n: int) -> str:
    return (
        f"You are a job-search curator. From the candidate postings, pick "
        f"the best {top_n} for the user's goal and explain each in 1-3 "
        f"sentences. Ground EVERY claim in the candidate's provided fields "
        f"(fit score, breakdown, skills, responsibilities, snippet); never "
        f"invent requirements or benefits. Include 1-2 short verbatim "
        f"quotes copied exactly from that candidate's own text (snippet, "
        f"responsibilities). Prefer higher fit_score and honest coverage "
        f"of must-terms; skip noise. Respond with JSON only."
    )


def _curate_user_prompt(state: AutopilotState, pool: list[dict]) -> str:
    c = _constraints(state)
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
    skills = [
        s.get("key", "") for s in candidate.get("skills") or [] if isinstance(s, dict)
    ]
    top = [key for key in skills[:3] if key]
    if top:
        why += f"; looking for {', '.join(top)}"
    return why[:1200]


def _candidate_texts(candidate: dict) -> str:
    """All text a quote may come from (the quote-verification corpus)."""
    skills = " ".join(
        str(s.get("key", ""))
        for s in candidate.get("skills") or []
        if isinstance(s, dict)
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


def _serialize_candidate(item: dict) -> Optional[dict]:
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
    return {
        "posting_id": str(posting.id),
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
            interaction.applied_at.isoformat()
            if interaction is not None and interaction.applied_at
            else None
        ),
        "hidden_at": (
            interaction.hidden_at.isoformat()
            if interaction is not None and interaction.hidden_at
            else None
        ),
    }


# -------------------------------------------------------------------- nodes


def make_plan_node(deps: GraphDeps):
    async def plan(state: AutopilotState) -> dict:
        """LLM step 1: goal + constraints + profile context → SearchPlan."""
        try:
            result = await ainvoke_structured(
                deps.db,
                AITaskType.AUTOPILOT_RUN,
                SearchPlan,
                system=_plan_system(),
                user=_plan_user_prompt(state),
                user_id=UUID(state["user_id"]),
            )
            return {"plan": result.model_dump(mode="json")}
        except Exception as exc:  # noqa: BLE001 — abort cleanly, deliver
            lowered = str(exc).lower()
            reason = (
                "budget" if "budget" in lowered or "rate limit" in lowered else "error"
            )
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
        over = (max_tokens and tokens > max_tokens) or (
            max_calls and calls >= max_calls
        )
        if over:
            return {"abort_reason": "budget", "tokens_used": tokens}
        return {"tokens_used": tokens}

    return budget_guard


def make_search_node(deps: GraphDeps):
    async def search(state: AutopilotState) -> dict:
        """Deterministic: execute each planned variant through the same
        explore code the API uses, collecting candidates."""
        variants = (state.get("plan") or {}).get("variants") or []
        timeline: list[dict] = []
        best: dict[str, dict] = {}
        for variant in variants[:6]:
            if await _is_cancelled(deps):
                return {"abort_reason": "cancelled"}
            raw_filters = dict(variant.get("filters") or {})
            if variant.get("query"):
                raw_filters["q"] = variant["query"]
            entry = {
                "step": "search",
                "query": variant.get("query") or "",
                "filters": raw_filters,
                "rationale": (variant.get("rationale") or "")[:400],
                "found": 0,
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
                )
                entry["found"] = int(result.get("total") or 0)
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
            except Exception as exc:  # noqa: BLE001 — a bad variant never kills the run
                entry["error"] = f"{type(exc).__name__}: {exc}"[:300]
            timeline.append(entry)
            await _report(
                deps,
                min(55, 15 + int(40 * len(timeline) / max(len(variants), 1))),
                f"searched {len(timeline)}/{max(len(variants), 1)} variants",
            )
        return {"searches": timeline, "candidates": list(best.values())}

    return search


def make_filter_node(deps: GraphDeps):
    async def filter_node(state: AutopilotState) -> dict:
        """Deterministic: seen/applied/hidden, never-terms, per-goal
        cooldown; counts land in the transparency timeline."""
        constraints = _constraints(state)
        never_terms = [str(t).casefold() for t in constraints.get("never_terms") or []]
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
            kept.append(candidate)
        await _report(deps, 62, "filtered candidates")
        return {
            "candidates": kept,
            "searches": [
                *(state.get("searches") or []),
                {"step": "filter", **dropped, "kept": len(kept)},
            ],
        }

    return filter_node


def make_evaluate_node(deps: GraphDeps):
    async def evaluate(state: AutopilotState) -> dict:
        """Deterministic: canonical posting_fit breakdowns + fit ordering,
        cut to the curator pool."""
        candidates = state.get("candidates") or []
        if not candidates:
            await _report(deps, 70, "evaluated fit")
            return {}
        from app.models.posting_model import JobPosting
        from app.services.posting_fit_service import get_posting_fits_batch

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
        enriched.sort(
            key=lambda c: (float(c.get("fit") or 0), c.get("posted_at") or ""),
            reverse=True,
        )
        await _report(deps, 70, "evaluated fit")
        return {"candidates": enriched[:CURATOR_POOL]}

    return evaluate


def make_curate_node(deps: GraphDeps):
    async def curate(state: AutopilotState) -> dict:
        """LLM step 2: top candidates → explained shortlist (audited)."""
        pool = (state.get("candidates") or [])[:CURATOR_POOL]
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
        except Exception as exc:  # noqa: BLE001 — fall back to deterministic
            lowered = str(exc).lower()
            reason = (
                "budget" if "budget" in lowered or "rate limit" in lowered else "error"
            )
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
            key=lambda c: float(c.get("fit") or 0),
            reverse=True,
        )[:top_n]
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
                    f"Autopilot found {len(findings)} match"
                    f"{'es' if len(findings) != 1 else ''}"
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


def build_autopilot_graph(deps: GraphDeps, checkpointer: Optional[Any] = None):
    """Compile plan → search → filter → evaluate → guard → curate →
    deliver. The guard sits between the deterministic pipeline and the
    second LLM call: at budget the searched candidates still ship with
    deterministic explanations (partial findings). Tests pass an
    ``InMemorySaver``; production passes the app checkpointer
    (thread_id = run id)."""
    builder = StateGraph(AutopilotState)
    retry = RetryPolicy(max_attempts=2)
    builder.add_node("plan", make_plan_node(deps), retry_policy=retry)
    builder.add_node("budget_guard", make_guard_node(deps))
    builder.add_node("search", make_search_node(deps))
    builder.add_node("filter", make_filter_node(deps))
    builder.add_node("evaluate", make_evaluate_node(deps))
    builder.add_node("curate", make_curate_node(deps), retry_policy=retry)
    builder.add_node("deliver", make_deliver_node(deps))

    builder.add_edge(START, "plan")
    builder.add_conditional_edges(
        "plan", route_by_abort, {"deliver": "deliver", "continue": "search"}
    )
    builder.add_edge("search", "filter")
    builder.add_edge("filter", "evaluate")
    builder.add_conditional_edges(
        "evaluate", route_by_abort, {"deliver": "deliver", "continue": "budget_guard"}
    )
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
    top_n: Optional[int] = None,
    cooldown_days: Optional[int] = None,
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
        searches=[],
        candidates=[],
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
    if schema is SearchPlan:
        goal = str(ctx.get("goal") or "matching roles")
        words = " ".join(goal.split())[:60]
        variants: list[dict] = [
            {
                "rationale": "broad sweep matching the goal text",
                "query": words,
                "filters": {},
            }
        ]
        must = [str(t) for t in (ctx.get("must_terms") or [])][:2]
        if must:
            variants.append(
                {
                    "rationale": "focused on must-have terms",
                    "query": " ".join(must),
                    "filters": {},
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
                    "filters": {
                        "mapped_family": [str(k) for k in ctx["target_families"][:3]]
                    },
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
            skills = [
                s.get("key")
                for s in candidate.get("skills") or []
                if isinstance(s, dict)
            ]
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
