"""CV builder copilot tools — the builder operations, registered.

The executors live in ``app.ai.agents.cv_builder_chat`` (single source,
the same functions the turn loop runs); this module wraps them as
registry objects so the registry lists them and the MCP layer
(41b) can later expose the read-scope readers. Write scope = mutators;
every handler resolves the owned CV from the ToolContext user.
"""

from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.ai.tools.base import AITool, ToolContext, ToolScope
from app.schemas.cv_assistant import (
    AddBlockOp,
    ApplyThemeOp,
    MoveBlockOp,
    RemoveBlockOp,
    SetBulletsOp,
    SetContextOp,
    SetDocOptionsOp,
    SetOverrideOp,
    SetTemplateOp,
    UpdateBlockPropsOp,
    UpdateDesignOp,
)

AUDIENCES = frozenset({"cv_builder"})


class CvRefInput(BaseModel):
    """The CV document to operate on."""

    cv_id: str = Field(min_length=8, max_length=64)


class SetTemplateInput(CvRefInput):
    template_id: str = Field(min_length=8, max_length=64)


class ApplyThemeInput(CvRefInput):
    theme_key: str = Field(min_length=1, max_length=64)


class UpdateDesignInput(CvRefInput):
    design: dict[str, object] = Field(min_length=1, max_length=30)


class SetContextInput(CvRefInput):
    mode: str = Field(
        default="custom",
        description=(
            "Selection mode: 'all' renders every profile item except the "
            "excluded ids; 'custom' is the normal mode for curated CVs. "
            "Never change the mode the CV already has."
        ),
    )
    include: list[dict] = Field(
        default_factory=list,
        max_length=200,
        description=(
            'Context refs to include, each {"source_key": str, '
            '"item_id": str}. Copy both fields VERBATIM from the '
            "attached CV's context/sources data — refs read from "
            "cv_read_state arrive as 'source_key:item_id' strings and "
            "must be split at the first ':' into these two fields."
        ),
    )
    exclude: list[dict] = Field(
        default_factory=list,
        max_length=200,
        description=(
            'Context refs to hide from this CV, each {"source_key": '
            'str, "item_id": str}. Copy both fields VERBATIM — refs '
            "read from cv_read_state arrive as 'source_key:item_id' "
            "strings and must be split at the first ':' into these two "
            "fields."
        ),
    )


class SetDocOptionsInput(CvRefInput):
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    page_size: Optional[str] = None
    max_pages: Optional[int] = Field(default=None, ge=1, le=10)
    language: Optional[str] = Field(default=None, min_length=2, max_length=10)


class AddBlockInput(CvRefInput):
    kind: str = Field(min_length=1, max_length=40)
    props: dict = Field(default_factory=dict, max_length=30)
    position: Optional[int] = Field(default=None, ge=0, le=24)


class BlockIndexInput(CvRefInput):
    block_index: int = Field(ge=0, le=24)


class MoveBlockInput(CvRefInput):
    block_index: int = Field(ge=0, le=24)
    to_index: int = Field(ge=0, le=24)


class UpdateBlockPropsInput(CvRefInput):
    block_index: int = Field(ge=0, le=24)
    props: dict[str, object] = Field(min_length=1, max_length=30)


class SetOverrideInput(CvRefInput):
    source_key: str = Field(min_length=1, max_length=40)
    item_id: str = Field(min_length=1, max_length=64)
    field: str = Field(min_length=1, max_length=80)
    value: str = Field(min_length=1, max_length=4000)


class SetBulletsInput(CvRefInput):
    source_key: Literal["experience", "projects", "volunteer"]
    item_id: str = Field(min_length=1, max_length=64)
    bullets: list[str] = Field(min_length=0, max_length=12)


async def _owned_cv(db, ctx: ToolContext, cv_id: str):
    from uuid import UUID

    from app.core.errors import PermissionDeniedError
    from app.services.cv_service import CvService

    if ctx.user_id is None:
        raise PermissionDeniedError("A signed-in user is required")
    return await CvService(db).get_owned(UUID(cv_id), ctx.user_id)


