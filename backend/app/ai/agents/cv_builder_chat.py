"""CV builder copilot agent.

One audited task (`cv_builder_chat`) turns a chat message into a bounded
`CvBuilderTurn`: an answer plus validated operations. Operations apply
through the same services the API uses (template versioning rules, block
registry, context engine — never hand-rolled SQL), the rendered preview
can be screenshotted and vision-critiqued (capability-detected, one
bounded refine round), and every turn that changed something snapshots an
`ai_apply` version so the user can restore in one click. Failed
operations never abort the turn — they are reported honestly in the op
trace.
"""

import asyncio
import copy
import json
import time
from typing import AsyncIterator, Optional, TYPE_CHECKING, cast

if TYPE_CHECKING:
    from app.schemas.cv_template import CvVisualCritique
    from app.models.cv_template_model import CvTemplate
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.agents.context import context_json, parse_context
from app.ai.gateway import StructuredStream, partial_answer_text, register_mock_fixture
from app.core.errors import DomainError, ValidationError
from app.models.enums import AITaskType, CvVersionCreator
from app.schemas.cv import CvContextSelection
from app.schemas.cv_assistant import CvBuilderTurn, OpResult
from app.schemas.cv_template import DesignTokens, TemplateContent
from app.services.cv_context_service import CV_CONTEXT_SOURCES, resolve_sources
from app.services.cv_pdf_service import html_to_pngs, pdf_engine_available
from app.services.cv_themes import CV_THEMES, THEMES_BY_KEY

SYSTEM = (
    "You are the CV Builder assistant inside Career Assistant's CV Studio. "
    "You receive the full builder state as JSON: the document options, the "
    "rendered template (id, design tokens), the ordered blocks (each with "
    "its index, kind and props), the editor overrides, the current context "
    "selection, every available profile item per source (with item_id), the "
    "render metrics, the lint report, the available themes and templates.\n"
    "You help by replying AND, when the user asks for changes, by emitting "
    "operations from exactly this vocabulary:\n"
    "- set_template {template_id} — switch the CV's template (ids from "
    "`templates`; the current one is excluded from that list).\n"
    "- apply_theme {theme_key} — apply a curated theme (keys from `themes`).\n"
    "- update_design {design} — patch design-token fields (accent_color, "
    "text_color, heading_color, font_stack, base_size_pt, line_height, "
    "spacing_scale, density, header_style, margin_mm, section_style, "
    "corner_radius, heading_case, heading_weight, heading_rule, layout, "
    "sidebar_side, sidebar_color, sidebar_width_pct, show_icons, "
    "icon_size_mm, show_photo, photo_shape, photo_size_mm, section_gap_mm, "
    "item_gap_mm). Hex colors look like #1d4ed8. Styling a bank template "
    "automatically customizes a private copy.\n"
    "- set_context {mode, include[], exclude[]} — select which profile "
    "items the CV uses; refs are {source_key, item_id} pairs from "
    "`sources`. Exclusions always win.\n"
    "- set_doc_options {title, page_size, max_pages, language}.\n"
    "- add_block {kind, props, position} / remove_block {block_index} / "
    "move_block {block_index, to_index} / update_block_props {block_index, "
    "props} — sections come from `blocks` with their 0-based index; kinds "
    "and props follow the block registry (header, summary, items with "
    "source_key, skills with display, languages, achievements, interests, "
    "custom_text, letter, spacer).\n"
    "- set_override {source_key, item_id, field, value} — rewrite one "
    "field of one profile item for THIS CV only (e.g. summary/summary, "
    "experience/description, education/description, basics/headline; "
    "allowed fields per source are in `override_fields`). Rephrase the "
    "user's real content; never invent employers, dates or skills.\n"
    "Rules: at most 12 operations, applied in order. Use block_index and "
    "item_id values exactly as listed in the state. Set "
    "`need_visual_review` true when the user asks about looks, layout, "
    "spacing or page fit — or after visual changes you want to verify. "
    "Answer concisely, list what you changed, and suggest one next step. "
    "If the request is conversational, return no operations."
)

