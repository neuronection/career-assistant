"""CV build reviewer — the polish-loop's vision critique.

`cv_build_review` looks at the actually-rendered draft (page PNGs,
deterministic lint, content-coverage matrix, current blocks) and returns
fail/warn/info findings plus `suggested_ops` in the existing BuilderOp
shapes. The model never edits anything itself: the polish loop's
deterministic applier re-validates and applies the ops it names.

The mock fixture is state-aware so tests drive the loop deterministically:
it only raises an issue while the input still shows its trigger — a clean
lint + complete coverage in ⇒ a clean critique out — so bounded-stop
assertions actually stop.
"""

from typing import Literal, Optional, overload

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.agents.context import context_json, parse_context
from app.ai.gateway import RunRef, ainvoke_structured, register_mock_fixture
from app.ai.schemas import CvBuildCritique
from app.models.enums import AITaskType

REVIEW_SYSTEM = (
    "You review a generated CV for a final professional pass: page "
    "images for layout/density/typography, the lint report for "
    "structural facts, and the coverage matrix for content that should "
    "have landed. The request may carry the user's brief (user_notes): "
    "judge the build against it too — e.g. a 'modern / sidepanel / "
    "two-column' brief makes a long plain single-column list a layout "
    "finding. Each issue carries a level: fail (blocks readiness), "
    "warn, info. Only suggest existing BuilderOps "
    "(add_block/remove_block/move_block/update_block_props/"
    "set_override/set_context/set_doc_options/update_design/"
    "apply_theme/set_template) that are truly safe for the stated area; "
    "never invent content or render HTML. The page budget is the "
    "user's constraint: NEVER suggest set_doc_options that raises "
    "max_pages. Fix an over-budget build by DENSIFYING first "
    "(update_design: base_size_pt 7–14, line_height 1.0–2.0, "
    "spacing_scale 0.6–1.8, section_gap_mm 0–14, item_gap_mm 0–8, "
    "sidebar_width_pct 25–45, icon_size_mm 2–6, photo_size_mm 10–40 — "
    "tighter type and spacing fit more content without cutting "
    "information; the pt/mm tokens are INTEGERS (8 or 9, never 8.5) "
    "and font_stack sans/serif/mixed/geometric + the heading tokens "
    "remain look levers, not fit levers), then trimming "
    "content (set_context exclude, remove_block, a smaller skills "
    "max_items) only when even the compact layout cannot fit it. "
    "Capping a section's max_items is a LOSSY last resort: prefer "
    "trimming duplicated/low-signal sources, then shortening long "
    "descriptions, before cutting whole entries; when you do cap, keep "
    "as many items as the fitted layout supports — do not jump to a "
    "small cap (4 or fewer) while denser levers or per-item "
    "shortening are still unused, and say in the issue text which "
    "items were dropped and why. A projects section that holds 6-8 "
    "short entries on a densified page beats 4 generous ones. "
    "When you cap or when a block keeps fewer entries than the source "
    "offers, SELECT which entries survive: an `order` list of item ids "
    "(update_block_props — the ids are in each block's source listing; "
    "the user's/pre-ordered entries render first and decide what "
    "truncation keeps) must accompany the cap, aligned with the brief "
    "— truncation otherwise keeps whatever arrived first, silently "
    "hiding exactly the entries the brief asked to emphasize. "
    "For hiding whole entries, context is the cleanest lever: "
    "set_context echoing the reported `context_selection` (SAME mode, "
    "include and pins echoed verbatim) with ONLY the exclude list "
    "extended by the target item ids ({source_key, item_id}). Mode "
    "all + targeted excludes disables just those items and keeps "
    "everything else; the Context tab shows and reverses it — far more "
    "expressive than a count cap, and it never invents or assumes: "
    "never switch modes (all/none/custom) and never shrink an include "
    "list the user already chose. Prefer an exclusion when a whole "
    "entry is unwanted; prefer cap+order when it is only a block-local "
    "display fit. "
    "Sidebar content that clips or wraps badly says widen "
    "sidebar_width_pct or densify, never drop the section. "
    "The user_notes ARE the brief: any request that describes the "
    "desired look — naming an aesthetic (e.g. 'Material 3 expressive', "
    "'minimal swiss', 'brutalist') OR clearly asking for one ('modern "
    "professional', 'elegant', 'catchy', 'a distinctive banner look') — "
    "is a style constraint you must honor. When the rendered pages "
    "clearly do not reflect it even after the safe "
    'token fixes you can suggest, add an issue with area "style": '
    'level "fail" (the render missed a requested look — '
    "this routes the brief to the template designer) when the look is "
    'explicit and unaddressed, otherwise "warn"; describe the gap '
    "against the brief. apply_theme on a curated theme is the FIRST "
    "remedy when a theme's palette matches the brief — its theme_key "
    "MUST be one of the keys listed in the context's `themes` — never "
    "invent one; when no listed theme fits, use update_design tokens "
    "instead. "
    'Style findings MUST use area "style" — never "layout" or '
    '"structure": those areas mean geometry problems (overflow, '
    "orphaned sections, broken columns) and revert freshly redesigned "
    "templates. Judge only the pages in front of you: never re-raise a "
    "style finding the current render has already addressed. "
    "If the summary or an override field carries obvious "
    "placeholder/test artifacts (e.g. '(Test — 123123213)') or notes "
    "copied verbatim from the profile's aspirations, suggest a "
    "set_override op (source_key summary, field summary) rewriting it "
    "into clean, professional prose — direction from the profile "
    "informs the text, it is never quoted."
)


