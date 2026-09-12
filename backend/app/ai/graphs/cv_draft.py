"""One-shot CV drafting flow — a LangGraph StateGraph.

``collect`` (deterministic) resolves the context for the
request's selection, ``plan`` (LLM) picks the section order, ``draft``
(LLM loop, one audited call per text section) writes grounded texts with
a bounded retry, and ``assemble`` (deterministic) maps everything onto
blocks + field overrides through the same builder services the API uses,
compiling an ``ai_apply`` recovery version. ``review``/``fix`` then
polish the committed draft (plan 64): the build reviewer looks at the
rendered pages + coverage matrix, the deterministic applier applies its
suggested ops through the copilot's `apply_operation`, looping while
fail-level issues persist up to a hard cap; ``finalize`` compiles the
final ``ai_apply`` version carrying the polish trace. A section that
fails drafting falls back to profile-derived content — a generation
never breaks or silently drops a section, and the AI never renders the
document. Checkpointed with ``thread_id`` = job id; no mid-flow
interrupts (the request carries all user intent, review happens in the
builder).
"""

import copy
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional, TypedDict
from uuid import UUID

from langgraph.graph import END, START, StateGraph
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.agents.cv_drafter import draft_section, plan_structure
from app.ai.gateway import RunRef
from app.ai.schemas import CvDraftStructure, CvDraftTexts
from app.models.enums import CvVersionCreator
from app.models.posting_model import JobPosting
from app.schemas.cv import CvContextSelection
from app.schemas.cv_generate import CvGenerateRequest
from app.services.cv_context_service import resolve


def _run_ref(state: dict, stage: str) -> RunRef:
    """The audit-row run linkage for one graph stage (run_id = job id)."""
    return RunRef(id=UUID(state["run_id"]), stage=stage)


logger = logging.getLogger(__name__)

PROGRESS_COLLECT = 15
PROGRESS_PLAN = 25
PROGRESS_DRAFT_START = 30
PROGRESS_DRAFT_END = 85
PROGRESS_ASSEMBLE = 95

POLISH_MAX_ITERATIONS = 3
MAX_OPS_PER_ITERATION = 6

DATA_URI_RE = re.compile(r"data:image/[^\"'\s)]+")

TEXT_KINDS = (
    "summary",
    "experience",
    "projects",
    "volunteer",
    "education",
    "certifications",
)
ITEM_TITLE = {
    "experience": "Work Experience",
    "projects": "Projects",
    "volunteer": "Volunteering",
    "education": "Education",
    "certifications": "Certifications",
}
MAX_PLAN_ITEMS_PER_KIND = 30
MAX_SYNTH_PROPOSALS = 3
SYNTH_ITEM_SOURCES = ("experience", "education", "certifications")
SYNTH_PROPOSAL_ACTIONS = ("posting_fit", "detail", "restyle")
SYNTH_LENGTH_MAP = {"concise": "short", "standard": "medium", "detailed": "long"}
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
    synth_applied: dict
    synth_proposals: list
    synth_proposed: list
    abort_reason: str
    error: str
    result: dict
    polish: dict
    critique: dict
    review_lint: dict


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
        if section.get("kind") == kind:
            return section
    return None


def _planned_item_ids(plan: dict, context: dict) -> set[str]:
    """Every item id the plan (or its fallback) actually feeds."""
    items_by_kind = _items_by_kind(context)
    planned: set[str] = set()
    for kind in context.get("available") or []:
        planned.update(_plan_item_ids(plan, str(kind), items_by_kind))
    return planned