MAX_REFINE_ROUNDS = 2
_PROP_CAP = 240

OVERRIDE_FIELD_HINTS = {
    "basics": ["headline"],
    "summary": ["summary"],
    "experience": ["title", "org", "description"],
    "education": ["title", "description"],
}

OP_TITLES = {
    "set_template": "Switching template",
    "apply_theme": "Applying theme",
    "update_design": "Updating styling",
    "set_context": "Updating context selection",
    "set_doc_options": "Updating document options",
    "add_block": "Adding section",
    "remove_block": "Removing section",
    "move_block": "Reordering sections",
    "update_block_props": "Configuring section",
    "set_override": "Rewriting text",
    "visual_review": "Reviewing the rendered preview",
}


def _cap(value, limit: int = _PROP_CAP):
    """Recursively cap strings so the digest stays token-lean."""
    if isinstance(value, str):
        return value[:limit]
    if isinstance(value, list):
        return [_cap(item, limit) for item in value[:12]]
    if isinstance(value, dict):
        return {key: _cap(item, limit) for key, item in list(value.items())[:20]}
    return value


def _validated_pairs(blocks: list[dict]):
    """(kind, props) pairs via the block registry, pass-through."""
    from app.services.cv_blocks import validate_blocks

    try:
        return validate_blocks(blocks or [])
    except Exception:  # noqa: BLE001 — a broken draft must still digest
        return [
            (block.get("kind", "unknown"), block.get("props") or {})
            for block in blocks or []
        ]


async def build_builder_context(db: AsyncSession, cv) -> dict:
    """The full builder state digest grounding the copilot."""
    from app.services.cv_builder_service import CvBuilderService
    from app.services.cv_export_service import CvExportService
    from app.services.cv_template_service import CvTemplateService

    builder = CvBuilderService(db)
    template = await builder.template_row(cv)
    template_content, template_id = await builder.template_content(cv)
    resolution = await builder.resolution(cv)
    html, _payload, _res, metrics = await builder.render_state(cv)
    working = cv.working_content or {}
    blocks = working.get("blocks") or template_content.blocks

    resolved = await resolve_sources(db, cv.user_id)
    sources = {
        key: {
            "label": CV_CONTEXT_SOURCES[key].label,
            "items": [
                {"item_id": item.item_id, "label": item.label, "detail": item.detail}
                for item in items[:25]
            ],
        }
        for key, items in resolved.items()
    }

    templates = await CvTemplateService(db).list_templates(cv.user_id)
    lint = await CvExportService(db).lint_report(cv)

    return {
        "document": {
            "title": cv.title,
            "kind": cv.kind,
            "language": cv.language,
            "page_size": cv.page_size,
            "max_pages": cv.max_pages,
            "status": cv.status,
        },
        "template": {
            "id": template_id,
            "title": template.title if template else "built-in fallback",
            "source": template.source if template else "bank",
            "owned": bool(template and template.author_user_id == cv.user_id),
        },
        "templates": [
            {"id": str(row.id), "title": row.title, "source": row.source}
            for row in templates[:20]
            if template_id is None or str(row.id) != template_id
        ],
        "themes": [
            {"key": theme.key, "label": theme.label, "description": theme.description}
            for theme in CV_THEMES
        ],
        "design": template_content.design.model_dump(mode="json"),
        "blocks": [
            {"index": index, "kind": kind, "props": _cap(props or {})}
            for index, (kind, props) in enumerate(_validated_pairs(blocks))
        ],
        "overrides": _cap(working.get("overrides") or {}),
        "selection": {
            "mode": (cv.context or {}).get("mode", "all"),
            "selected_items": {
                key: ids for key, ids in (resolution.snapshot_index or {}).items()
            },
        },
        "sources": sources,
        "override_fields": OVERRIDE_FIELD_HINTS,
        "metrics": {
            "estimated_pages": metrics.estimated_pages,
            "lines_per_page": metrics.lines_per_page,
            "overflow": metrics.overflow,
            "truncated": metrics.truncated,
            "empty_blocks": metrics.empty_blocks,
        },
        "lint": {
            "score": lint.get("score"),
            "issues": [
                {"level": check.get("level"), "message": check.get("message")}
                for check in lint.get("checks") or []
                if check.get("level") in ("warn", "fail")
            ][:10],
        },
    }


