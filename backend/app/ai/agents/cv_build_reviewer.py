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


def _ref_ids(refs: list) -> list[str]:
    """Matrix ids may arrive as `{item_id}` refs or bare ids — both echo."""
    return [str(ref["item_id"] if isinstance(ref, dict) else ref) for ref in refs]


def _mock_build_critique(schema: type, user_prompt: str) -> dict:
    """State-aware critique: content only while triggers persist.

    - a lint-fail check ⇒ one fail-level issue with a safe fix;
    - empty block kinds ⇒ one move fix (disappears once filled);
    - a page-budget overrun ⇒ fail + `set_doc_options`;
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
        issues.append(
            {
                "level": "fail",
                "area": "page_budget",
                "message": (
                    f"Content needs {lint.get('pages_actual')} pages but "
                    f"the budget is {lint.get('max_pages')}."
                ),
                "suggested_ops": [
                    {
                        "operation": {
                            "op": "set_doc_options",
                            "max_pages": min(3, int(lint.get("max_pages") or 1) + 1),
                        },
                        "rationale": "budget exceeded; widen before trimming",
                    }
                ],
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
    run: Optional[RunRef] = None,
    with_ref: bool = False,
) -> "CvBuildCritique | tuple[CvBuildCritique, dict]":
    """Critique the rendered draft: layout, density and content coverage.

    `lint` is the deterministic report, `coverage` the deterministic
    matrix (`available` cut into included/dropped/missing); both are
    host-side truth — the model judges and suggests, it never audits ids
    on its own.
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
                }
                for index, block in enumerate(blocks)
            ],
            "page_count": page_count,
            "max_pages": max_pages,
            "iteration": iteration,
            "pages": [f"[PAGE {index}]" for index in range(page_count)],
        }
    )
    if with_ref:
        return await ainvoke_structured(
            db,
            AITaskType.CV_BUILD_REVIEW,
            CvBuildCritique,
            system=(
                "You review a generated CV for a final professional pass: page "
                "images for layout/density/typography, the lint report for "
                "structural facts, and the coverage matrix for content that "
                "should have landed. Each issue carries a level: fail (blocks "
                "readiness), warn, info. Only suggest existing BuilderOps "
                "(add_block/remove_block/move_block/update_block_props/"
                "set_override/set_context/set_doc_options/update_design/"
                "apply_theme/set_template) that are truly safe for the stated "
                "area; never invent content or render HTML."
            ),
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
        system=(
            "You review a generated CV for a final professional pass: page "
            "images for layout/density/typography, the lint report for "
            "structural facts, and the coverage matrix for content that "
            "should have landed. Each issue carries a level: fail (blocks "
            "readiness), warn, info. Only suggest existing BuilderOps "
            "(add_block/remove_block/move_block/update_block_props/"
            "set_override/set_context/set_doc_options/update_design/"
            "apply_theme/set_template) that are truly safe for the stated "
            "area; never invent content or render HTML."
        ),
        user=prompt,
        user_id=user_id,
        images=images or None,
        run=run,
    )