def _clamp_proposals(
    structure: CvDraftStructure,
    state: CvDraftState,
    plan: Optional[dict] = None,
) -> list[dict]:
    """Clamp the planner's gap-variant proposals (plan 69.2).

    Only skill-bearing item sources, only planned item ids, never refs
    already reused via an active variant, `posting_fit` only for a saved
    target posting, and at most `MAX_SYNTH_PROPOSALS` per run."""
    request = _request(state)
    context = state.get("context") or {}
    planned = _planned_item_ids(plan or state.get("plan") or {}, context)
    applied = set(state.get("synth_applied") or {})
    by_id = {str(item.get("item_id")): item for item in context.get("items") or []}
    clamped: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for proposal in structure.synth_proposals:
        source_key = str(proposal.source_key or "")
        item_id = str(proposal.item_id or "")
        action = str(proposal.action or "detail")
        key = (source_key, item_id)
        if (
            source_key not in SYNTH_ITEM_SOURCES
            or action not in SYNTH_PROPOSAL_ACTIONS
            or key in seen
            or item_id not in planned
            or f"{key[0]}:{key[1]}" in applied
            or "description" not in ((by_id.get(item_id) or {}).get("payload") or {})
        ):
            continue
        if action == "posting_fit" and request.target_posting_id is None:
            continue
        seen.add(key)
        clamped.append({"source_key": source_key, "item_id": item_id, "action": action})
        if len(clamped) >= MAX_SYNTH_PROPOSALS:
            break
    return clamped


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
        """Deterministic: resolve the request's context + target brief.

        Plan 69: in `prefer` synth mode, matched active variants swap
        their text in before the digest is built — the LLM drafts from
        the library, not from raw profile text."""
        if await _is_cancelled(deps):
            return {"abort_reason": "cancelled"}
        request = _request(state)
        selection = CvContextSelection.model_validate(request.context)
        resolution = await resolve(deps.db, UUID(state["user_id"]), selection)
        synth_applied: dict[str, str] = {}
        if selection.synth_mode == "prefer" or selection.synth_pins:
            from app.services.cv_synth_service import CvSynthService

            synth_applied = await CvSynthService(deps.db).apply_to_items(
                UUID(state["user_id"]),
                request.language,
                request.target_posting_id,
                resolution,
                selection.synth_mode,
                pins=selection.synth_pins,
            )
        items = []
        for item in resolution.items:
            source_key = _source_of(resolution.snapshot_index, item.item_id)
            entry = {
                "source_key": source_key,
                "item_id": item.item_id,
                "label": item.label,
                "detail": item.detail,
                "payload": _public_payload(item.payload),
            }
            synth_id = synth_applied.get(f"{source_key}:{item.item_id}")
            if synth_id:
                entry["synth"] = synth_id
            items.append(entry)
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
                if request.posting_text.strip():
                    warnings.append(
                        "Pasted posting text ignored — the saved target "
                        "posting takes precedence"
                    )
        elif request.posting_text.strip():
            # Pasted job posting: first non-empty line usually is the
            # role title — the CV title names itself after it (≤120
            # chars; longer paste keeps a neutral name).
            text = request.posting_text.strip()
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            title_line = lines[0] if lines else ""
            if len(title_line) > 120:
                title_line = "Pasted job posting"
            target = {"title": title_line, "posting_text": text}
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
            "synth_applied": synth_applied,
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
                run=_run_ref(state, "cv_draft.plan"),
            )
            clamped = _clamp_plan(structure, enabled, items_by_kind)
            if not clamped["sections"]:
                raise ValueError("plan contained no usable sections")
            proposals = _clamp_proposals(structure, state, plan=clamped)
            await _report(deps, PROGRESS_PLAN, "planned sections")
            return {"plan": clamped, "synth_proposals": proposals}
        except Exception as exc:  # noqa: BLE001 — deterministic plan fallback
            logger.warning("cv_draft plan fell back to canonical order: %s", exc)
            await _report(deps, PROGRESS_PLAN, "planned sections")
            return {
                "plan": _default_plan(enabled, items_by_kind),
                "plan_fallback": True,
                "synth_proposals": [],
                "warnings": [
                    *(state.get("warnings") or []),
                    "AI section planning unavailable; used the standard order",
                ],
            }

    return plan


def make_synthesize_node(deps: GraphDeps):
    async def synthesize(state: CvDraftState) -> dict:
        """Plan 69.2: ground the planner's gap variants as CV_SYNTH drafts.

        Each accepted proposal runs one audited CV_SYNTH call; the draft
        row's text is swapped into the state digest (the draft node
        grounds from it) and recorded in `synth_proposed`. Failures are
        logged into `warnings` and skipped — a generation never fails
        because variant grounding failed."""
        proposals = list(state.get("synth_proposals") or [])
        if not proposals:
            return {}
        if await _is_cancelled(deps):
            return {"abort_reason": "cancelled"}
        from app.schemas.cv_synth import CvSynthItemGenerate
        from app.services.cv_synth_service import CvSynthService, swap_variant_payload

        request = _request(state)
        context = state.get("context") or {}
        items = [dict(item) for item in context.get("items") or []]
        by_id = {str(item.get("item_id")): item for item in items}
        service = CvSynthService(deps.db)
        warnings = list(state.get("warnings") or [])
        proposed: list[dict] = []
        for proposal in proposals:
            if await _is_cancelled(deps):
                return {
                    "abort_reason": "cancelled",
                    "synth_proposed": proposed,
                    "warnings": warnings,
                }
            source_key = str(proposal.get("source_key"))
            item_id = str(proposal.get("item_id"))
            action = str(proposal.get("action") or "detail")
            gen_request = CvSynthItemGenerate(
                refs=[{"source_key": source_key, "item_id": item_id}],
                action=action,
                posting_id=(
                    request.target_posting_id if action == "posting_fit" else None
                ),
                language=request.language,
                tone=request.tone,
                length=SYNTH_LENGTH_MAP.get(request.length),
            )
            try:
                rows = await service.generate(
                    UUID(state["user_id"]),
                    gen_request,
                    run=_run_ref(state, "cv_synth"),
                )
            except Exception as exc:  # noqa: BLE001 — grounding never fails the run
                logger.warning("cv_draft variant grounding skipped: %s", exc)
                warnings.append(
                    f"Variant grounding skipped for {source_key}: {str(item_id)[:20]}"
                )
                continue
            if not rows:
                continue
            row = rows[0]
            item = by_id.get(item_id)
            if item is None:
                continue
            item["payload"] = dict(item["payload"] or {})
            swap_variant_payload(item["payload"], (source_key, item_id), row)
            proposed.append(
                {
                    "source_key": source_key,
                    "item_id": item_id,
                    "action": action,
                    "synth_item_id": str(row.id),
                }
            )
        result: dict = {"warnings": warnings}
        if proposed:
            result["synth_proposed"] = proposed
            result["context"] = {**context, "items": items}
            await _report(deps, PROGRESS_PLAN + 1, "grounded gap variants")
        return result

    return synthesize


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
                        run=_run_ref(state, "cv_draft.draft"),
                    )
                except Exception as exc:  # noqa: BLE001 — fallback, never fail
                    retry_note = f"{type(exc).__name__}: {exc}"[:300]
                    continue
                clamped = _clamp_section_texts(result, allowed_ids)
                if _section_usable(_section_payload(clamped, kind), kind):
                    break
                retry_note = "the previous draft cited no known item ids or was empty"
            usable = _section_payload(clamped, kind)
            if usable is not None and _section_usable(usable, kind):
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


def _block_source_key(block: dict) -> str:
    props = block.get("props") or {}
    return str(props.get("source_key") or "")