# ------------------------------------------------------------- operations


def _design_candidate(current: dict, patch: dict) -> dict:
    unknown = set(patch) - set(DesignTokens.model_fields)
    if unknown:
        raise ValidationError(
            "Unknown design token(s): " + ", ".join(sorted(str(key) for key in unknown))
        )
    return {**current, **patch}


async def _styled_template(
    db: AsyncSession, cv, mutate_design
) -> tuple["CvTemplate", str]:
    """Resolve the CV's template to an owned row with `mutate_design`
    applied — bank/read-only templates are customized on a private copy
    (the same rule the template editor enforces)."""
    from app.services.cv_builder_service import CvBuilderService
    from app.services.cv_template_service import CvTemplateService

    template = await CvBuilderService(db).template_row(cv)
    if template is None:
        raise ValidationError("No template to restyle")
    content = TemplateContent.model_validate(template.content)
    content = content.model_copy(update={"design": mutate_design(content.design)})
    templates = CvTemplateService(db)
    if template.author_user_id == cv.user_id and template.author_key != "bank":
        row = await templates.new_version(template.id, cv.user_id, content)
        note = f"published v{row.version} of “{row.title}”"
    else:
        copy_row = await templates.duplicate(
            template.id, cv.user_id, f"{template.title} (customized)"
        )
        row = await templates.new_version(copy_row.id, cv.user_id, content)
        note = f"customized a private copy of “{template.title}”"
    return row, note


def _save_working(cv, blocks: list[dict], overrides: dict) -> None:
    cv.working_content = {"blocks": blocks, "overrides": overrides}


def _op_args(op) -> dict:
    return {
        key: value for key, value in op.model_dump(mode="json").items() if key != "op"
    }


