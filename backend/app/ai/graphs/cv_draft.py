"""One-shot CV drafting flow — a LangGraph StateGraph.

``collect`` (deterministic) resolves the context for the
request's selection, ``plan`` (LLM) picks the section order, ``draft``
(LLM loop, one audited call per text section) writes grounded texts with
a bounded retry, and ``assemble`` (deterministic) maps everything onto
blocks + field overrides through the same builder services the API uses,
compiling an ``ai_apply`` recovery version. A section that fails
drafting falls back to its profile-derived content — a generation never
breaks or silently drops a section, and the AI never renders the
document. Checkpointed with ``thread_id`` = job id; no mid-flow
interrupts (the request carries all user intent, review happens in the
builder).
"""

import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional, TypedDict
from uuid import UUID

from langgraph.graph import END, START, StateGraph
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.agents.cv_drafter import draft_section, plan_structure
from app.ai.schemas import CvDraftStructure, CvDraftTexts
from app.models.enums import CvVersionCreator
from app.models.posting_model import JobPosting
from app.schemas.cv import CvContextSelection
from app.schemas.cv_generate import CvGenerateRequest
from app.services.cv_context_service import resolve

logger = logging.getLogger(__name__)

PROGRESS_COLLECT = 15
PROGRESS_PLAN = 25
PROGRESS_DRAFT_START = 30
PROGRESS_DRAFT_END = 85
PROGRESS_ASSEMBLE = 95

TEXT_KINDS = ("summary", "experience", "education", "certifications")
ITEM_TITLE = {
    "experience": "Experience",
    "education": "Education",
    "certifications": "Certifications",
}
MAX_PLAN_ITEMS_PER_KIND = 30
DRAFT_RETRIES = 1

ProgressCb = Callable[[int, str], Awaitable[None]]
CancelCb = Callable[[], Awaitable[bool]]


class CvDraftState(TypedDict, total=False):
    """Checkpointed working state (serializable — a run resumes from it)."""

    user_id: str
    run_id: str
    request: dict
    context: dict
    plan: dict
    plan_fallback: bool
    texts: list
    fallback_sections: list
    warnings: list
    abort_reason: str
    error: str
    result: dict


@dataclass
class GraphDeps:
    """Per-invocation dependencies (never checkpointed)."""

    db: AsyncSession
    progress: Optional[ProgressCb] = None
    cancelled: Optional[CancelCb] = None


# ------------------------------------------------------------------ helpers


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


def _request(state: CvDraftState) -> CvGenerateRequest:
    return CvGenerateRequest.model_validate(state.get("request") or {})


def _public_payload(payload: dict) -> dict:
    """Prompt-safe payload (drops the photo data URI — render re-resolves)."""
    return {key: value for key, value in (payload or {}).items() if key != "photo"}


def _source_of(snapshot_index: dict, item_id: str) -> str:
    for key, ids in snapshot_index.items():
        if item_id in ids:
            return key
    return ""


def _items_by_kind(context: dict) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for item in context.get("items") or []:
        grouped.setdefault(str(item.get("source_key") or ""), []).append(item)
    return grouped


def _default_plan(enabled: list[str], items_by_kind: dict[str, list[dict]]) -> dict:
    """Canonical section plan: every enabled kind that has items, in order."""
    return {
        "sections": [
            {"kind": kind, "source_key": kind, "item_ids": [], "rationale": ""}
            for kind in enabled
            if items_by_kind.get(kind)
        ]
    }


def _clamp_plan(
    structure: CvDraftStructure,
    enabled: list[str],
    items_by_kind: dict[str, list[dict]],
) -> dict:
    """Clamp the model's plan to enabled kinds + real item ids."""
    allowed = set(enabled)
    clamped: list[dict] = []
    seen: set[str] = set()
    for section in structure.sections:
        kind = str(section.kind or "")
        if kind not in allowed or kind in seen or not items_by_kind.get(kind):
            continue
        seen.add(kind)
        known = {
            str(item["item_id"]) for item in items_by_kind[kind] if item.get("item_id")
        }
        clamped.append(
            {
                "kind": kind,
                "source_key": kind,
                "item_ids": [
                    item_id for item_id in section.item_ids if item_id in known
                ][:MAX_PLAN_ITEMS_PER_KIND],
                "rationale": str(section.rationale or "")[:400],
            }
        )
    return {"sections": clamped}


