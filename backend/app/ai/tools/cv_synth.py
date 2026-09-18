"""CV synth copilot tools — the variant library operations, registered.

The executors resolve ownership from the ToolContext user and delegate
to `CvSynthService` (single source). Read scope feeds chat answers (the
MCP layer exposes them, 41b contract); write scope mutates: generate /
update / enable. No delete tool — deletion stays a human action in the
library UI.

Plan 104: `variant_list` / `variant_pin` carry the "chat" audience (keys
sit outside the cv_ main-chat exclusion) so the main chatbot — with a CV
attached (plan 78) — can list variants and set/unset the per-item
default (the Context-panel star). Pinning follows plan-102 star
semantics: a pinned draft is promoted (supersede + active) first."""

from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.ai.tools.base import AITool, ToolContext, ToolScope

from app.schemas.cv import CvContextRef, CvContextSelection
from app.schemas.cv_synth import (
    CvSynthAction,
    CvSynthItemGenerate,
    CvSynthItemUpdate,
    CvSynthPayload,
    CvSynthStateStatus,
)

AUDIENCES = frozenset({"cv_builder"})
CHAT_AUDIENCES = frozenset({"chat"})


class CvSynthListInput(BaseModel):
    cv_id: Optional[str] = Field(
        default=None,
        min_length=8,
        max_length=64,
        description=(
            "Optional CV — per-variant applicability verdicts vs this CV: "
            "applies / wrong_language / other_posting / stale / "
            "override_conflict / orphaned."
        ),
    )
    status: Optional[str] = None
    source_key: Optional[str] = None
    language: Optional[str] = None
    stale: Optional[bool] = None


class CvSynthReadInput(BaseModel):
    item_id: str = Field(min_length=8, max_length=64)


class CvSynthGenerateInput(BaseModel):
    cv_id: str = Field(min_length=8, max_length=64)
    refs: list[CvContextRef] = Field(min_length=1, max_length=10)
    action: CvSynthAction = "summarize"
    target_language: Optional[str] = None
    translate_of: Optional[str] = None
    regenerate_of: Optional[str] = None
    posting_id: Optional[str] = None
    variant_key: Optional[str] = None
    language: str = "en"
    tone: Optional[str] = None
    length: Optional[str] = None
    instruction: Optional[str] = Field(
        default=None,
        max_length=300,
        description="Optional free-text steering, e.g. 'emphasize teamwork'; "
        "grounding rules always win.",
    )
    activate: bool = Field(
        default=True,
        description=(
            "Plan 102: the user's request in chat is the approval — "
            "created variants go live immediately. Pass false only to "
            "leave them as drafts."
        ),
    )


class CvSynthUpdateInput(BaseModel):
    item_id: str = Field(min_length=8, max_length=64)
    description: Optional[str] = Field(default=None, min_length=1, max_length=4000)
    status: Optional[CvSynthStateStatus] = Field(
        default=None, description="draft | active | archived"
    )
    variant_key: Optional[str] = None


class VariantListInput(BaseModel):
    cv_id: Optional[str] = Field(
        default=None,
        min_length=8,
        max_length=64,
        description=(
            "Optional CV — adds a per-variant applicability verdict for it: "
            "applies / wrong_language / other_posting / stale / "
            "override_conflict / orphaned / not_pinned."
        ),
    )
    status: Optional[str] = None
    source_key: Optional[str] = None
    language: Optional[str] = None
    stale: Optional[bool] = None


class VariantPinInput(BaseModel):
    cv_id: str = Field(min_length=8, max_length=64)
    variant_id: Optional[str] = Field(
        default=None,
        min_length=8,
        max_length=64,
        description="The variant to make the default for its item(s).",
    )
    source_key: Optional[str] = Field(
        default=None,
        description="With item_id + unpin: clear one item slot's default.",
    )
    item_id: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=64,
    )
    unpin: bool = Field(
        default=False,
        description=(
            "true = remove defaults (by variant_id, or by source_key+item_id "
            "slot) so the item renders the profile text again."
        ),
    )