async def apply_operation(db: AsyncSession, cv, op) -> OpResult:
    """Validate + apply one operation through the owning services."""
    kind = op.op
    try:
        if kind == "set_template":
            from app.services.cv_template_service import CvTemplateService

            template = await CvTemplateService(db).get_readable(
                UUID(op.template_id), cv.user_id
            )
            cv.template_id = template.id
            await db.commit()
            return OpResult(op=kind, ok=True, detail=f"template “{template.title}”")

        if kind == "apply_theme":
            theme = THEMES_BY_KEY.get(op.theme_key)
            if theme is None:
                raise ValidationError(f"Unknown theme: {op.theme_key}")

            def _apply_theme(current: DesignTokens) -> DesignTokens:
                return current.model_copy(
                    update=theme.design.model_dump(exclude_unset=True)
                )

            row, note = await _styled_template(db, cv, _apply_theme)
            cv.template_id = row.id
            await db.commit()
            return OpResult(op=kind, ok=True, detail=f"theme “{theme.label}” — {note}")

        if kind == "update_design":
            from app.services.cv_builder_service import CvBuilderService

            template_row = await CvBuilderService(db).template_row(cv)
            if template_row is None:
                raise ValidationError("No template to restyle")
            current = TemplateContent.model_validate(template_row.content).design
            candidate = _design_candidate(
                current.model_dump(mode="json"), dict(op.design)
            )
            patched = DesignTokens.model_validate(candidate)

            def _apply_patch(_current: DesignTokens) -> DesignTokens:
                return patched

            row, note = await _styled_template(db, cv, _apply_patch)
            cv.template_id = row.id
            await db.commit()
            return OpResult(op=kind, ok=True, detail=f"design updated ({note})")

        if kind == "set_context":
            resolved = await resolve_sources(db, cv.user_id)
            known = {
                (source_key, item.item_id)
                for source_key, items in resolved.items()
                for item in items
            }
            for ref in list(op.include) + list(op.exclude):
                if (ref.source_key, ref.item_id) not in known:
                    raise ValidationError(
                        f"Unknown context item {ref.source_key}:{ref.item_id}"
                    )
            selection = CvContextSelection(
                mode=op.mode,
                include=[ref.model_dump(mode="json") for ref in op.include],
                exclude=[ref.model_dump(mode="json") for ref in op.exclude],
            )
            cv.context = selection.model_dump(mode="json")
            await db.commit()
            return OpResult(
                op=kind,
                ok=True,
                detail=(
                    f"context mode {op.mode}"
                    f" (+{len(op.include)}/-{len(op.exclude)} items)"
                ),
            )

        if kind == "set_doc_options":
            if op.title is not None:
                cv.title = op.title.strip()[:200]
            if op.page_size is not None:
                cv.page_size = op.page_size
            if op.max_pages is not None:
                cv.max_pages = op.max_pages
            if op.language is not None:
                cv.language = op.language
            await db.commit()
            return OpResult(op=kind, ok=True, detail="document options updated")

        working = cv.working_content or {}
        overrides = copy.deepcopy(working.get("overrides") or {})
        blocks = copy.deepcopy(working.get("blocks") or [])
        if not blocks:
            from app.services.cv_builder_service import (
                CvBuilderService,
                FALLBACK_CONTENT,
            )

            _content, _tid = await CvBuilderService(db).template_content(cv)
            blocks = copy.deepcopy(_content.blocks or FALLBACK_CONTENT["blocks"])

        if kind == "add_block":
            from app.services.cv_blocks import validate_blocks

            validate_blocks([{"kind": op.kind, "props": op.props}])
            position = op.position if op.position is not None else len(blocks)
            blocks.insert(
                min(position, len(blocks)), {"kind": op.kind, "props": op.props}
            )
            _save_working(cv, blocks, overrides)
            await db.commit()
            return OpResult(op=kind, ok=True, detail=f"{op.kind} section added")

        if kind == "remove_block":
            if op.block_index >= len(blocks):
                raise ValidationError(f"block_index {op.block_index} out of range")
            removed = blocks.pop(op.block_index)
            _save_working(cv, blocks, overrides)
            await db.commit()
            return OpResult(
                op=kind, ok=True, detail=f"{removed.get('kind')} section removed"
            )

        if kind == "move_block":
            if op.block_index >= len(blocks):
                raise ValidationError(f"block_index {op.block_index} out of range")
            target = min(max(op.to_index, 0), len(blocks) - 1)
            blocks.insert(target, blocks.pop(op.block_index))
            _save_working(cv, blocks, overrides)
            await db.commit()
            return OpResult(op=kind, ok=True, detail=f"moved to position {target}")

        if kind == "update_block_props":
            from app.services.cv_blocks import validate_blocks

            if op.block_index >= len(blocks):
                raise ValidationError(f"block_index {op.block_index} out of range")
            blocks[op.block_index] = {
                **blocks[op.block_index],
                "props": {
                    **(blocks[op.block_index].get("props") or {}),
                    **op.props,
                },
            }
            validate_blocks(blocks)
            _save_working(cv, blocks, overrides)
            await db.commit()
            return OpResult(
                op=kind,
                ok=True,
                detail=f"{blocks[op.block_index]['kind']} props updated",
            )

        if kind == "set_override":
            from app.services.cv_builder_service import CvBuilderService

            resolution = await CvBuilderService(db).resolution(cv)
            ids = (resolution.snapshot_index or {}).get(
                "summary" if op.source_key == "summary" else op.source_key
            ) or []
            if op.item_id not in ids:
                raise ValidationError(
                    f"{op.source_key}:{op.item_id} is not in this CV's context"
                )
            ref = f"{op.source_key}:{op.item_id}"
            overrides[ref] = {**(overrides.get(ref) or {}), op.field: op.value}
            _save_working(cv, blocks, overrides)
            await db.commit()
            return OpResult(
                op=kind, ok=True, detail=f"{op.source_key}.{op.field} rewritten"
            )

        raise ValidationError(f"Unsupported operation: {kind}")
    except ValidationError as exc:
        await db.rollback()
        return OpResult(op=kind, ok=False, detail=str(exc)[:300])
    except Exception as exc:  # noqa: BLE001 — one op never aborts the turn
        await db.rollback()
        return OpResult(op=kind, ok=False, detail=f"{type(exc).__name__}: {exc}"[:300])


