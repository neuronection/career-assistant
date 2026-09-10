"""CV template designer + visual reviewer.

Two audited AI tasks, both draft-then-approve:
- `cv_template_design`: brief → a full validated template package draft.
- `cv_template_review`: page images (printed/scanned export) + lint
  metrics → structured critique with safe token fixes.

Mock fixtures are deterministic so the whole loop runs offline in tests;
the mock reviewer parses `[PAGE n]` markers the same way the OCR mock does.
"""

from app.ai.agents.context import context_json, parse_context
from app.ai.gateway import ainvoke_structured, register_mock_fixture
from app.models.enums import AITaskType
from app.schemas.cv_template import CvVisualCritique, TemplateContent
from sqlalchemy.ext.asyncio import AsyncSession


def _mock_template_content(schema: type, user_prompt: str) -> dict:
    """Deterministic template draft: registry-valid, brief-aware accents."""
    ctx = parse_context(user_prompt)
    brief = str(ctx.get("brief", ""))
    density = str(ctx.get("density") or "normal")
    accent = "#0f766e" if "green" in brief.lower() else "#1d4ed8"
    font = "serif" if "serif" in brief.lower() else "sans"
    return {
        "blocks": [
            {"kind": "header", "props": {"show_links": True, "show_location": True}},
            {"kind": "summary", "props": {"title": "Summary", "max_chars": 600}},
            {
                "kind": "items",
                "props": {
                    "title": "Experience",
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
        ],
        "design": {"accent_color": accent, "font_stack": font, "density": density},
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


async def draft_template(
    db: AsyncSession,
    user_id,
    *,
    brief: str,
    target_role: str = "",
    density: str = "normal",
    page_budget: int = 1,
) -> TemplateContent:
    """Brief → validated template draft (author reviews before publish)."""
    prompt = context_json(
        {
            "brief": brief,
            "target_role": target_role,
            "density": density,
            "page_budget": page_budget,
        }
    )
    return await ainvoke_structured(
        db,
        AITaskType.CV_TEMPLATE_DESIGN,
        TemplateContent,
        system=(
            "You design CV templates as structured packages of blocks. "
            "Use only the registered block kinds provided in the brief; "
            "respect the page budget; keep typography readable. Leave "
            "design.margin_mm unset unless the brief explicitly asks for "
            "full-bleed or unusual margins; it is bounded 0-25mm."
        ),
        user=prompt,
        user_id=user_id,
    )


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
