"""CV builder copilot schemas: the typed operation vocabulary.

The copilot's model output is a `CvBuilderTurn`: an answer plus a bounded
list of tagged operations. Every operation validates against the same
registries the API uses (block kinds, design tokens, context sources) at
application time — the schema only fixes the shape, never the values.
"""

from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, Field

from app.schemas.cv import CvContextRef


class SetTemplateOp(BaseModel):
    """Point the CV at a readable template (bank or the owner's own)."""

    op: Literal["set_template"]
    template_id: str = Field(min_length=8, max_length=64)


class ApplyThemeOp(BaseModel):
    """Apply a curated theme (key from the themes registry)."""

    op: Literal["apply_theme"]
    theme_key: str = Field(min_length=1, max_length=64)


class UpdateDesignOp(BaseModel):
    """Patch design tokens on the rendered template (duplicate-if-bank)."""

    op: Literal["update_design"]
    design: dict[str, Union[str, int, float, bool]] = Field(min_length=1, max_length=30)


class SetContextOp(BaseModel):
    """Replace the context selection (same contract as PUT /cv/{id}/context)."""

    op: Literal["set_context"]
    mode: Literal["all", "none", "custom"] = "custom"
    include: list[CvContextRef] = Field(default_factory=list, max_length=200)
    exclude: list[CvContextRef] = Field(default_factory=list, max_length=200)


class SetDocOptionsOp(BaseModel):
    """Document-level options: title, page size, page budget, language."""

    op: Literal["set_doc_options"]
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    page_size: Optional[Literal["a4", "letter"]] = None
    max_pages: Optional[int] = Field(default=None, ge=1, le=10)
    language: Optional[str] = Field(default=None, min_length=2, max_length=10)


class AddBlockOp(BaseModel):
    """Append (or insert at a position) one registry-valid block."""

    op: Literal["add_block"]
    kind: str = Field(min_length=1, max_length=40)
    props: dict = Field(default_factory=dict, max_length=30)
    position: Optional[int] = Field(default=None, ge=0, le=24)


class RemoveBlockOp(BaseModel):
    """Drop the block at a context-listed index."""

    op: Literal["remove_block"]
    block_index: int = Field(ge=0, le=24)


class MoveBlockOp(BaseModel):
    """Move one block to a new position (bounds-clamped)."""

    op: Literal["move_block"]
    block_index: int = Field(ge=0, le=24)
    to_index: int = Field(ge=0, le=24)


class UpdateBlockPropsOp(BaseModel):
    """Merge a props patch into the block at a context-listed index."""

    op: Literal["update_block_props"]
    block_index: int = Field(ge=0, le=24)
    props: dict[str, Union[str, int, float, bool, list, dict]] = Field(
        min_length=1, max_length=30
    )


class SetOverrideOp(BaseModel):
    """Field patch over one resolved context item (editor override)."""

    op: Literal["set_override"]
    source_key: str = Field(min_length=1, max_length=40)
    item_id: str = Field(min_length=1, max_length=64)
    field: str = Field(min_length=1, max_length=80)
    value: str = Field(min_length=1, max_length=4000)


BuilderOp = Annotated[
    Union[
        SetTemplateOp,
        ApplyThemeOp,
        UpdateDesignOp,
        SetContextOp,
        SetDocOptionsOp,
        AddBlockOp,
        RemoveBlockOp,
        MoveBlockOp,
        UpdateBlockPropsOp,
        SetOverrideOp,
    ],
    Field(discriminator="op"),
]


class CvBuilderTurn(BaseModel):
    """One copilot turn: reply text + bounded operation plan."""

    answer: str = Field(min_length=1, max_length=4000)
    operations: list[BuilderOp] = Field(default_factory=list, max_length=12)
    need_visual_review: bool = False


class OpResult(BaseModel):
    """Application outcome of one operation (failed ops never abort)."""

    op: str
    ok: bool
    detail: str = Field(default="", max_length=300)