# --------------------------------------------------------- visual review


async def _critique_preview(
    db: AsyncSession, cv, *, user_id, lint: dict
) -> tuple[Optional["CvVisualCritique"], str]:
    """Screenshot the rendered preview and critique it; capability-
    detected on both the Chromium engine and a configured vision task."""
    from app.ai.agents.cv_template_designer import critique_pages
    from app.ai.providers.resolution import resolve_task_model
    from app.services.cv_builder_service import CvBuilderService

    try:
        resolved = await resolve_task_model(
            db, AITaskType.CV_TEMPLATE_REVIEW.value, user_id
        )
    except Exception:  # noqa: BLE001 — degrade below
        resolved = None
    if resolved is None:
        return None, "no vision model configured for visual review"
    if not pdf_engine_available():
        return None, "no headless Chromium on this host for screenshots"
    builder = CvBuilderService(db)
    html, _payload, _res, metrics = await builder.render_state(cv)
    template = await builder.template_row(cv)
    try:
        images = await asyncio.wait_for(
            html_to_pngs(html, page_size=cv.page_size), timeout=60
        )
    except Exception as exc:  # noqa: BLE001 — degrade to lint-only
        return None, f"screenshot failed: {exc}"
    critique = await critique_pages(
        db,
        user_id,
        template_summary=template.title if template else "",
        lint=lint,
        max_pages=cv.max_pages,
        page_count=max(1, metrics.estimated_pages),
        images=images,
    )
    return critique, ""


def _critique_digest(critique) -> dict:
    return {
        "summary": critique.summary,
        "issues": [issue.model_dump() for issue in critique.issues],
        "safe_token_fixes": critique.safe_token_fixes,
    }


# --------------------------------------------------------------- turn