async def _owned_cv(db, ctx: ToolContext, cv_id: str):
    from uuid import UUID

    from app.core.errors import PermissionDeniedError
    from app.services.cv_service import CvService

    if ctx.user_id is None:
        raise PermissionDeniedError("A signed-in user is required")
    return await CvService(db).get_owned(UUID(cv_id), ctx.user_id)


async def _owned_variant(db, ctx: ToolContext, item_id: str):
    from uuid import UUID

    from app.core.errors import PermissionDeniedError
    from app.services.cv_synth_service import CvSynthService

    if ctx.user_id is None:
        raise PermissionDeniedError("A signed-in user is required")
    return await CvSynthService(db).get_owned(UUID(item_id), ctx.user_id)


def _applicability_verdict(
    row,
    entry: dict,
    cv,
    applied_ids: dict[str, str],
    override_patch_keys: set[str],
) -> Optional[str]:
    """Per-CV applicability verdict for one variant row (plan 62.4)."""
    ref_keys = [f"{ref['source_key']}:{ref['item_id']}" for ref in row.source_refs]
    if str(row.id) in applied_ids.values():
        return "applies"
    if entry["orphaned"]:
        return "orphaned"
    if entry["stale"]:
        return "stale"
    if row.voice.get("language") != (cv.language or "en"):
        return "wrong_language"
    if (
        row.target_posting_id is not None
        and row.target_posting_id != cv.target_posting_id
    ):
        return "other_posting"
    if row.status == "active" and any(
        ref_key in override_patch_keys for ref_key in ref_keys
    ):
        return "override_conflict"
    if row.status == "active" and not any(
        ((cv.context or {}).get("synth_pins") or {}).get(ref_key)
        for ref_key in ref_keys
    ):
        return "not_pinned"
    return None


async def _list_synths(db, ctx: ToolContext, args: CvSynthListInput):
    from app.services.cv_synth_service import CvSynthService

    if ctx.user_id is None:
        from app.core.errors import PermissionDeniedError

        raise PermissionDeniedError("A signed-in user is required")
    service = CvSynthService(db)
    rows = await service.list_rows(
        ctx.user_id,
        status=args.status,
        source_key=args.source_key,
        language=args.language,
        stale=args.stale,
    )
    applied_ids: dict[str, str] = {}
    cv = None
    override_patch_keys: set[str] = set()
    if args.cv_id:
        from app.services.cv_builder_service import CvBuilderService

        cv = await _owned_cv(db, ctx, args.cv_id)
        resolution = await CvBuilderService(db).resolution(cv)
        applied_ids = resolution.synth_applied or {}
        override_patch_keys = set(
            k
            for k, v in (cv.working_content or {}).get("overrides", {}).items()
            if isinstance(v, dict) and v
        )
    items = []
    for entry in rows:
        row = entry["row"]
        item = {
            "id": str(row.id),
            "scope": row.scope,
            "variant_key": row.variant_key,
            "status": row.status,
            "source": row.source,
            "verified": row.verified,
            "stale": entry["stale"],
            "orphaned": entry["orphaned"],
            "voice": row.voice,
            "source_refs": row.source_refs,
        }
        if cv is not None:
            verdict = _applicability_verdict(
                row, entry, cv, applied_ids, override_patch_keys
            )
            if verdict is not None:
                item["verdict"] = verdict
        items.append(item)
    return {"items": items[:40]}