def _ref_ids(refs: list) -> list[str]:
    """Matrix ids may arrive as `{item_id}` refs or bare ids — both echo."""
    return [str(ref["item_id"] if isinstance(ref, dict) else ref) for ref in refs]


_REVIEW_PROPS_KEYS = frozenset(
    {
        "source_key",
        "display",
        "max_items",
        "show_levels",
        "kinds",
        "order",
        "container",
        "selected",
    }
)


def _review_props(props: dict) -> dict:
    """The block props the reviewer can reason about (bounded snapshot).

    Skills selections render as the resolved id list (≤12 labels), item
    ordering rides `order`, synth-stars surface via `props` keys above."""
    out: dict = {
        key: props[key]
        for key in _REVIEW_PROPS_KEYS
        if key in props and props[key] not in (None, "")
    }
    selected = props.get("selected")
    if isinstance(selected, list):
        out["selected"] = [str(item) for item in selected[:12]]
        if len(selected) > 12:
            out["selected_count"] = len(selected)
    if isinstance(out.get("order"), list) and out["order"]:
        out["order"] = out["order"][:12]
    return out


def _mock_build_critique(schema: type, user_prompt: str) -> dict:
    """State-aware critique: content only while triggers persist.

    - a lint-fail check ⇒ one fail-level issue with a safe fix;
    - empty block kinds ⇒ one move fix (disappears once filled);
    - a page-budget overrun ⇒ fail + a content-trim suggestion (the
      budget never grows);
    - unused matrix ids ⇒ one coverage fix on the first missing
      item's source block (disappears once covered).

    Clean lint + complete coverage in ⇒ clean critique out, so the
    polish loop's bounded-stop tests actually stop.
    """
    ctx = parse_context(user_prompt)
    lint = ctx.get("lint") or {}
    checks = lint.get("checks") or []
    coverage = ctx.get("coverage") or {}
    blocks = ctx.get("blocks") or []

    issues: list[dict] = []

    def _kind_index(kind_like: str) -> int:
        return next(
            (
                idx
                for idx, block in enumerate(blocks)
                if kind_like
                in {
                    str((block or {}).get("kind") or ""),
                    str(((block or {}).get("props") or {}).get("source_key") or ""),
                }
            ),
            0,
        )

    for check in checks:
        if str((check or {}).get("level")) == "fail":
            issues.append(
                {
                    "level": "fail",
                    "area": "content",
                    "message": f"{check['message']} Fix before the final pass.",
                }
            )

    for kind in lint.get("empty_blocks") or []:
        issues.append(
            {
                "level": "warn",
                "area": "density",
                "message": f"The {kind} area renders empty — redistribute content.",
                "suggested_ops": [
                    {
                        "operation": {
                            "op": "move_block",
                            "block_index": _kind_index(kind),
                            "to_index": max(0, len(blocks) - 1),
                        },
                        "rationale": "fill the empty area before the final pass",
                    }
                ],
            }
        )

    if lint.get("pages_actual_over_budget"):
        skills_index = _kind_index("skills")
        trim_ops: list[dict] = [
            {
                "operation": {
                    "op": "update_design",
                    "design": {"base_size_pt": 9, "spacing_scale": 0.9},
                },
                "rationale": (
                    "densify first — tighter type and spacing fit more "
                    "content within the fixed page budget"
                ),
            }
        ]
        if skills_index is not None:
            trim_ops.append(
                {
                    "operation": {
                        "op": "update_block_props",
                        "block_index": skills_index,
                        "props": {"max_items": 8},
                    },
                    "rationale": (
                        "trim the skills list to the strongest entries "
                        "within the fixed page budget"
                    ),
                }
            )
        issues.append(
            {
                "level": "fail",
                "area": "page_budget",
                "message": (
                    f"Content needs {lint.get('pages_actual')} pages but "
                    f"the budget is {lint.get('max_pages')}. Densify, then "
                    f"trim what still does not fit — the budget never grows."
                ),
                "suggested_ops": trim_ops,
            }
        )

    missing = list(coverage.get("missing") or [])
    if missing:
        first = missing[0]
        source_key = (
            str(first.get("source_key") or "") if isinstance(first, dict) else ""
        )
        label = str(first.get("label") or "") if isinstance(first, dict) else str(first)
        if source_key:
            # Per-round include/omit assessment: suggest the full
            # custom selection — the current coverage plus the first
            # usable gaps — instead of a generic max_items nudge.
            included_refs = [
                ref
                for ref in (coverage.get("included") or [])
                if isinstance(ref, dict)
                and ref.get("source_key")
                and ref.get("item_id")
            ]
            keep = {f"{ref['source_key']}:{ref['item_id']}" for ref in included_refs}
            combined = (
                list(included_refs)
                + [
                    ref
                    for ref in missing
                    if isinstance(ref, dict)
                    and ref.get("source_key")
                    and ref.get("item_id")
                    and f"{ref['source_key']}:{ref['item_id']}" not in keep
                ][:8]
            )
            issues.append(
                {
                    "level": "warn",
                    "area": "coverage",
                    "message": f"Usable {source_key} item not on the CV: {label}.",
                    "suggested_ops": [
                        {
                            "operation": {
                                "op": "set_context",
                                "mode": "none",
                                "include": combined,
                                "exclude": [],
                            },
                            "rationale": (
                                f"selection keeps the covered items and adds "
                                f"the first usable {source_key} item(s)"
                            ),
                        }
                    ],
                }
            )
    covered = _ref_ids(coverage.get("included") or [])
    return {
        "summary": (
            "Build looks ready." if not issues else f"{len(issues)} finding(s)."
        ),
        "issues": issues,
        "coverage": {
            "covered": covered,
            "dropped_knowingly": _ref_ids(coverage.get("dropped") or []),
            "missing": _ref_ids(missing),
        },
    }