async def builder_turn_events(
    db: AsyncSession,
    cv,
    *,
    session,
    user_id,
    message: str,
    history: list[dict],
    user_message_id,
) -> AsyncIterator[tuple[str, dict]]:
    """Run one copilot turn, yielding (event, payload) pairs.

    Event vocabulary matches the chat SSE contract plus `builder_state`
    (the full post-turn builder state the page re-syncs from).
    """
    from app.services.chat_service import ChatService

    turn_started = time.monotonic()
    steps = [
        {"id": "ground", "label": "reading the builder state"},
        {"id": "plan", "label": "planning changes"},
        {"id": "apply", "label": "applying changes"},
        {"id": "review", "label": "reviewing the preview"},
    ]
    yield "flow_started", {"flow": "cv_builder", "steps": steps}

    yield "node_started", {"id": "ground", "label": steps[0]["label"]}
    digest = await build_builder_context(db, cv)
    yield (
        "node_finished",
        {
            "id": "ground",
            "duration_ms": int((time.monotonic() - turn_started) * 1000),
        },
    )

    all_results: list[dict] = []
    critique: Optional[object] = None
    critique_note = ""
    answers: list[str] = []
    try:
        for round_index in range(MAX_REFINE_ROUNDS):
            label = steps[1]["label"] if round_index == 0 else "refining changes"
            yield "node_started", {"id": "plan", "label": label}
            stream = StructuredStream()
            sent = 0
            prompt = context_json(
                {
                    "message": message,
                    "history": history[-6:],
                    "builder_state": digest,
                    "applied_operations": all_results,
                    "visual_critique": _critique_digest(critique)
                    if critique is not None
                    else critique_note,
                    "round": round_index + 1,
                    "instruction": (
                        "Propose the next operations. Round 1 plans from the "
                        "user's message; a later round fixes the issues the "
                        "visual critique found (prefer its safe_token_fixes "
                        "via update_design). Return an empty operation list "
                        "when nothing is left to change."
                    ),
                }
            )
            async for _chunk in stream.chunks(
                db, AITaskType.CV_BUILDER_CHAT, CvBuilderTurn, SYSTEM, prompt, user_id
            ):
                partial = partial_answer_text("".join(stream._raw))
                if len(partial) > sent:
                    yield "delta", {"text": partial[sent:]}
                    sent = len(partial)
            if stream.reply is None:
                raise DomainError(stream.error or "AI produced no valid plan")
            turn = cast(CvBuilderTurn, stream.reply)
            answers.append(turn.answer)
            yield (
                "node_finished",
                {
                    "id": "plan",
                    "duration_ms": int((time.monotonic() - turn_started) * 1000),
                },
            )

            if not turn.operations:
                break
            yield "node_started", {"id": "apply", "label": steps[2]["label"]}
            for op_index, op in enumerate(turn.operations):
                started = time.monotonic()
                result = await apply_operation(db, cv, op)
                all_results.append(result.model_dump(mode="json"))
                yield (
                    "tool_call",
                    {
                        "id": f"cv-{op.op}-{round_index}-{op_index}",
                        "name": f"cv_{op.op}",
                        "title": OP_TITLES.get(op.op, op.op),
                        "status": "done" if result.ok else "failed",
                        "args": json.dumps(_op_args(op))[:160],
                        "result": result.detail,
                        "durationMs": int((time.monotonic() - started) * 1000),
                    },
                )
            yield "node_finished", {"id": "apply"}

            digest = await build_builder_context(db, cv)

            if round_index + 1 >= MAX_REFINE_ROUNDS or not turn.need_visual_review:
                break
            yield "node_started", {"id": "review", "label": steps[3]["label"]}
            critique, critique_note = await _critique_preview(
                db, cv, user_id=user_id, lint=digest.get("lint") or {}
            )
            yield (
                "tool_call",
                {
                    "id": f"cv-visual_review-{round_index}",
                    "name": "cv_review_visual",
                    "title": OP_TITLES["visual_review"],
                    "status": "done",
                    "args": "rendered page screenshots",
                    "result": critique.summary
                    if critique is not None
                    else critique_note,
                },
            )
            yield "node_finished", {"id": "review"}
            if critique is None or not critique.issues:
                break

        from app.services.cv_builder_service import CvBuilderService

        version_number: Optional[int] = None
        if any(result["ok"] for result in all_results):
            try:
                version, _html, _metrics = await CvBuilderService(db).compile(
                    cv, created_by=CvVersionCreator.AI_APPLY
                )
                version_number = version.version
            except Exception:  # noqa: BLE001 — empty context may block compile
                pass

        html, metrics, resolution, blocks = await CvBuilderService(db).preview(cv)
        state = {
            "document": {
                "id": str(cv.id),
                "title": cv.title,
                "kind": cv.kind,
                "language": cv.language,
                "page_size": cv.page_size,
                "max_pages": cv.max_pages,
                "status": cv.status,
                "template_id": str(cv.template_id) if cv.template_id else None,
                "photo_document_id": str(cv.photo_document_id)
                if cv.photo_document_id
                else None,
            },
            "blocks": blocks,
            "overrides": (cv.working_content or {}).get("overrides") or {},
            "html": html,
            "metrics": metrics,
            "resolution": {"snapshot_index": resolution.snapshot_index},
            "operations": all_results,
            "critique": _critique_digest(critique) if critique is not None else None,
            "version": version_number,
        }

        total_ms = int((time.monotonic() - turn_started) * 1000)
        message_row = await ChatService(db).complete_builder_turn(
            session,
            user_message_id,
            "\n\n".join(answers) or "Done.",
            {
                "surface": "cv_builder",
                "operations": all_results,
                "critique": state["critique"],
                "version": version_number,
                "elapsed_ms": total_ms,
                "model": stream.model,
            },
        )
        yield "builder_state", state
        yield "meta", {"message_id": str(message_row.id)}
        yield (
            "flow_finished",
            {
                "flow": "cv_builder",
                "total_ms": total_ms,
                "tool_count": len(all_results),
            },
        )
        yield "done", {"ok": True}
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 — stream must end cleanly
        code = "ai_unavailable" if "not configured" in str(exc).lower() else "ai_error"
        yield "flow_failed", {"code": code, "message": str(exc), "retryable": True}
        yield "error", {"detail": str(exc)}