async def _list_variants(db, ctx: ToolContext, args: VariantListInput):
    """Chat-audience variant digest (plan 104): slim rows + verdicts."""
    from app.services.cv_synth_service import CvSynthService

    if ctx.user_id is None:
        from app.core.errors import PermissionDeniedError

        raise PermissionDeniedError("A signed-in user is required")
    service = CvSynthService(db)
    rows = await service.list_rows(
        ctx.user_id,
        status=args.status,
        source_key=args.source_key,
        language=args.language,
        stale=args.stale,
    )
    applied_ids: dict[str, str] = {}
    cv = None
    override_patch_keys: set[str] = set()
    if args.cv_id:
        cv = await _owned_cv(db, ctx, args.cv_id)
        from app.services.cv_builder_service import CvBuilderService

        resolution = await CvBuilderService(db).resolution(cv)
        applied_ids = resolution.synth_applied or {}
        override_patch_keys = set(
            k
            for k, v in (cv.working_content or {}).get("overrides", {}).items()
            if isinstance(v, dict) and v
        )
    items = []
    for entry in rows:
        row = entry["row"]
        item = {
            "id": str(row.id),
            "variant_key": row.variant_key,
            "status": row.status,
            "source": row.source,
            "stale": entry["stale"],
            "orphaned": entry["orphaned"],
            "language": row.voice.get("language"),
            "source_refs": row.source_refs,
        }
        if cv is not None:
            verdict = _applicability_verdict(
                row, entry, cv, applied_ids, override_patch_keys
            )
            if verdict is not None:
                item["verdict"] = verdict
        items.append(item)
    return {"items": items[:40]}


async def _pin_variant(db, ctx: ToolContext, args: VariantPinInput):
    """Set/unset the per-item default variant on a CV (plan 104).

    Pin = the Context-panel star: the variant's text swaps in at
    resolution for every ref it covers. A pinned draft is promoted first
    (supersede + active — plan 102 keeps `pin inactive` unreachable).
    The rest of the context selection (mode/include/exclude) is
    preserved."""
    from app.core.errors import ValidationError
    from app.schemas.cv import CvDocumentUpdate
    from app.services.cv_service import CvService
    from app.services.cv_synth_service import CvSynthService

    if ctx.user_id is None:
        from app.core.errors import PermissionDeniedError

        raise PermissionDeniedError("A signed-in user is required")
    user_id = ctx.user_id
    cv = await _owned_cv(db, ctx, args.cv_id)
    selection = CvContextSelection.model_validate(cv.context or {})
    pins = dict(selection.synth_pins)

    if args.unpin:
        removed: list[str] = []
        if args.source_key and args.item_id:
            ref_key = f"{args.source_key}:{args.item_id}"
            if pins.pop(ref_key, None) is not None:
                removed.append(ref_key)
        elif args.variant_id:
            variant_id = await _variant_id_of(db, ctx, args.variant_id)
            for ref_key in [k for k, v in pins.items() if v == variant_id]:
                pins.pop(ref_key)
                removed.append(ref_key)
        else:
            raise ValidationError(
                "unpin needs variant_id, or source_key+item_id for one slot"
            )
        if not removed:
            return {
                "cv_id": str(cv.id),
                "pinned": {},
                "removed": [],
                "note": "Nothing was pinned for that target.",
            }
        note = "Default removed — the item(s) render the profile text again."
    else:
        if not args.variant_id:
            raise ValidationError("pin needs variant_id")
        variant = await _owned_variant(db, ctx, args.variant_id)
        if variant.status == "archived":
            raise ValidationError("Archived variants cannot be pinned")
        if not variant.source_refs:
            raise ValidationError("Variant has no source refs to pin")
        if variant.status == "draft":
            service = CvSynthService(db)
            await service.update(
                variant.id, user_id, CvSynthItemUpdate(status="active")
            )
        pinned: dict[str, str] = {}
        for ref in variant.source_refs:
            ref_key = f"{ref['source_key']}:{ref['item_id']}"
            pins[ref_key] = str(variant.id)
            pinned[ref_key] = str(variant.id)
        note = (
            "Pinned — this variant is now the default for its item(s) on "
            "this CV and swaps in at render time."
        )
        removed = []
    await CvService(db).update(
        cv.id,
        user_id,
        CvDocumentUpdate(
            context=CvContextSelection(
                mode=selection.mode,
                include=selection.include,
                exclude=selection.exclude,
                synth_pins=pins,
            )
        ),
    )
    return {
        "cv_id": str(cv.id),
        "pinned": {} if args.unpin else pinned,
        "removed": removed,
        "note": note,
    }