def _plan_item_ids(
    plan: dict, kind: str, items_by_kind: dict[str, list[dict]]
) -> list[str]:
    """The plan's item ids for a kind (unplanned = every available item)."""
    known = [
        str(item["item_id"])
        for item in items_by_kind.get(kind) or []
        if item.get("item_id")
    ]
    for section in plan.get("sections") or []:
        if section.get("kind") == kind:
            ids = [str(item_id) for item_id in section.get("item_ids") or []]
            return [item_id for item_id in ids if item_id in known] or known
    return known


def _clamp_section_texts(texts: CvDraftTexts, allowed_ids: list[str]) -> list[dict]:
    """Keep only drafted items whose ids are in the section's allowlist."""
    allowed = set(allowed_ids)
    return [
        {
            "kind": str(section.kind),
            "source_key": str(section.source_key or ""),
            "title": str(section.title or "")[:60],
            "text": str(section.text or "")[:2000],
            "items": [
                {
                    "item_id": str(item.item_id),
                    "text": str(item.text or "")[:2000],
                    "bullets": [str(bullet)[:500] for bullet in item.bullets if bullet],
                }
                for item in section.items
                if str(item.item_id) in allowed
            ],
        }
        for section in texts.sections
    ]


def _section_payload(clamped: list[dict], kind: str) -> Optional[dict]:
    for section in clamped:
        if section["kind"] == kind:
            return section
    return None


def _section_usable(section: Optional[dict], kind: str) -> bool:
    """A section is usable when it carries grounded text to apply."""
    if section is None:
        return False
    if kind == "summary":
        return bool(str(section.get("text") or "").strip())
    return any(str(item.get("text") or "").strip() for item in section["items"])


# -------------------------------------------------------------------- nodes


def make_collect_node(deps: GraphDeps):
    async def collect(state: CvDraftState) -> dict:
        """Deterministic: resolve the request's context + target brief."""
        if await _is_cancelled(deps):
            return {"abort_reason": "cancelled"}
        request = _request(state)
        selection = CvContextSelection.model_validate(request.context)
        resolution = await resolve(deps.db, UUID(state["user_id"]), selection)
        items = []
        for item in resolution.items:
            items.append(
                {
                    "source_key": _source_of(resolution.snapshot_index, item.item_id),
                    "item_id": item.item_id,
                    "label": item.label,
                    "detail": item.detail,
                    "payload": _public_payload(item.payload),
                }
            )
        target: dict = {}
        warnings: list[str] = []
        if request.target_posting_id is not None:
            posting = (
                (
                    await deps.db.execute(
                        select(JobPosting).where(
                            JobPosting.id == request.target_posting_id
                        )
                    )
                )
                .scalars()
                .first()
            )
            if posting is None:
                warnings.append("Target posting not found; generated without it")
            else:
                target = {"title": posting.title, "org": posting.org or ""}
        enabled = [kind for kind in request.enabled_kinds() if kind != "basics"]
        items_by_kind = _items_by_kind({"items": items})
        available = [kind for kind in enabled if items_by_kind.get(kind)]
        if not available:
            return {
                "abort_reason": "sparse",
                "error": "No profile content resolved for the selected sections",
            }
        await _report(deps, PROGRESS_COLLECT, "collected profile context")
        return {
            "context": {
                "items": items,
                "index": resolution.snapshot_index,
                "available": available,
                "target": target,
            },
            "warnings": warnings,
        }

    return collect


def make_plan_node(deps: GraphDeps):
    async def plan(state: CvDraftState) -> dict:
        """LLM step 1: section order + item assignment (clamped).

        A failed plan call falls back to the canonical deterministic plan
        — the plan only personalizes order/selection, so the run never
        depends on it.
        """
        request = _request(state)
        context = state.get("context") or {}
        enabled = list(context.get("available") or [])
        items_by_kind = _items_by_kind(context)
        try:
            structure: CvDraftStructure = await plan_structure(
                deps.db,
                UUID(state["user_id"]),
                enabled_kinds=enabled,
                available={kind: items_by_kind.get(kind) or [] for kind in enabled},
                target=context.get("target") or {},
                language=request.language,
                notes=request.notes,
                tone=request.tone,
            )
            clamped = _clamp_plan(structure, enabled, items_by_kind)
            if not clamped["sections"]:
                raise ValueError("plan contained no usable sections")
            await _report(deps, PROGRESS_PLAN, "planned sections")
            return {"plan": clamped}
        except Exception as exc:  # noqa: BLE001 — deterministic plan fallback
            logger.warning("cv_draft plan fell back to canonical order: %s", exc)
            await _report(deps, PROGRESS_PLAN, "planned sections")
            return {
                "plan": _default_plan(enabled, items_by_kind),
                "plan_fallback": True,
                "warnings": [
                    *(state.get("warnings") or []),
                    "AI section planning unavailable; used the standard order",
                ],
            }

    return plan