# ---------------------------------------------------------- mock fixture


def _mock_builder_turn(schema: type, user_prompt: str) -> dict:
    """Deterministic copilot: keyword-driven ops over the digest."""
    ctx = parse_context(user_prompt)
    message = str(ctx.get("message", ""))
    state = ctx.get("builder_state") or {}
    round_index = int(ctx.get("round") or 1)
    lowered = message.lower()
    blocks = state.get("blocks") or []
    sources = state.get("sources") or {}
    current_template = (state.get("template") or {}).get("id")
    templates = [
        t for t in state.get("templates") or [] if t.get("id") != current_template
    ]

    if any(
        word in lowered for word in ("review", "layout", "overflow", "looks", "spacing")
    ):
        return {
            "answer": (
                "I reviewed the rendered preview and tightened the spacing."
                if round_index > 1
                else "Let me render the preview and review the layout."
            ),
            "operations": [{"op": "update_design", "design": {"spacing_scale": 1.05}}],
            "need_visual_review": True,
        }

    ops: list[dict] = []

    def _first_item(source_key: str) -> Optional[dict]:
        items = (sources.get(source_key) or {}).get("items") or []
        return items[0] if items else None

    if "template" in lowered and templates:
        ops.append({"op": "set_template", "template_id": templates[0]["id"]})
    elif any(word in lowered for word in ("theme", "color", "accent")):
        ops.append({"op": "apply_theme", "theme_key": "teal_modern"})
    elif "two" in lowered and "page" in lowered:
        ops.append({"op": "set_doc_options", "max_pages": 2})
    elif any(word in lowered for word in ("hide", "exclude", "drop")):
        for source_key in ("interests", "achievements", "languages"):
            item = _first_item(source_key)
            if item is not None:
                ops.append(
                    {
                        "op": "set_context",
                        "mode": "all",
                        "include": [],
                        "exclude": [
                            {"source_key": source_key, "item_id": item["item_id"]}
                        ],
                    }
                )
                break
    elif "add" in lowered and "section" in lowered:
        ops.append(
            {
                "op": "add_block",
                "kind": "custom_text",
                "props": {"title": "Highlights", "text": "Added by the assistant."},
            }
        )
    elif "rewrite" in lowered or "shorten" in lowered:
        summary_item = _first_item("summary")
        if summary_item is not None:
            ops.append(
                {
                    "op": "set_override",
                    "source_key": "summary",
                    "item_id": summary_item["item_id"],
                    "field": "summary",
                    "value": "Rewritten by the assistant from the profile summary.",
                }
            )
    elif any(word in lowered for word in ("levels", "skills")):
        skills = next((b for b in blocks if b.get("kind") == "skills"), None)
        if skills is not None:
            ops.append(
                {
                    "op": "update_block_props",
                    "block_index": skills["index"],
                    "props": {"show_levels": True},
                }
            )
    if not ops:
        ops.append({"op": "update_design", "design": {"accent_color": "#0f766e"}})
    listed = ", ".join(op["op"] for op in ops)
    return {
        "answer": f"I would apply: {listed}.",
        "operations": ops[:12],
        "need_visual_review": False,
    }


register_mock_fixture(AITaskType.CV_BUILDER_CHAT, _mock_builder_turn)