def _merge_onto_template(skeleton: list[dict], generated: list[dict]) -> list[dict]:
    """Merge generated sections onto the template's block skeleton.

    Areas and placement belong to the template: each generated block
    claims the first unused skeleton block of the same kind (items also
    match on `source_key` when both declare one), reusing the skeleton
    block verbatim — including its `area` and title. Skeleton blocks of
    kinds the plan did not include are dropped, and generated blocks
    that match nothing append in the main flow.
    """
    pending = list(generated)
    merged: list[dict] = []
    for block in skeleton:
        kind = str(block.get("kind") or "")
        source_key = _block_source_key(block)
        for index, entry in enumerate(pending):
            if str(entry.get("kind")) != kind:
                continue
            if source_key and _block_source_key(entry) not in ("", source_key):
                continue
            merged.append(copy.deepcopy(block))
            del pending[index]
            break
    merged.extend(pending)
    return merged


async def _resolve_template_for_run(
    deps: GraphDeps,
    request: CvGenerateRequest,
    context: dict,
    user_id: str,
) -> tuple[str | None, str | None]:
    """Background-side template pick (never blocks the UI submit).

    `template_pick == "ai"` runs the deterministic-signal + AI ranking
    right here while the job executes; the endpoint only enqueues, so
    the generate modal can submit instantly. Returns the template id
    (None = studio default) and an optional warning string — a pick
    failure never fails the run."""
    if request.template_pick != "ai" or request.template_id is not None:
        return request.template_id, None
    try:
        from types import SimpleNamespace

        from app.services.cv_template_service import CvTemplateService

        follow_target = context.get("target") or {}
        posting = (
            SimpleNamespace(
                title=follow_target.get("title"), org=follow_target.get("org")
            )
            if follow_target.get("title")
            else None
        )
        result = await CvTemplateService(deps.db).suggest(
            user_id,
            language=request.language,
            posting=posting,
        )
    except Exception:  # noqa: BLE001 — the pick is advice, never the run
        return None, "AI template pick unavailable — using the studio default"
    picks = result.get("picks") or []
    if not picks:
        return None, None
    return str(picks[0]["template_id"]), None


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
        items_by_kind = _items_by_kind(state.get("context") or {})
        overrides: dict[str, dict] = {}

        def section_of(kind: str) -> Optional[dict]:
            for section in texts:
                if section.get("kind") == kind:
                    return section
            return None

        generated: list[dict] = [{"kind": "header"}]
        for section in plan.get("sections") or []:
            kind = str(section.get("kind") or "")
            if kind == "summary":
                generated.append({"kind": "summary"})
                drafted = section_of("summary")
                text = str((drafted or {}).get("text") or "").strip()
                if text:
                    overrides["summary:summary"] = {"summary": text}
            elif kind in ITEM_TITLE:
                generated.append(
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
                chosen = _plan_item_ids(plan, kind, items_by_kind)
                all_skills = [
                    str(x.get("item_id")) for x in items_by_kind.get("skills") or []
                ]
                props: dict = {"title": "Skills"}
                if chosen and len(chosen) < len(all_skills):
                    # The plan picked a relevance subset — carry it to the
                    # block so the renderer lists only those skills.
                    props["selected"] = chosen
                generated.append({"kind": "skills", "props": props})
            elif kind == "languages":
                generated.append({"kind": "languages", "props": {"title": "Languages"}})
            elif kind == "achievements":
                generated.append(
                    {"kind": "achievements", "props": {"title": "Achievements"}}
                )
            elif kind == "interests":
                generated.append({"kind": "interests", "props": {"title": "Interests"}})
        if not request.include_photo:
            overrides.setdefault("basics:basics", {})["photo"] = ""

        resolved_template_id, pick_warning = await _resolve_template_for_run(
            deps, request, state.get("context") or {}, str(state["user_id"])
        )
        if pick_warning:
            state_warnings = list(state.get("warnings") or [])
            state_warnings.append(pick_warning)
            state["warnings"] = state_warnings
        template_id = resolved_template_id
        template_skeleton: list[dict] = []
        if template_id is not None:
            from app.schemas.cv_template import TemplateContent
            from app.services.cv_template_service import CvTemplateService

            try:
                row = await CvTemplateService(deps.db).get_readable(
                    template_id, UUID(state["user_id"])
                )
                template_skeleton = (
                    TemplateContent.model_validate(row.content).blocks or []
                )
            except Exception:  # noqa: BLE001 — a bad template never fails the run
                template_id = None
        blocks = (
            _merge_onto_template(template_skeleton, generated)
            if template_skeleton
            else generated
        )
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
                "run_id": state["run_id"],
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
                "synth_applied": dict(state.get("synth_applied") or {}),
                "synth_proposed": list(state.get("synth_proposed") or []),
            }
        }

    return assemble


# ------------------------------------------------------------ polish loop


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _trace_stage(polish: dict, node: str, note: str = "") -> None:
    """Append a run-stage marker to the trace (timestamps per §3)."""
    stages = polish.setdefault("run", {}).setdefault("stages", [])
    stages.append({"node": node, "at": _now_iso(), "note": note})


async def _mirror_job_result(
    deps: GraphDeps, state: CvDraftState, polish: dict
) -> None:
    """Mirror the trace + cv id into the job's result row mid-run.

    The queue writes the authoritative result at completion; mirrored
    copies let the live preview/progress card show the timeline while
    the loop is still working (overwritten harmlessly at finish)."""
    from app.models.background_job_model import BackgroundJob
    from sqlalchemy.orm.attributes import flag_modified

    job = (
        (
            await deps.db.execute(
                select(BackgroundJob).where(BackgroundJob.id == UUID(state["run_id"]))
            )
        )
        .scalars()
        .first()
    )
    polish["llm_calls"] = await _run_llm_calls(deps, state)
    if job is None:
        return
    result = dict(job.result or {})
    result["cv_id"] = str((state.get("result") or {}).get("cv_id") or "")
    result["polish"] = polish
    result["status"] = "running"
    job.result = result
    flag_modified(job, "result")