def make_draft_node(deps: GraphDeps):
    async def draft(state: CvDraftState) -> dict:
        """LLM step 2: one audited call per text section, bounded retry.

        Structural sections (skills/languages/achievements/interests)
        render profile data directly — no drafting call, taxonomy labels
        stay verbatim. A section that still fails after the retry keeps
        its profile-derived content and lands in ``fallback_sections``.
        """
        request = _request(state)
        context = state.get("context") or {}
        plan = state.get("plan") or {}
        items_by_kind = _items_by_kind(context)
        planned = [
            str(section.get("kind"))
            for section in plan.get("sections") or []
            if section.get("kind") in TEXT_KINDS
        ]
        total = max(len(planned), 1)
        texts: list[dict] = []
        fallback: list[str] = []
        warnings = list(state.get("warnings") or [])
        for position, kind in enumerate(planned):
            if await _is_cancelled(deps):
                return {"abort_reason": "cancelled"}
            allowed_ids = _plan_item_ids(plan, kind, items_by_kind)
            section = {"kind": kind, "source_key": kind, "item_ids": allowed_ids}
            allowed = set(allowed_ids)
            items = [
                item
                for item in items_by_kind.get(kind) or []
                if str(item.get("item_id")) in allowed
            ]
            clamped: list[dict] = []
            retry_note = ""
            for _attempt in range(DRAFT_RETRIES + 1):
                try:
                    result: CvDraftTexts = await draft_section(
                        deps.db,
                        UUID(state["user_id"]),
                        section=section,
                        items=items,
                        target=context.get("target") or {},
                        language=request.language,
                        notes=request.notes,
                        tone=request.tone,
                        length=request.length,
                        retry_note=retry_note,
                    )
                except Exception as exc:  # noqa: BLE001 — fallback, never fail
                    retry_note = f"{type(exc).__name__}: {exc}"[:300]
                    continue
                clamped = _clamp_section_texts(result, allowed_ids)
                if _section_usable(_section_payload(clamped, kind), kind):
                    break
                retry_note = "the previous draft cited no known item ids or was empty"
            usable = _section_payload(clamped, kind)
            if _section_usable(usable, kind):
                texts.append(usable)
            else:
                fallback.append(kind)
            await _report(
                deps,
                PROGRESS_DRAFT_START
                + int(
                    (PROGRESS_DRAFT_END - PROGRESS_DRAFT_START) * (position + 1) / total
                ),
                f"drafted {kind} ({position + 1}/{total})",
            )
        if fallback:
            warnings.append("Some sections kept profile text: " + ", ".join(fallback))
        return {"texts": texts, "fallback_sections": fallback, "warnings": warnings}

    return draft