_STYLING_OPS = frozenset({"set_template", "apply_theme", "update_design"})


def _op_wrapper(op_model):
    """Wrap one builder operation: load the owned CV, apply, return dict.

    Styling ops verify their result deterministically: the response's
    `after` carries the applied template's factual layout, the page fit
    and the rendered layers — a switch is grounded on the render, not
    on a template's name."""

    async def _handler(db, ctx: ToolContext, args):
        from pydantic import ValidationError

        from app.ai.agents.cv_builder_chat import apply_operation, styled_after
        from app.core.errors import DomainError

        try:
            op = op_model(**args.model_dump(exclude={"cv_id"}))
        except ValidationError as exc:
            raise DomainError(f"Invalid operation input: {exc}") from exc
        cv = await _owned_cv(db, ctx, args.cv_id)
        result = await apply_operation(db, cv, op)
        if not result.ok:
            raise DomainError(result.detail)
        out = result.model_dump(mode="json")
        if op.op in _STYLING_OPS:
            try:
                out["after"] = await styled_after(db, cv)
            except Exception:  # noqa: BLE001 — verify never breaks the op
                pass
        return out

    return _handler


async def _read_state(db, ctx: ToolContext, args: CvRefInput):
    from app.ai.agents.cv_builder_chat import build_builder_context

    cv = await _owned_cv(db, ctx, args.cv_id)
    return await build_builder_context(db, cv)


async def _review_visual(db, ctx: ToolContext, args: CvRefInput):
    from app.ai.agents.cv_builder_chat import (
        _critique_preview,
        build_builder_context,
    )

    cv = await _owned_cv(db, ctx, args.cv_id)
    digest = await build_builder_context(db, cv)
    critique, note = await _critique_preview(
        db,
        cv,
        user_id=ctx.user_id,
        lint=digest.get("lint") or {},
        rendered=digest.get("rendered") or [],
    )
    if critique is None:
        return {"available": False, "note": note}
    return {
        "available": True,
        "rendered": digest.get("rendered") or [],
        "summary": critique.summary,
        "issues": [issue.model_dump() for issue in critique.issues],
        "safe_token_fixes": critique.safe_token_fixes,
    }


def _tool(
    key,
    title,
    description,
    input_model,
    handler,
    scope,
    cost="cheap",
    audiences=None,
):
    return AITool(
        key=key,
        title=title,
        description=description,
        input_model=input_model,
        handler=handler,
        scope=scope,
        audiences=audiences or AUDIENCES,
        cost_hint=cost,
        requires_user=True,
    )


