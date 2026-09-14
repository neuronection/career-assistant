"""CV template designer + visual reviewer.

Two audited AI tasks, both draft-then-approve:
- `cv_template_design`: brief → a full validated template package draft.
- `cv_template_review`: page images (printed/scanned export) + lint
  metrics → structured critique with safe token fixes.

Mock fixtures are deterministic so the whole loop runs offline in tests;
the mock reviewer parses `[PAGE n]` markers the same way the OCR mock does.
"""

from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.agents.context import context_json, parse_context
from app.ai.gateway import RunRef, ainvoke_structured, register_mock_fixture
from app.models.enums import AITaskType
from app.schemas.cv_template import CvVisualCritique, TemplateContent


def _mock_template_content(schema: type, user_prompt: str) -> dict:
    """Deterministic template draft: registry-valid, brief-aware accents.

    Modify mode (the polish loop's copy-rung): a `base_blocks` context
    echoes the base package back with the critique's structural ask
    applied — a sidebar mention moves the trailing compact blocks into
    the sidebar area."""
    ctx = parse_context(user_prompt)
    brief = str(ctx.get("brief", ""))
    density = str(ctx.get("density") or "normal")
    base_blocks = ctx.get("base_blocks")
    if base_blocks:
        blocks = [dict(block) for block in base_blocks]
        critique = str(ctx.get("critique") or "").lower()
        if "sidebar" in critique or "column" in critique:
            compact = {"skills", "languages", "interests", "certifications"}
            moved = 0
            for block in blocks:
                if moved >= 2:
                    break
                if str(block.get("kind")) in compact:
                    block["area"] = "sidebar"
                    moved += 1
            if moved:
                return {
                    "blocks": blocks,
                    "design": {"layout": "sidebar", "density": density},
                    "pages": {
                        "default_max_pages": int(ctx.get("page_budget") or 1),
                        "overflow_policy": "warn",
                    },
                    "prompts": {"field_prompts": {}},
                }
        return {
            "blocks": blocks,
            "design": {"density": density},
            "pages": {
                "default_max_pages": int(ctx.get("page_budget") or 1),
                "overflow_policy": "warn",
            },
            "prompts": {"field_prompts": {}},
        }
    accent = "#0f766e" if "green" in brief.lower() else "#1d4ed8"
    font = "serif" if "serif" in brief.lower() else "sans"
    sidebar = "sidebar" in brief.lower()
    blocks = [
        {"kind": "header", "props": {"show_links": True, "show_location": True}},
        {"kind": "summary", "props": {"title": "Summary", "max_chars": 600}},
        {
            "kind": "items",
            "props": {
                "title": "Work Experience",
                "source_key": "experience",
                "max_items": 8,
                "show_skills": True,
                "show_achievements": True,
            },
        },
        {
            "kind": "items",
            "props": {
                "title": "Education",
                "source_key": "education",
                "max_items": 5,
                "show_skills": False,
                "show_achievements": False,
            },
        },
        {
            "kind": "skills",
            "props": {
                "title": "Skills",
                "display": "chips",
                "show_levels": False,
                "max_items": 18,
            },
        },
        {
            "kind": "languages",
            "props": {"title": "Languages"},
        },
    ]
    design: dict = {"accent_color": accent, "font_stack": font, "density": density}
    if sidebar:
        blocks[-1]["area"] = "sidebar"
        blocks[-2]["area"] = "sidebar"
        design["layout"] = "sidebar"
    return {
        "blocks": blocks,
        "design": design,
        "pages": {
            "default_max_pages": int(ctx.get("page_budget") or 1),
            "overflow_policy": "warn",
        },
        "prompts": {"field_prompts": {"summary": "Lead with the strongest evidence."}},
    }


def _mock_visual_critique(schema: type, user_prompt: str) -> dict:
    """Deterministic critique; honors page-count markers in the prompt."""
    ctx = parse_context(user_prompt)
    pages = int(ctx.get("page_count") or 1)
    budget = int(ctx.get("max_pages") or 1)
    issues = []
    if pages > budget:
        issues.append(
            {
                "severity": "major",
                "area": "page_budget",
                "message": f"Content renders on {pages} pages but the budget is {budget}.",
            }
        )
    issues.append(
        {
            "severity": "minor",
            "area": "spacing",
            "message": "Section spacing looks tight under the header rule.",
        }
    )
    return {
        "issues": issues,
        "safe_token_fixes": {"spacing_scale": "1.1", "base_size_pt": "9.5"},
        "summary": "Layout is close to budget; minor spacing adjustments suggested.",
    }