def _ref_id(item_id: str) -> str:
    return item_id


def _snapshot_items(resolution, snapshot_index: dict) -> dict[str, list]:
    """Rebuild `{source_key: [CvContextItem]}` from a resolution.

    `snapshot_index` keys (in insertion order) map onto `resolution.items`
    slices by count — the same ordering `resolve()` built them in.
    """
    grouped: dict[str, list] = {}
    cursor = 0
    items = list(getattr(resolution, "items", []) or [])
    for source_key, ids in snapshot_index.items():
        grouped[source_key] = items[cursor : cursor + len(ids)]
        cursor += len(ids)
    return grouped


def _override_ids(working: Optional[dict]) -> set[str]:
    """Item ids that carry field overrides (their content landed)."""
    ids: set[str] = set()
    for key in (working or {}).get("overrides") or {}:
        _, _, item_id = key.partition(":")
        if item_id and item_id not in ("basics", "summary"):
            ids.add(item_id)
    return ids


ITEM_KINDS = frozenset(
    {"experience", "education", "certifications", "projects", "volunteer"}
)


def _plan_ids_and_kinds(plan: dict) -> tuple[set[str], dict[str, str]]:
    """The plan's chosen item ids + each planned kind's rationale."""
    chosen: set[str] = set()
    planned: dict[str, str] = {}
    for section in plan.get("sections") or []:
        kind = str(section.get("kind") or "")
        if kind:
            planned[kind] = str(section.get("rationale") or "the section plan")
            chosen.update(str(x) for x in section.get("item_ids") or [])
    return chosen, planned


def coverage_matrix_for(state: CvDraftState, working: Optional[dict]) -> dict:
    """The deterministic content-coverage audit (plan 64 §3).

    Included = ids the plan chose / that carry overrides / that a
    whole-source planned section renders wholesale; dropped = available
    ids a planned items-section consciously did not feed (with the
    carried rationale) or the request did not enable; missing =
    everything else — the actionable gap the fix loop works on.
    """
    from app.schemas.cv import CvCoverageRef
    from app.services.cv_context_service import CvContextItem, build_coverage_matrix

    context = state.get("context") or {}
    plan = state.get("plan") or {}
    request = _request(state)
    enabled = set(request.enabled_kinds())
    chosen, planned = _plan_ids_and_kinds(plan)
    included = chosen | _override_ids(working)
    dropped: dict[str, str] = {}
    refs: list[CvCoverageRef] = []
    grouped_items: dict[str, list[CvContextItem]] = {}
    for item in context.get("items") or []:
        kind = str(item.get("source_key") or "")
        item_id = str(item.get("item_id") or "")
        if not kind or not item_id:
            continue
        grouped_items.setdefault(kind, []).append(
            CvContextItem(
                item_id=item_id,
                label=str(item.get("label") or ""),
                payload={},
                updated_at=datetime.now(timezone.utc),
            )
        )
        refs.append(
            CvCoverageRef(
                source_key=kind, item_id=item_id, label=str(item.get("label") or "")
            )
        )
        if item_id in included:
            continue
        if kind not in enabled:
            dropped[item_id] = f"the {kind} section is not enabled"
        elif kind in planned and kind in ITEM_KINDS:
            dropped[item_id] = (
                f"the {kind} section plan chose other items ({planned[kind]})"
            )
        elif kind in planned:
            included.add(item_id)
    matrix = build_coverage_matrix(
        grouped_items, included_ids=included, dropped=dropped
    )
    return matrix.model_dump(mode="json")


def route_after_review(state: CvDraftState) -> str:
    """Deterministic gate (§3): fix, finalize or stop cleanly.

    Blocking findings are fail-level vision/lint issues or uncovered
    usable items; warns never block. Cancelled runs and the iteration
    cap finalize what is committed instead of looping.
    """
    if state.get("abort_reason"):
        return "end"
    polish = state.get("polish") or {}
    outcome = polish.get("outcome", {}).get("status")
    if outcome in ("cancelled",):
        return "end"
    critique = state.get("critique") or {}
    iteration = int(polish.get("iteration") or 0)
    issues = critique.get("issues") or []
    lint = state.get("review_lint") or {}
    lint_fails = any(
        str(check.get("level")) == "fail" for check in lint.get("checks") or []
    )
    coverage = critique.get("coverage") or {}
    blocking = lint_fails or any(issue.get("level") == "fail" for issue in issues)
    missing = coverage.get("missing") or []
    pending_judgements = polish.get("variant_pending") or (
        polish.get("redesign") or {}
    ).get("pending")
    if not blocking and not missing:
        if pending_judgements and iteration <= POLISH_MAX_ITERATIONS:
            return "fix"
        return "finalize"
    if iteration >= POLISH_MAX_ITERATIONS or not issues:
        return "finalize"
    return "fix"


def polish_outcome(status: str, error: str = "") -> dict:
    return {"status": status, **({"error": error} if error else {})}


STRUCTURAL_AREAS = frozenset({"layout", "structure"})


def _structural_fail(critique: dict) -> Optional[str]:
    """The first fail-level structural issue message (or None)."""
    for issue in critique.get("issues") or []:
        if issue.get("level") == "fail" and issue.get("area") in STRUCTURAL_AREAS:
            return str(issue.get("message") or "")[:400]
    return None