def make_assemble_node(deps: GraphDeps):
    async def assemble(state: CvDraftState) -> dict:
        """Deterministic: blocks + overrides → CvDocument → ai_apply
        version → lint report (the same builder services the API uses)."""
        from app.models.cv_model import CvDocument
        from app.services.cv_builder_service import CvBuilderService
        from app.services.cv_export_service import CvExportService

        request = _request(state)
        plan = state.get("plan") or {}
        texts = state.get("texts") or []
        overrides: dict[str, dict] = {}

        def section_of(kind: str) -> Optional[dict]:
            for section in texts:
                if section.get("kind") == kind:
                    return section
            return None

        blocks: list[dict] = [{"kind": "header"}]
        for section in plan.get("sections") or []:
            kind = str(section.get("kind") or "")
            if kind == "summary":
                blocks.append({"kind": "summary"})
                drafted = section_of("summary")
                text = str((drafted or {}).get("text") or "").strip()
                if text:
                    overrides["summary:summary"] = {"summary": text}
            elif kind in ITEM_TITLE:
                blocks.append(
                    {
                        "kind": "items",
                        "props": {"title": ITEM_TITLE[kind], "source_key": kind},
                    }
                )
                drafted = section_of(kind)
                for item in (drafted or {}).get("items") or []:
                    patch: dict = {}
                    if str(item.get("text") or "").strip():
                        patch["description"] = str(item["text"])
                    bullets = [
                        str(bullet)
                        for bullet in item.get("bullets") or []
                        if str(bullet).strip()
                    ]
                    if bullets:
                        patch["achievements"] = [{"text": bullet} for bullet in bullets]
                    if patch:
                        overrides[f"{kind}:{item['item_id']}"] = patch
            elif kind == "skills":
                blocks.append({"kind": "skills", "props": {"title": "Skills"}})
            elif kind == "languages":
                blocks.append({"kind": "languages", "props": {"title": "Languages"}})
            elif kind == "achievements":
                blocks.append(
                    {"kind": "achievements", "props": {"title": "Achievements"}}
                )
            elif kind == "interests":
                blocks.append({"kind": "interests", "props": {"title": "Interests"}})
        if not request.include_photo:
            overrides.setdefault("basics:basics", {})["photo"] = ""

        template_id = request.template_id
        if template_id is not None:
            from app.services.cv_template_service import CvTemplateService

            try:
                await CvTemplateService(deps.db).get_readable(
                    template_id, UUID(state["user_id"])
                )
            except Exception:  # noqa: BLE001 — a bad template never fails the run
                template_id = None
        posting_title = str(
            ((state.get("context") or {}).get("target") or {}).get("title") or ""
        )
        title = f"CV — {posting_title}"[:200] if posting_title else "My CV"
        cv = CvDocument(
            user_id=UUID(state["user_id"]),
            title=title,
            kind="resume",
            target_posting_id=request.target_posting_id,
            template_id=template_id,
            language=request.language,
            page_size="a4",
            max_pages=request.max_pages,
            status="draft",
            working_content={
                "blocks": blocks,
                "overrides": overrides,
                "generated_by": "cv_draft",
            },
            context=CvContextSelection.model_validate(
                (state.get("request") or {}).get("context") or {}
            ).model_dump(mode="json"),
        )
        deps.db.add(cv)
        await deps.db.flush()

        builder = CvBuilderService(deps.db)
        version, _html, _metrics = await builder.compile(
            cv, created_by=CvVersionCreator.AI_APPLY
        )
        lint = await CvExportService(deps.db).lint_report(cv)
        await deps.db.commit()
        await _report(deps, PROGRESS_ASSEMBLE, "assembled the CV")
        return {
            "result": {
                "cv_id": str(cv.id),
                "title": cv.title,
                "version": version.version,
                "lint": lint,
                "warnings": list(state.get("warnings") or []),
                "fallback_sections": list(state.get("fallback_sections") or []),
                "plan_fallback": bool(state.get("plan_fallback")),
            }
        }

    return assemble


# ------------------------------------------------------------------- wiring


def route_by_abort(state: CvDraftState) -> str:
    """After collect/draft: cancel or sparse context ends the run."""
    return "end" if state.get("abort_reason") else "continue"


def build_cv_draft_graph(deps: GraphDeps, checkpointer: Optional[Any] = None):
    """Compile collect → plan → draft → assemble. Tests pass an
    ``InMemorySaver``; production passes the app checkpointer
    (thread_id = job id)."""
    builder = StateGraph(CvDraftState)
    builder.add_node("collect", make_collect_node(deps))
    builder.add_node("plan", make_plan_node(deps))
    builder.add_node("draft", make_draft_node(deps))
    builder.add_node("assemble", make_assemble_node(deps))

    builder.add_edge(START, "collect")
    builder.add_conditional_edges(
        "collect", route_by_abort, {"end": END, "continue": "plan"}
    )
    builder.add_edge("plan", "draft")
    builder.add_conditional_edges(
        "draft", route_by_abort, {"end": END, "continue": "assemble"}
    )
    builder.add_edge("assemble", END)
    return builder.compile(checkpointer=checkpointer)


def initial_state(*, user_id: UUID, run_id: UUID, request: dict) -> CvDraftState:
    """The first checkpoint's payload (everything a resumed run needs)."""
    return CvDraftState(
        user_id=str(user_id),
        run_id=str(run_id),
        request=request,
        texts=[],
        fallback_sections=[],
        warnings=[],
    )
