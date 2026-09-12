"""CV synth copilot tools — the variant library operations, registered.

The executors resolve ownership from the ToolContext user and delegate
to `CvSynthService` (single source). Read scope feeds chat answers (the
MCP layer exposes them, 41b contract); write scope mutates: generate /
update / enable. No delete tool — deletion stays a human action in the
library UI."""

from typing import Optional

from pydantic import BaseModel, Field

from app.ai.tools.base import AITool, ToolContext, ToolScope
from typing import Literal

from app.schemas.cv import CvContextRef, CvContextSelection
from app.schemas.cv_synth import (
    CvSynthAction,
    CvSynthItemGenerate,
    CvSynthItemUpdate,
    CvSynthPayload,
    CvSynthStateStatus,
)

AUDIENCES = frozenset({"cv_builder"})


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


class CvSynthUpdateInput(BaseModel):
    item_id: str = Field(min_length=8, max_length=64)
    description: Optional[str] = Field(default=None, min_length=1, max_length=4000)
    status: Optional[CvSynthStateStatus] = Field(
        default=None, description="draft | active | archived"
    )
    variant_key: Optional[str] = None


class CvSynthEnableInput(BaseModel):
    cv_id: str = Field(min_length=8, max_length=64)
    mode: Literal["off", "prefer"] = "prefer"


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
    overrides: dict = {}
    cv = None
    if args.cv_id:
        from app.services.cv_builder_service import CvBuilderService

        cv = await _owned_cv(db, ctx, args.cv_id)
        resolution = await CvBuilderService(db).resolution(cv)
        applied_ids = resolution.synth_applied or {}
        override_patch_keys: set[str] = set(
            k
            for k, v in (cv.working_content or {}).get("overrides", {}).items()
            if isinstance(v, dict) and v
        )
        del overrides
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
            ref_keys = [
                f"{ref['source_key']}:{ref['item_id']}" for ref in row.source_refs
            ]
            if str(row.id) in applied_ids.values():
                item["verdict"] = "applies"
            elif entry["orphaned"]:
                item["verdict"] = "orphaned"
            elif entry["stale"]:
                item["verdict"] = "stale"
            elif row.voice.get("language") != (cv.language or "en"):
                item["verdict"] = "wrong_language"
            elif (
                row.target_posting_id is not None
                and row.target_posting_id != cv.target_posting_id
            ):
                item["verdict"] = "other_posting"
            elif row.status == "active" and any(
                ref_key in override_patch_keys for ref_key in ref_keys
            ):
                item["verdict"] = "override_conflict"
            elif (
                row.status == "active"
                and cv.context
                and (cv.context.get("synth_mode") or "off") == "off"
            ):
                item["verdict"] = "mode_off"
        items.append(item)
    return {"items": items[:40]}


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
        variant_key=args.variant_key,
        translate_of=UUID(args.translate_of) if args.translate_of else None,
        regenerate_of=(UUID(args.regenerate_of) if args.regenerate_of else None),
    )
    rows = await CvSynthService(db).generate(ctx.user_id, request)
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
        "note": "Draft-then-approve: activate in the library to use them.",
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


async def _enable_synth(db, ctx: ToolContext, args: CvSynthEnableInput):
    from app.services.cv_service import CvService

    if ctx.user_id is None:
        from app.core.errors import PermissionDeniedError

        raise PermissionDeniedError("A signed-in user is required")
    cv = await _owned_cv(db, ctx, args.cv_id)
    if args.mode not in ("off", "prefer"):
        from app.core.errors import DomainError

        raise DomainError("mode must be 'off' or 'prefer'")
    selection = (
        CvContextSelection.model_validate(cv.context)
        if cv.context
        else CvContextSelection()
    )
    selection.synth_mode = args.mode
    cv.context = selection.model_dump(mode="json")
    await CvService(db).update(cv.id, ctx.user_id, cv_id_patch(cv))
    return {"cv_id": str(cv.id), "synth_mode": args.mode}


def cv_id_patch(cv):
    from app.schemas.cv import CvDocumentUpdate

    return CvDocumentUpdate(context=cv.context)


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


CV_SYNTH_TOOLS: list[AITool] = [
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
        "Draft AI variants over the given CV's context refs (summarize / "
        "detail / restyle / posting_fit / translate). Draft-then-approve.",
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
    _tool(
        "cv_synth_enable",
        "Set the CV's synth preference",
        "Flip `synth_mode` on a CV: 'prefer' applies matching variants at "
        "resolution, 'off' renders verbatim profile text.",
        CvSynthEnableInput,
        _enable_synth,
        ToolScope.WRITE,
    ),
]