CV_BUILDER_TOOLS: list[AITool] = [
    _tool(
        "cv_read_state",
        "Read CV builder state",
        "Full digest of one CV: template, design, blocks, context "
        "selection, metrics, lint and `rendered` (the deterministic "
        "ground truth of what prints per section). For 'which profile "
        "items are on or off this CV', use `selection.include`/`selection."
        "exclude` (refs as 'source_key:item_id' strings), `selection.mode`"
        " and `selection.selected_items` (the ids actually rendered per "
        "source). `sources` maps every source_key to its items: off-CV "
        "items carry only {item_id, label, detail}; items with "
        "`selected`: true carry the EFFECTIVE layers this CV prints — "
        "`description` and `bullets` hold the text that renders (a "
        "pinned variant's text replaces the profile's, `variant`: true "
        "says so; an override patch wins over both) — never the original "
        "text next to the variant.",
        CvRefInput,
        _read_state,
        ToolScope.READ,
        audiences=frozenset({"cv_builder", "chat"}),
    ),
    _tool(
        "cv_review_visual",
        "Review CV preview visually",
        "Screenshot the rendered CV and run the vision critique "
        "(capability-detected). cv_id is required — pass the attached "
        "CV's id verbatim. The result includes `rendered`: the "
        "deterministic ground truth of what prints (per entry: headline, "
        "description/bullet layers; per section: with_description/"
        "with_bullets counts) — check every content claim of the "
        "critique against it and never explain an entry printing bullets "
        "when its `rendered` entry says otherwise.",
        CvRefInput,
        _review_visual,
        ToolScope.READ,
        cost="expensive",
        audiences=frozenset({"cv_builder", "chat"}),
    ),
    _tool(
        "cv_set_template",
        "Switch CV template",
        "Point the CV at another readable template.",
        SetTemplateInput,
        _op_wrapper(SetTemplateOp),
        ToolScope.WRITE,
        audiences=frozenset({"cv_builder", "chat"}),
    ),
    _tool(
        "cv_apply_theme",
        "Apply a CV theme",
        "Apply a curated theme to the rendered template.",
        ApplyThemeInput,
        _op_wrapper(ApplyThemeOp),
        ToolScope.WRITE,
        audiences=frozenset({"cv_builder", "chat"}),
    ),
    _tool(
        "cv_update_design",
        "Update CV styling",
        "Patch design tokens (colors, typography, layout) on the rendered template.",
        UpdateDesignInput,
        _op_wrapper(UpdateDesignOp),
        ToolScope.WRITE,
        audiences=frozenset({"cv_builder", "chat"}),
    ),
    _tool(
        "cv_set_context",
        "Select CV context items",
        "Change which profile items this CV includes/excludes (one op "
        "REPLACES the whole selection). Workflow: call cv_read_state "
        "first, echo its reported `selection.mode` and `selection."
        "include` verbatim, and only EXTEND `selection.exclude` with the "
        "newly hidden items (mode 'none' likewise only extends include). "
        "To add a previously hidden item, drop its ref from exclude; to "
        "restore one that was never on the CV, re-include it from "
        '`sources` ids. Each ref is an OBJECT {"source_key": str, '
        "\"item_id\": str} — split the 'source_key:item_id' strings from "
        "cv_read_state at the first ':'. Never switch modes or drop "
        "entries the user chose; describe the resulting change. An op "
        "that would deselect everything is refused.",
        SetContextInput,
        _op_wrapper(SetContextOp),
        ToolScope.WRITE,
        audiences=frozenset({"cv_builder", "chat"}),
    ),
    _tool(
        "cv_set_doc_options",
        "Update CV document options",
        "Title, page size, page budget, language.",
        SetDocOptionsInput,
        _op_wrapper(SetDocOptionsOp),
        ToolScope.WRITE,
    ),
    _tool(
        "cv_add_block",
        "Add CV section",
        "Insert one registry-valid block.",
        AddBlockInput,
        _op_wrapper(AddBlockOp),
        ToolScope.WRITE,
    ),
    _tool(
        "cv_remove_block",
        "Remove CV section",
        "Drop the block at an index.",
        BlockIndexInput,
        _op_wrapper(RemoveBlockOp),
        ToolScope.WRITE,
    ),
    _tool(
        "cv_move_block",
        "Reorder CV sections",
        "Move one block to a new position.",
        MoveBlockInput,
        _op_wrapper(MoveBlockOp),
        ToolScope.WRITE,
    ),
    _tool(
        "cv_update_block_props",
        "Configure CV section",
        "Merge a props patch into one block.",
        UpdateBlockPropsInput,
        _op_wrapper(UpdateBlockPropsOp),
        ToolScope.WRITE,
    ),
    _tool(
        "cv_set_override",
        "Rewrite CV text",
        "Patch one field of one resolved profile item for this CV.",
        SetOverrideInput,
        _op_wrapper(SetOverrideOp),
        ToolScope.WRITE,
    ),
    _tool(
        "cv_set_bullets",
        "Rewrite CV bullets",
        "Replace one experience/projects/volunteer item's bullet list on "
        "this CV with grounded, metric-honest lines.",
        SetBulletsInput,
        _op_wrapper(SetBulletsOp),
        ToolScope.WRITE,
    ),
]