def _public_request(request) -> dict:
    """The trace's `request` block (§0.11): the user's prompt, unaltered."""
    return {
        "notes": str(request.notes or ""),
        "target_posting_id": (
            str(request.target_posting_id) if request.target_posting_id else ""
        ),
        "tone": request.tone or "",
        "length": request.length,
        "language": request.language,
        "max_pages": int(request.max_pages),
        "sections": list(request.sections or []),
        "include_photo": bool(request.include_photo),
    }


async def _load_cv(deps: GraphDeps, state: CvDraftState):
    from app.core.errors import DomainError
    from app.models.cv_model import CvDocument

    cv_id = str((state.get("result") or {}).get("cv_id") or "")
    row = (
        (await deps.db.execute(select(CvDocument).where(CvDocument.id == UUID(cv_id))))
        .scalars()
        .first()
    )
    if row is None:
        raise DomainError(f"Generated CV {cv_id} missing during polish")
    return row


def _summary_lint(lint: dict) -> dict:
    """The reviewer's compact lint facts (schema per plan §3 trace)."""
    checks = lint.get("checks") or []
    return {
        "checks": checks[:20],
        "empty_blocks": list(lint.get("metrics", {}).get("empty_blocks") or []),
        "pages_actual": lint.get("metrics", {}).get("pages_actual"),
        "max_pages": lint.get("max_pages"),
        "pages_actual_over_budget": bool(
            lint.get("metrics", {}).get("pages_actual_over_budget")
        ),
    }


def _block_summaries(blocks: list[dict]) -> list[dict]:
    return [
        {
            "index": index,
            "kind": str(block.get("kind") or ""),
            "area": str(block.get("area") or "main"),
            "title": str((block.get("props") or {}).get("title") or ""),
        }
        for index, block in enumerate(copy.deepcopy(blocks or []))
    ]


def make_review_node(deps: GraphDeps):
    """Deterministic prep + one audited ``cv_build_review`` call.

    Renders the committed state without creating a version (versions
    exist only at assemble and finalize); pages ride PNGs when the
    optional engine is present, degrading to lint-only facts without it.
    """

    async def review(state: CvDraftState) -> dict:
        if await _is_cancelled(deps):
            polish = dict(state.get("polish") or {})
            polish["outcome"] = polish_outcome("cancelled")
            _trace_stage(polish, "review", "run cancelled")
            return {"abort_reason": "cancelled", "polish": polish}
        from app.ai.agents.cv_build_reviewer import review_build
        from app.services.cv_builder_service import CvBuilderService
        from app.services.cv_export_service import CvExportService
        from app.services.cv_pdf_service import html_to_pngs, pdf_engine_available

        polish = dict(state.get("polish") or {})
        polish.setdefault("run", {})
        polish.setdefault("iterations", [])
        iteration = int(polish.get("iteration") or 0)
        cv = await _load_cv(deps, state)
        request = _request(state)
        builder = CvBuilderService(deps.db)
        exporter = CvExportService(deps.db)

        html, payload, _resolution, _metrics = await builder.render_state(cv)
        lint = await exporter.lint_report(cv)
        template_content, _template_id = await builder.template_content(cv)
        design = template_content.design
        template_summary = (
            f"{design.layout} layout, density {design.density}, base size"
            f" {design.base_size_pt}pt, sidebar width {design.sidebar_width_pct}%"
        )
        coverage = coverage_matrix_for(state, cv.working_content)
        summary_lint = _summary_lint(lint)
        if pdf_engine_available():
            try:
                pages = list(await html_to_pngs(html, page_size=cv.page_size))
            except Exception:  # noqa: BLE001 — PNG engine flakiness degrades
                pages = []
        else:
            pages = []

        critique, review_audit = await review_build(
            deps.db,
            UUID(state["user_id"]),
            template_summary=template_summary,
            lint=summary_lint,
            coverage=coverage,
            blocks=payload.get("blocks") or [],
            page_count=len(pages),
            max_pages=int(request.max_pages),
            iteration=iteration,
            images=pages or None,
            run=_run_ref(state, "cv_draft.review"),
            with_ref=True,
        )
        iteration_record = {
            "n": iteration,
            "started_at": _now_iso(),
            "finished_at": _now_iso(),
            "summary": critique.summary,
            "lint": summary_lint,
            "pages": len(pages),
            "issues": [issue.model_dump(mode="json") for issue in critique.issues],
            "ops": [],
            "audit_ids": [],
            "coverage": coverage,
            "template_chain": [],
            "variants": [],
            "html": DATA_URI_RE.sub("[photo]", html),
        }
        if review_audit:
            iteration_record["audit_ids"].append(review_audit["id"])
        _trace_stage(
            polish, "review", iteration_record.get("summary") or "review complete"
        )
        polish.setdefault("iterations", []).append(iteration_record)
        polish["iteration"] = iteration + 1
        percentage = PROGRESS_ASSEMBLE + (
            (iteration + 1) * (100 - PROGRESS_ASSEMBLE - 1)
        ) // (POLISH_MAX_ITERATIONS + 1)
        await _report(
            deps,
            min(98, percentage),
            f"reviewing the draft (iteration {iteration + 1}/{POLISH_MAX_ITERATIONS})",
        )
        await _mirror_job_result(deps, state, polish)
        await deps.db.commit()
        return {
            "polish": polish,
            "critique": critique.model_dump(mode="json"),
            "review_lint": summary_lint,
        }

    return review