async def _variant_id_of(db, ctx: ToolContext, variant_id: str) -> str:
    """Ownership-checked variant id as a plain string."""
    row = await _owned_variant(db, ctx, variant_id)
    return str(row.id)


async def _read_synth(db, ctx: ToolContext, args: CvSynthReadInput):
    row = await _owned_variant(db, ctx, args.item_id)
    return {
        "id": str(row.id),
        "scope": row.scope,
        "variant_key": row.variant_key,
        "status": row.status,
        "source": row.source,
        "payload": row.payload,
        "voice": row.voice,
        "source_refs": row.source_refs,
        "target_posting_id": (
            str(row.target_posting_id) if row.target_posting_id else None
        ),
        "last_used_at": (row.last_used_at.isoformat() if row.last_used_at else None),
    }


async def _generate_synths(db, ctx: ToolContext, args: CvSynthGenerateInput):
    from uuid import UUID

    from app.services.cv_synth_service import CvSynthService

    if ctx.user_id is None:
        from app.core.errors import PermissionDeniedError

        raise PermissionDeniedError("A signed-in user is required")
    await _owned_cv(db, ctx, args.cv_id)
    request = CvSynthItemGenerate(
        refs=args.refs,
        action=args.action,
        posting_id=UUID(args.posting_id) if args.posting_id else None,
        language=args.language,
        target_language=args.target_language,
        tone=args.tone,
        length=args.length,
        instruction=args.instruction,
        variant_key=args.variant_key,
        translate_of=UUID(args.translate_of) if args.translate_of else None,
        regenerate_of=(UUID(args.regenerate_of) if args.regenerate_of else None),
    )
    service = CvSynthService(db)
    rows = await service.generate(ctx.user_id, request)
    if args.activate and rows:
        from app.schemas.cv_synth import CvSynthItemUpdate

        for row in rows:
            await service.update(
                row.id, ctx.user_id, CvSynthItemUpdate(status="active")
            )
    return {
        "created": [
            {
                "id": str(row.id),
                "status": row.status,
                "variant_key": row.variant_key,
                "language": row.voice.get("language"),
            }
            for row in rows
        ],
        "note": (
            "Created and activated — already live on the CV."
            if args.activate
            else "Draft-then-approve: activate in the library to use them."
        ),
    }


async def _update_synth(db, ctx: ToolContext, args: CvSynthUpdateInput):
    if ctx.user_id is None:
        from app.core.errors import PermissionDeniedError

        raise PermissionDeniedError("A signed-in user is required")
    row = await _owned_variant(db, ctx, args.item_id)
    from app.services.cv_synth_service import CvSynthService

    service = CvSynthService(db)
    payload_patch = None
    if args.description:
        payload_patch = CvSynthPayload(description=args.description)
    request = CvSynthItemUpdate(
        payload=payload_patch,
        status=args.status,
        variant_key=args.variant_key,
    )
    updated = await service.update(row.id, ctx.user_id, request)
    return {
        "id": str(updated.id),
        "status": updated.status,
        "variant_key": updated.variant_key,
    }


class CvReadItemsInput(BaseModel):
    cv_id: str = Field(min_length=8, max_length=64)
    """Bullet-bearing rows of ONE CV, as the renderer resolves them."""

    source_keys: list[Literal["experience", "projects", "volunteer"]] = Field(
        default_factory=lambda: ["experience", "projects", "volunteer"],
        max_length=3,
    )