register_mock_fixture(AITaskType.CV_TEMPLATE_DESIGN, _mock_template_content)
register_mock_fixture(AITaskType.CV_TEMPLATE_REVIEW, _mock_visual_critique)


AREA_RULES = (
    'Templates have layout areas: `design.layout` is "single" or '
    '"sidebar"; a sidebar layout splits blocks between two columns '
    'through each block\'s `area` field ("main" or "sidebar"). Assign '
    "compact scan-friendly sections (skills, languages, interests, "
    "certifications) to the sidebar and narrative sections (summary, "
    "experience, projects, education) to main. Declare "
    '`design.layout`="sidebar" only when at least one block carries '
    '`area`="sidebar" — and every sidebar-assigned block implies a '
    "sidebar layout. For sidebar layouts prefer margin_mm=0 with "
    "per-area padding (main_padding_mm, sidebar_padding_mm) so the "
    "colored column runs to the page edge."
)


def _normalize_areas(content: TemplateContent) -> TemplateContent:
    """Make `design.layout` and the blocks' areas agree.

    The renderer degrades gracefully either way, but a draft declaring
    `layout: sidebar` with no sidebar block (or the inverse) silently
    loses the designer's intent — align the token with the blocks."""
    has_sidebar = any(
        str(block.get("area") or block.get("column") or "") == "sidebar"
        for block in content.blocks
    )
    layout = "sidebar" if has_sidebar else "single"
    if content.design.layout != layout:
        return content.model_copy(
            update={"design": content.design.model_copy(update={"layout": layout})}
        )
    return content


async def draft_template(
    db: AsyncSession,
    user_id,
    *,
    brief: str,
    target_role: str = "",
    density: str = "normal",
    page_budget: int = 1,
    base_content: Optional[TemplateContent] = None,
    critique_message: str = "",
    run: Optional[RunRef] = None,
) -> TemplateContent:
    """Brief → validated template draft (author reviews before publish).

    With `base_content` this is the polish loop's modify-copy rung: the
    model returns the same package with the minimal structural changes
    the critique asks for, keeping the template's identity."""
    if base_content is not None:
        prompt = context_json(
            {
                "brief": brief,
                "critique": critique_message,
                "density": density,
                "page_budget": page_budget,
                "base_blocks": base_content.blocks,
                "base_design": base_content.design.model_dump(mode="json"),
                "base_pages": base_content.pages.model_dump(mode="json"),
            }
        )
        system = (
            "You modify an existing CV template package. Keep its "
            "identity — typography, accent, density — and change only "
            "what the critique requires. Return the FULL modified "
            "package. " + AREA_RULES
        )
    else:
        prompt = context_json(
            {
                "brief": brief,
                "target_role": target_role,
                "density": density,
                "page_budget": page_budget,
            }
        )
        system = (
            "You design CV templates as structured packages of blocks. "
            "Use only the registered block kinds provided in the brief; "
            "respect the page budget; keep typography readable. Leave "
            "design.margin_mm unset unless the brief explicitly asks for "
            "full-bleed or unusual margins; it is bounded 0-25mm. " + AREA_RULES
        )
    content = await ainvoke_structured(
        db,
        AITaskType.CV_TEMPLATE_DESIGN,
        TemplateContent,
        system=system,
        user=prompt,
        user_id=user_id,
        run=run,
    )
    return _normalize_areas(content)


async def critique_pages(
    db: AsyncSession,
    user_id,
    *,
    template_summary: str,
    lint: dict,
    max_pages: int,
    page_count: int,
    images: list[tuple[str, bytes]] | None = None,
) -> CvVisualCritique:
    """Vision critique of rendered pages; degrades to lint-only facts.

    With no images the model still receives the deterministic lint report
    and proposes token-level fixes (no vision required to be useful).
    """
    prompt = context_json(
        {
            "template_summary": template_summary,
            "lint": lint,
            "page_count": page_count,
            "max_pages": max_pages,
            "pages": [f"[PAGE {index}]" for index in range(page_count)],
        }
    )
    return await ainvoke_structured(
        db,
        AITaskType.CV_TEMPLATE_REVIEW,
        CvVisualCritique,
        system=(
            "You review CV page images for layout quality: overflow, "
            "crowding, alignment, hierarchy, contrast. Propose only safe "
            "design-token fixes; never invent CV content."
        ),
        user=prompt,
        user_id=user_id,
        images=images or None,
    )