register_mock_fixture(AITaskType.CV_BUILD_REVIEW, _mock_build_critique)


@overload
async def review_build(
    db: AsyncSession,
    user_id,
    *,
    template_summary: str,
    lint: dict,
    coverage: dict,
    blocks: list[dict],
    page_count: int,
    max_pages: int,
    iteration: int,
    images: Optional[list[tuple[str, bytes]]] = None,
    notes: str = "",
    synth_applied: Optional[dict] = None,
    overrides: Optional[dict] = None,
    themes: Optional[list[dict]] = None,
    run: Optional[RunRef] = None,
    with_ref: Literal[False] = False,
) -> CvBuildCritique: ...


@overload
async def review_build(
    db: AsyncSession,
    user_id,
    *,
    template_summary: str,
    lint: dict,
    coverage: dict,
    blocks: list[dict],
    page_count: int,
    max_pages: int,
    iteration: int,
    images: Optional[list[tuple[str, bytes]]] = None,
    notes: str = "",
    synth_applied: Optional[dict] = None,
    overrides: Optional[dict] = None,
    themes: Optional[list[dict]] = None,
    run: Optional[RunRef] = None,
    with_ref: Literal[True] = True,
) -> "tuple[CvBuildCritique, dict]": ...


async def review_build(
    db: AsyncSession,
    user_id,
    *,
    template_summary: str,
    lint: dict,
    coverage: dict,
    blocks: list[dict],
    page_count: int,
    max_pages: int,
    iteration: int,
    images: Optional[list[tuple[str, bytes]]] = None,
    notes: str = "",
    synth_applied: Optional[dict] = None,
    overrides: Optional[dict] = None,
    themes: Optional[list[dict]] = None,
    selection: Optional[dict] = None,
    run: Optional[RunRef] = None,
    with_ref: bool = False,
) -> "CvBuildCritique | tuple[CvBuildCritique, dict]":
    """Critique the rendered draft: layout, density and content coverage.

    `lint` is the deterministic report, `coverage` the deterministic
    matrix (`available` cut into included/dropped/missing); both are
    host-side truth — the model judges and suggests, it never audits ids
    on its own. `notes` is the user's brief the build must satisfy.
    `selection` is the CV's current context selection (mode + include/
    exclude refs) — the model echoes it verbatim when suggesting a
    targeted `set_context` exclusion. `synth_applied` (`{ref_key:
    synth_id}`) and `override_fields` (`{ref_key: [fields]}`) say
    exactly which items lean on a synthesized variant or a manual field
    patch.
    """
    prompt = context_json(
        {
            "template_summary": template_summary,
            "lint": lint,
            "coverage": coverage,
            "blocks": [
                {
                    "index": index,
                    "kind": str(block.get("kind") or ""),
                    "area": str(block.get("area") or "main"),
                    "title": str((block.get("props") or {}).get("title") or ""),
                    "props": _review_props(block.get("props") or {}),
                }
                for index, block in enumerate(blocks)
            ],
            "synth_applied": synth_applied or {},
            "override_fields": overrides or {},
            "themes": themes or [],
            "context_selection": selection or {},
            "page_count": page_count,
            "max_pages": max_pages,
            "iteration": iteration,
            "pages": [f"[PAGE {index}]" for index in range(page_count)],
            "user_notes": notes,
        }
    )
    if with_ref:
        return await ainvoke_structured(
            db,
            AITaskType.CV_BUILD_REVIEW,
            CvBuildCritique,
            system=REVIEW_SYSTEM,
            user=prompt,
            user_id=user_id,
            images=images or None,
            run=run,
            with_audit_ref=True,
        )
    return await ainvoke_structured(
        db,
        AITaskType.CV_BUILD_REVIEW,
        CvBuildCritique,
        system=REVIEW_SYSTEM,
        user=prompt,
        user_id=user_id,
        images=images or None,
        run=run,
    )
