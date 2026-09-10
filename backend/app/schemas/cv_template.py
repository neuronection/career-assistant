"""CV template content schemas: the validated template package.

A template is data: ordered blocks (validated against the block-kind
registry in `app.services.cv_blocks`), design tokens emitted as CSS custom
properties, page rules, and optional per-field AI prompt overrides merged
over global defaults at AI-call time.
"""

import uuid
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

from app.models.enums import CvOverflowPolicy

HEX_COLOR = "^#[0-9a-fA-F]{6}$"


class DesignTokens(BaseModel):
    """Design tokens emitted as CSS custom properties by the renderer."""

    accent_color: str = Field(default="#1d4ed8", pattern=HEX_COLOR)
    text_color: str = Field(default="#111827", pattern=HEX_COLOR)
    muted_color: str = Field(default="#6b7280", pattern=HEX_COLOR)
    heading_color: str = Field(default="#0f172a", pattern=HEX_COLOR)
    background_color: str = Field(default="#ffffff", pattern=HEX_COLOR)
    font_stack: Literal["sans", "serif", "mixed", "geometric"] = "sans"
    base_size_pt: int = Field(default=10, ge=7, le=14)
    line_height: float = Field(default=1.35, ge=1.0, le=2.0)
    spacing_scale: float = Field(default=1.0, ge=0.6, le=1.8)
    header_style: Literal["left", "centered", "banner"] = "left"
    show_photo: bool = False
    density: Literal["compact", "normal", "roomy"] = "normal"
    margin_mm: Optional[int] = Field(default=None, ge=0, le=25)
    # Modern-layout tokens: section containers, corners, heading style.
    section_style: Literal["flat", "card"] = "flat"
    corner_radius: int = Field(default=0, ge=0, le=6)
    heading_case: Literal["uppercase", "title", "none"] = "uppercase"
    heading_weight: int = Field(default=600, ge=400, le=800)
    # Two-column layout: a colored sidebar holds its assigned blocks.
    heading_rule: Literal["line", "none", "accent"] = "line"
    show_icons: bool = True
    icon_size_mm: float = Field(default=3.2, ge=2.0, le=6.0)
    photo_shape: Literal["circle", "rounded", "square"] = "circle"
    photo_size_mm: int = Field(default=22, ge=10, le=40)
    section_gap_mm: Optional[int] = Field(default=None, ge=0, le=14)
    item_gap_mm: Optional[int] = Field(default=None, ge=0, le=8)
    border_color: str = Field(default="#e5e7eb", pattern=HEX_COLOR)
    layout: Literal["single", "sidebar"] = "single"
    sidebar_side: Literal["left", "right"] = "left"
    sidebar_color: str = Field(default="#16324f", pattern=HEX_COLOR)
    sidebar_text_color: str = Field(default="#ffffff", pattern=HEX_COLOR)
    sidebar_width_pct: int = Field(default=34, ge=25, le=45)


class PagesConfig(BaseModel):
    default_max_pages: int = Field(default=1, ge=1, le=10)
    overflow_policy: CvOverflowPolicy = CvOverflowPolicy.WARN


class PromptOverrides(BaseModel):
    """Per-field AI guidance, versioned with the template."""

    field_prompts: dict[str, str] = Field(default_factory=dict, max_length=50)
    field_handling: str = Field(default="", max_length=2000)


class TemplateContent(BaseModel):
    """The full validated template package stored on every version row."""

    blocks: list[dict] = Field(min_length=1, max_length=25)
    design: DesignTokens = Field(default_factory=DesignTokens)
    pages: PagesConfig = Field(default_factory=PagesConfig)
    prompts: PromptOverrides = Field(default_factory=PromptOverrides)

    @field_validator("blocks")
    @classmethod
    def _blocks_must_validate(cls, value: list[dict]) -> list[dict]:
        from app.services.cv_blocks import validate_blocks

        validate_blocks(value)
        return value

    def merged_prompts(self) -> dict[str, str]:
        """Template overrides layered over the global field defaults."""
        from app.services.cv_blocks import GLOBAL_FIELD_PROMPTS

        merged = dict(GLOBAL_FIELD_PROMPTS)
        for path, guidance in self.prompts.field_prompts.items():
            base = merged.get(path, "")
            merged[path] = f"{base}\n{guidance}".strip() if base else guidance
        if self.prompts.field_handling:
            merged["__handling__"] = (
                f"{merged.get('__handling__', '')}\n{self.prompts.field_handling}".strip()
            )
        return merged


class CvTemplateOut(BaseModel):
    id: uuid.UUID
    key: str
    version: int
    title: str
    description: str
    author_key: str
    source: str
    visibility: str
    language: str
    page_size: str
    ats_safe: bool
    status: str
    content: dict
    content_hash: str

    model_config = {"from_attributes": True}


class CvTemplateExport(BaseModel):
    """File-first export package."""

    schema_version: int = 1
    kind: Literal["cv_template"] = "cv_template"
    metadata: dict
    content: dict
    content_hash: str


class CvVisualIssue(BaseModel):
    severity: Literal["minor", "major"]
    area: str = Field(min_length=1, max_length=80)
    message: str = Field(min_length=1, max_length=500)


class CvVisualCritique(BaseModel):
    """Structured output of the visual-review task (vision or lint)."""

    issues: list[CvVisualIssue] = Field(default_factory=list, max_length=20)
    safe_token_fixes: dict[str, str] = Field(default_factory=dict, max_length=20)
    summary: str = Field(default="", max_length=1000)


class VisualReviewRequest(BaseModel):
    """Optional page images (printed/scanned) ground the vision critique.

    Without images the deterministic renderer-metrics lint runs alone.
    """

    page_count: Optional[int] = Field(default=None, ge=1, le=10)
