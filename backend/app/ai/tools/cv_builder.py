"""CV builder copilot tools — the builder operations, registered.

The executors live in ``app.ai.agents.cv_builder_chat`` (single source,
the same functions the turn loop runs); this module wraps them as
registry objects so the registry lists them and the MCP layer
(41b) can later expose the read-scope readers. Write scope = mutators;
every handler resolves the owned CV from the ToolContext user.
"""

from typing import Optional

from pydantic import BaseModel, Field

from app.ai.tools.base import AITool, ToolContext, ToolScope
from app.schemas.cv_assistant import (
    AddBlockOp,
    ApplyThemeOp,
    MoveBlockOp,
    RemoveBlockOp,
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
    mode: str = "custom"
    include: list[dict] = Field(default_factory=list, max_length=200)
    exclude: list[dict] = Field(default_factory=list, max_length=200)


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


async def _owned_cv(db, ctx: ToolContext, cv_id: str):
    from uuid import UUID

    from app.core.errors import PermissionDeniedError
    from app.services.cv_service import CvService

    if ctx.user_id is None:
        raise PermissionDeniedError("A signed-in user is required")
    return await CvService(db).get_owned(UUID(cv_id), ctx.user_id)


def _op_wrapper(op_model):
    """Wrap one builder operation: load the owned CV, apply, return dict."""

    async def _handler(db, ctx: ToolContext, args):
        from pydantic import ValidationError

        from app.ai.agents.cv_builder_chat import apply_operation
        from app.core.errors import DomainError

        try:
            op = op_model(**args.model_dump(exclude={"cv_id"}))
        except ValidationError as exc:
            raise DomainError(f"Invalid operation input: {exc}") from exc
        cv = await _owned_cv(db, ctx, args.cv_id)
        result = await apply_operation(db, cv, op)
        if not result.ok:
            raise DomainError(result.detail)
        return result.model_dump(mode="json")

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
        db, cv, user_id=ctx.user_id, lint=digest.get("lint") or {}
    )
    if critique is None:
        return {"available": False, "note": note}
    return {
        "available": True,
        "summary": critique.summary,
        "issues": [issue.model_dump() for issue in critique.issues],
        "safe_token_fixes": critique.safe_token_fixes,
    }


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


CV_BUILDER_TOOLS: list[AITool] = [
    _tool(
        "cv_read_state",
        "Read CV builder state",
        "Full digest of one CV: template, design, blocks, context "
        "selection, metrics and lint.",
        CvRefInput,
        _read_state,
        ToolScope.READ,
    ),
    _tool(
        "cv_review_visual",
        "Review CV preview visually",
        "Screenshot the rendered CV and run the vision critique (capability-detected).",
        CvRefInput,
        _review_visual,
        ToolScope.READ,
        cost="expensive",
    ),
    _tool(
        "cv_set_template",
        "Switch CV template",
        "Point the CV at another readable template.",
        SetTemplateInput,
        _op_wrapper(SetTemplateOp),
        ToolScope.WRITE,
    ),
    _tool(
        "cv_apply_theme",
        "Apply a CV theme",
        "Apply a curated theme to the rendered template.",
        ApplyThemeInput,
        _op_wrapper(ApplyThemeOp),
        ToolScope.WRITE,
    ),
    _tool(
        "cv_update_design",
        "Update CV styling",
        "Patch design tokens (colors, typography, layout) on the rendered template.",
        UpdateDesignInput,
        _op_wrapper(UpdateDesignOp),
        ToolScope.WRITE,
    ),
    _tool(
        "cv_set_context",
        "Select CV context items",
        "Replace which profile items the CV includes.",
        SetContextInput,
        _op_wrapper(SetContextOp),
        ToolScope.WRITE,
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
]