async def _run_llm_calls(deps: GraphDeps, state: CvDraftState) -> list[dict]:
    """The run's LLM-call ledger, read from the audit rows this run
    opted into (65.1 `RunRef` linkage) — one capped indexed query, no
    per-node state. Drives the live telemetry mirror (65.2) and the runs
    endpoint (65.3)."""
    from app.models.ai_model import AIGeneration

    rows = (
        (
            await deps.db.execute(
                select(AIGeneration)
                .where(AIGeneration.run_id == UUID(state["run_id"]))
                .order_by(AIGeneration.created_at)
                .limit(64)
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": str(row.id),
            "task": row.task_type,
            "stage": row.run_stage,
            "status": row.status,
            "provider": row.provider,
            "model": row.model,
            "prompt_version": row.prompt_version,
            "tokens_in": row.tokens_in,
            "tokens_out": row.tokens_out,
            "latency_ms": int(row.latency_ms) if row.latency_ms is not None else None,
        }
        for row in rows
    ]


def make_fix_node(deps: GraphDeps):
    """The deterministic applier: `suggested_ops` → `apply_operation`.

    Bounded by MAX_OPS_PER_ITERATION; anything the applier rejects is
    logged into the trace and dropped — an op failure never blocks the
    run. Each op rides the same audited path the copilot uses. Template
    results ride the template version control (chains recorded per
    iteration); the synth-variant cycle applies a variant, lets the
    NEXT review judge it, and keeps or reverts here.
    """
    from pydantic import TypeAdapter

    from app.schemas.cv_assistant import BuilderOp

    op_parser: TypeAdapter = TypeAdapter(BuilderOp)

    from app.ai.agents.cv_builder_chat import apply_operation

    async def _apply(db, cv, op_dict: dict) -> dict:
        """Validate + apply one op; failures are logged, never raised."""
        entry = {"op": "unknown", "ok": False, "detail": "not applied"}
        try:
            operation = op_parser.validate_python(dict(op_dict))
            result = await apply_operation(db, cv, operation)
            entry = {"op": operation.op, "ok": result.ok, "detail": result.detail[:200]}
        except Exception as exc:  # noqa: BLE001 — a rejected op never blocks
            logger.warning("polish op rejected: %s", exc)
            entry = {
                "op": str((op_dict or {}).get("op")),
                "ok": False,
                "detail": str(exc)[:200],
            }
        return entry

    async def _variant_candidate(critique: dict) -> Optional[dict]:
        """The first set_override op a fail issue suggests (the variant slot)."""
        for issue in critique.get("issues") or []:
            if issue.get("level") != "fail":
                continue
            for suggested in issue.get("suggested_ops") or []:
                operation = dict(suggested.get("operation") or {})
                if operation.get("op") == "set_override":
                    return {
                        "source_key": str(operation.get("source_key") or ""),
                        "item_id": str(operation.get("item_id") or ""),
                        "field": str(operation.get("field") or "description"),
                    }
        return None

    async def _resolve_variant(db, state, cv) -> Optional[dict]:
        """Keep-or-revert a variant the last review already judged."""
        pending = (state.get("polish") or {}).get("variant_pending")
        if not pending:
            return None
        critique = state.get("critique") or {}
        item_id = str(pending.get("item_id") or "")
        still_flagged = (
            any(
                issue.get("level") == "fail"
                and any(
                    str(((op.get("operation") or {}).get("item_id")) or "") == item_id
                    for op in issue.get("suggested_ops") or []
                    if str((op.get("operation") or {}).get("op")) == "set_override"
                )
                for issue in critique.get("issues") or []
            )
            if item_id
            else False
        )
        verdict = "reverted" if still_flagged else "kept"
        record: dict = {
            "item_id": item_id,
            "verdict": verdict,
            "synth_item_id": pending.get("synth_item_id"),
        }
        if still_flagged and pending.get("previous_text") is not None:
            await _apply(
                deps.db,
                cv,
                {
                    "op": "set_override",
                    "source_key": pending.get("source_key"),
                    "item_id": item_id,
                    "field": pending.get("field") or "description",
                    "value": pending.get("previous_text") or "",
                },
            )
            if pending.get("synth_item_id"):
                from app.schemas.cv_synth import CvSynthItemUpdate
                from app.services.cv_synth_service import CvSynthService

                await CvSynthService(deps.db).update(
                    UUID(str(pending["synth_item_id"])),
                    UUID(state["user_id"]),
                    CvSynthItemUpdate(status="archived"),
                )
        return record

    async def _new_variant(db, state, cv) -> Optional[dict]:
        """Ground a variant through CV_SYNTH and apply it as an override."""
        candidate = await _variant_candidate(dict(state.get("critique") or {}))
        if candidate is None:
            return None
        from app.schemas.cv_synth import CvSynthItemGenerate
        from app.services.cv_synth_service import CvSynthService

        request = CvSynthItemGenerate(
            refs=[
                {
                    "source_key": candidate["source_key"],
                    "item_id": candidate["item_id"],
                }
            ],
            action="restyle",
            language=cv.language or "en",
        )
        rows = await CvSynthService(db).generate(
            UUID(state["user_id"]),
            request,
            run=_run_ref(state, "cv_synth"),
        )
        if not rows:
            return None
        row = rows[0]
        overrides = (cv.working_content or {}).get("overrides") or {}
        patch = (
            overrides.get(f"{candidate['source_key']}:{candidate['item_id']}" or "")
            or {}
        )
        previous = patch.get(candidate["field"] or "description")
        payload = dict(row.payload or {})
        text = str(payload.get(candidate["field"] or "description") or "")
        if not text:
            return None
        result = await _apply(
            deps.db,
            cv,
            {
                "op": "set_override",
                "source_key": candidate["source_key"],
                "item_id": candidate["item_id"],
                "field": candidate["field"] or "description",
                "value": text,
            },
        )
        if not result.get("ok"):
            return None
        return {
            "item_id": candidate["item_id"],
            "source_key": candidate["source_key"],
            "previous_text": previous,
            "synth_item_id": str(row.id),
            "verdict": "pending",
            "op_result": result["detail"],
        }

    async def _resolve_redesign(db, state, cv) -> Optional[dict]:
        """Keep-or-revert a redesign the last review judged."""
        redesign = (state.get("polish") or {}).get("redesign") or {}
        if not redesign.get("pending"):
            return None
        critique = state.get("critique") or {}
        if not _structural_fail(critique):
            redesign["pending"] = False
            return {"verdict": "kept", "template_id": redesign.get("template")}
        await _apply(
            db,
            cv,
            {"op": "set_template", "template_id": redesign.get("from")},
        )
        redesign["pending"] = False
        return {"verdict": "reverted", "to": redesign.get("from")}

    async def _redesign_once(db, state, cv) -> Optional[dict]:
        """The structural escape hatch: one AI-drafted private template.

        Trigger: a layout fail persisted across an iteration despite
        applied ops (`layout_fails` ≥ 2). Drafts a fresh private
        template via the existing designer, publishes it DRAFT through
        the template version control, switches to it and re-merges the
        current content onto the new skeleton — the next review judges
        it; the hatch is spent once per run."""
        from sqlalchemy.orm.attributes import flag_modified

        from app.ai.agents.cv_template_designer import draft_template
        from app.models.enums import CvTemplateSource
        from app.services.cv_builder_service import CvBuilderService
        from app.services.cv_template_service import CvTemplateService

        request = _request(state)
        message = _structural_fail(dict(state.get("critique") or {}))
        current, _template_id = await CvBuilderService(db).template_content(cv)
        block_mix = [
            str(block.get("kind"))
            for block in (cv.working_content or {}).get("blocks") or []
        ]
        previous_template_id = str(cv.template_id) if cv.template_id else ""
        template_content = await draft_template(
            db,
            UUID(state["user_id"]),
            brief=(
                f"Redesign a CV template for an existing draft. Current"
                f" problem: {message}. Current block mix: {block_mix}."
                f" Keep readable typography and honor the blocks' areas."
            ),
            density=current.design.density,
            page_budget=int(request.max_pages),
            run=_run_ref(state, "cv_template_design"),
        )
        template = await CvTemplateService(db).create(
            UUID(state["user_id"]),
            f"AI-polished layout ({state['run_id'][:8]})",
            template_content,
            description="Polish-loop redesign draft",
            source=CvTemplateSource.AI,
        )
        result = await _apply(
            db, cv, {"op": "set_template", "template_id": str(template.id)}
        )
        current_blocks = (cv.working_content or {}).get("blocks") or []
        merged = _merge_onto_template(template_content.blocks, current_blocks)
        working = dict(cv.working_content or {})
        working["blocks"] = merged
        cv.working_content = working
        flag_modified(cv, "working_content")
        return {
            "pending": True,
            "template": str(template.id),
            "from": previous_template_id,
            "op": result,
        }

    async def fix(state: CvDraftState) -> dict:
        if await _is_cancelled(deps):
            polish = dict(state.get("polish") or {})
            polish["outcome"] = polish_outcome("cancelled")
            return {"abort_reason": "cancelled", "polish": polish}
        from app.services.cv_builder_service import CvBuilderService

        polish = dict(state.get("polish") or {})
        critique = dict(state.get("critique") or {})
        cv = await _load_cv(deps, state)
        applied = 0
        verdict = await _resolve_variant(deps.db, state, cv)
        if verdict:
            iterations = polish.get("iterations") or []
            if iterations:
                iterations[-1].setdefault("variants", []).append(verdict)
            polish.pop("variant_pending", None)
        redesign_verdict = await _resolve_redesign(deps.db, state, cv)
        if redesign_verdict:
            iterations = polish.get("iterations") or []
            if iterations:
                iterations[-1].setdefault("redesign", []).append(redesign_verdict)
        polish["layout_fails"] = (
            int(polish.get("layout_fails") or 0) + 1
            if _structural_fail(critique)
            else 0
        )
        if (
            _structural_fail(critique)
            and not polish.get("redesign_spent")
            and polish["layout_fails"] >= 2
            and applied < MAX_OPS_PER_ITERATION
        ):
            polish["redesign_spent"] = True
            polish["redesign"] = await _redesign_once(deps.db, state, cv) or {
                "drafted": True
            }
        for issue in critique.get("issues") or []:
            if applied >= MAX_OPS_PER_ITERATION:
                break
            for suggested in issue.get("suggested_ops") or []:
                if applied >= MAX_OPS_PER_ITERATION:
                    break
                applied += 1
                entry = await _apply(
                    deps.db, cv, dict(suggested.get("operation") or {})
                )
                iterations = polish.get("iterations") or []
                if iterations:
                    iterations[-1].setdefault("ops", []).append(entry)
        template_row = await CvBuilderService(deps.db).template_row(cv)
        if template_row is not None:
            iterations = polish.get("iterations") or []
            if iterations:
                iterations[-1].setdefault("template_chain", []).append(
                    {
                        "template_id": str(template_row.id),
                        "version": template_row.version,
                    }
                )
        if applied < MAX_OPS_PER_ITERATION and not polish.get("variant_pending"):
            pending = await _new_variant(deps.db, state, cv)
            if pending:
                polish["variant_pending"] = pending
        await deps.db.commit()
        _trace_stage(polish, "fix", f"applied {applied} op(s)")
        await _report(
            deps,
            min(99, PROGRESS_ASSEMBLE + 2),
            f"applying fixes ({applied} operation{'s' if applied != 1 else ''})",
        )
        await _mirror_job_result(deps, state, polish)
        await deps.db.commit()
        return {"polish": polish}

    return fix


def make_finalize_node(deps: GraphDeps):
    """Final compile + trace persistence (§3).

    Recompiles as the final ``ai_apply`` version, writes the polish
    trace into that version's immutable payload (and hands it to the
    job result); the pre-polish `ai_apply` version from assemble stays
    as the recovery point.
    """

    async def finalize(state: CvDraftState) -> dict:
        from sqlalchemy.orm.attributes import flag_modified

        from app.models.enums import CvVersionCreator
        from app.services.cv_builder_service import CvBuilderService

        cv = await _load_cv(deps, state)
        builder = CvBuilderService(deps.db)
        version, _html, _metrics = await builder.compile(
            cv, created_by=CvVersionCreator.AI_APPLY
        )
        polish = dict(state.get("polish") or {})
        _trace_stage(polish, "finalize", f"final v{version.version}")
        outcome = polish.get("outcome") or {}
        if outcome.get("status") not in ("cancelled",):
            review_lint = state.get("review_lint") or {}
            failed = (
                (review_lint.get("checks") or [])
                and any(
                    str(check.get("level")) == "fail"
                    for check in review_lint.get("checks") or []
                )
            ) or any(
                issue.get("level") == "fail"
                for issue in (state.get("critique") or {}).get("issues") or []
            )
            polish.setdefault("outcome", {})
            polish["outcome"] = polish_outcome("cap" if failed else "completed")
        polish["request"] = _public_request(_request(state))
        polish["final"] = {
            "finished_at": _now_iso(),
            "version": version.version,
        }
        content = dict(version.content or {})
        content["polish"] = polish
        version.content = content
        flag_modified(version, "content")
        await deps.db.commit()
        result = dict(state.get("result") or {})
        result["polish"] = polish
        return {"result": result, "polish": polish}

    return finalize


def route_by_abort(state: CvDraftState) -> str:
    """After collect/draft: cancel or sparse context ends the run."""
    return "end" if state.get("abort_reason") else "continue"


def build_cv_draft_graph(deps: GraphDeps, checkpointer: Optional[Any] = None):
    """Compile collect → plan → draft → assemble → (polish loop).

    The polish loop (plan 64): review → gate → fix → review ⤺ (≤
    POLISH_MAX_ITERATIONS) → finalize. Tests pass an ``InMemorySaver``;
    production passes the app checkpointer (thread_id = job id)."""
    builder = StateGraph(CvDraftState)
    builder.add_node("collect", make_collect_node(deps))
    builder.add_node("plan", make_plan_node(deps))
    builder.add_node("synthesize", make_synthesize_node(deps))
    builder.add_node("draft", make_draft_node(deps))
    builder.add_node("assemble", make_assemble_node(deps))
    builder.add_node("review", make_review_node(deps))
    builder.add_node("fix", make_fix_node(deps))
    builder.add_node("finalize", make_finalize_node(deps))

    builder.add_edge(START, "collect")
    builder.add_conditional_edges(
        "collect", route_by_abort, {"end": END, "continue": "plan"}
    )
    builder.add_edge("plan", "synthesize")
    builder.add_edge("synthesize", "draft")
    builder.add_conditional_edges(
        "draft", route_by_abort, {"end": END, "continue": "assemble"}
    )
    builder.add_edge("assemble", "review")
    builder.add_conditional_edges(
        "review",
        route_after_review,
        {"fix": "fix", "finalize": "finalize", "end": END},
    )
    builder.add_edge("fix", "review")
    builder.add_edge("finalize", END)
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


def build_cv_polish_graph(deps: GraphDeps, checkpointer: Optional[Any] = None):
    """Re-enter the flow at review for an existing CV (plan 64 §3 / 64.5).

    `collect` rebuilds the deterministic context from the CV's stored
    selection; the review → fix ⤺ loop and finalize are the same nodes
    the generate flow uses, so "run polish again" edits a committed CV
    exactly like the loop edits a fresh draft. Resume links ride
    `polish.run.resumed_from`."""
    builder = StateGraph(CvDraftState)
    builder.add_node("collect", make_collect_node(deps))
    builder.add_node("review", make_review_node(deps))
    builder.add_node("fix", make_fix_node(deps))
    builder.add_node("finalize", make_finalize_node(deps))

    builder.add_edge(START, "collect")
    builder.add_conditional_edges(
        "collect", route_by_abort, {"end": END, "continue": "review"}
    )
    builder.add_conditional_edges(
        "review",
        route_after_review,
        {"fix": "fix", "finalize": "finalize", "end": END},
    )
    builder.add_edge("fix", "review")
    builder.add_edge("finalize", END)
    return builder.compile(checkpointer=checkpointer)


def polish_entry_state(
    *, user_id: UUID, run_id: UUID, request: dict, cv_id: UUID, resumed_from: str
) -> CvDraftState:
    """The first checkpoint of a polish-only run over a committed CV."""
    return CvDraftState(
        user_id=str(user_id),
        run_id=str(run_id),
        request=request,
        result={"cv_id": str(cv_id)},
        polish={"run": {"resumed_from": {"job_id": resumed_from}}},
        texts=[],
        fallback_sections=[],
        warnings=[],
    )