async def _read_items(db, ctx: ToolContext, args: CvReadItemsInput):
    """Plan 107 grounding: read BEFORE proposing bullet rewrites."""
    from app.services.cv_builder_service import CvBuilderService

    if ctx.user_id is None:
        from app.core.errors import PermissionDeniedError

        raise PermissionDeniedError("A signed-in user is required")
    cv = await _owned_cv(db, ctx, args.cv_id)
    resolution = await CvBuilderService(db).resolution(cv)
    overrides = (cv.working_content or {}).get("overrides") or {}
    items = []
    for source_key in args.source_keys:
        rows = resolution.snapshot.get(source_key)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            item_id = str(row.get("id") or "")
            patch = overrides.get(f"{source_key}:{item_id}") or {}
            entries = patch.get("achievements")
            overridden = isinstance(entries, list)
            source_entries = entries if overridden else row.get("achievements") or []
            bullets = [
                str(entry.get("text") or "")
                for entry in source_entries
                if isinstance(entry, dict)
            ]
            items.append(
                {
                    "source_key": source_key,
                    "item_id": item_id,
                    "title": str(row.get("title") or ""),
                    "org": str(row.get("org_name") or ""),
                    "bullets": bullets[:12],
                    "bullets_overridden_for_this_cv": overridden,
                }
            )
    return {"cv_id": str(cv.id), "items": items}


def _tool(key, title, description, input_model, handler, scope, cost="cheap"):
    return AITool(
        key=key,
        title=title,
        description=description,
        input_model=input_model,
        handler=handler,
        scope=scope,
        audiences=AUDIENCES,
        cost_hint=cost,
        requires_user=True,
    )


def _chat_tool(key, title, description, input_model, handler, scope, cost="cheap"):
    return AITool(
        key=key,
        title=title,
        description=description,
        input_model=input_model,
        handler=handler,
        scope=scope,
        audiences=CHAT_AUDIENCES,
        cost_hint=cost,
        requires_user=True,
    )


CV_SYNTH_TOOLS: list[AITool] = [
    _chat_tool(
        "cv_read_items",
        "Read a CV's bullet items",
        "The attached CV's experience/projects/volunteer rows as they "
        "render: item ids, titles and the current bullets (flags "
        "what is overridden for this CV). Read this before proposing "
        "bullet rewrites.",
        CvReadItemsInput,
        _read_items,
        ToolScope.READ,
    ),
    _tool(
        "cv_synth_list",
        "List synthesized variants",
        "The variant library (status/language/stale filters); pass a CV "
        "to get per-variant applicability verdicts for it.",
        CvSynthListInput,
        _list_synths,
        ToolScope.READ,
    ),
    _tool(
        "cv_synth_read",
        "Read one synthesized variant",
        "Full variant row: refs, payload text, voice, staleness state.",
        CvSynthReadInput,
        _read_synth,
        ToolScope.READ,
    ),
    _tool(
        "cv_synth_generate",
        "Generate synthesized variants",
        "Generate AI variants over the given CV's context refs (summarize / "
        "detail / restyle / posting_fit / translate). The user's request "
        "is the approval — variants go live immediately (pass "
        "activate=false to keep drafts).",
        CvSynthGenerateInput,
        _generate_synths,
        ToolScope.WRITE,
        cost="standard",
    ),
    _tool(
        "cv_synth_update",
        "Update a synthesized variant",
        "Edit the variant text or transition its status "
        "(draft/active/archived). No delete — that stays human-only.",
        CvSynthUpdateInput,
        _update_synth,
        ToolScope.WRITE,
    ),
    _chat_tool(
        "variant_list",
        "List my CV variants",
        "The user's synthesized variant library (status/language/stale "
        "filters); pass the attached CV to get per-variant applicability "
        "verdicts. Ids returned here feed variant_pin.",
        VariantListInput,
        _list_variants,
        ToolScope.READ,
    ),
    _chat_tool(
        "variant_pin",
        "Set / unset a variant as an item's default",
        "Star a variant as the default for its item(s) on one CV (its "
        "text swaps in at render; a draft is promoted first), or unpin "
        "to restore the plain profile text. Changes the attached CV's "
        "context, not the document text.",
        VariantPinInput,
        _pin_variant,
        ToolScope.WRITE,
    ),
]
