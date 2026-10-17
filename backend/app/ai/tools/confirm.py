"""The D20 destructive-confirm runtime funnel (plan 32 follow-up /
ADR-0015 Class-B / ADR-0011 trust boundary).

A ``destructive`` registry tool can never execute through
:func:`app.ai.tools.registry.run_tool`: the call becomes a detached
Class-B card (kind ``tool_execution`` on the existing proposal
machinery — idempotent resolve, notification fanout, cross-session
inbox) and the tool's handler runs exactly once through THAT card's
approve path (:func:`apply_tool_execution`). The law this module
enforces:

* confirmed every call — no grant, setting or repeated call bypasses
  the card; a second destructive call emits a second card;
* the model can never arm execution — the tool result the model sees
  carries only the card reference (``awaiting_approval``), and
  execution happens exclusively server-side on the authenticated
  resolve endpoint; nothing in the result, the args or any model output
  flips state toward the handler;
* the approve path re-validates everything (tool still registered,
  still destructive, args still parse) and executes the STORED args —
  the card approves THIS call, never the tool in general;
* audit rows for both halves: the card row itself (with chat lineage +
  notification) is the proposal audit; each execution lands on the
  ``ai_generations`` funnel (``tool_run`` task) like every tool-class
  effect.
"""

import logging
import time
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.tools.base import AITool, ToolContext, ToolRiskClass
from app.core.errors import DomainError
from app.models.enums import AITaskType, ProposalAction, ProposalKind
from app.models.profile_proposal_model import ProfileProposal

logger = logging.getLogger(__name__)

#: The model-facing result of a confirmed (not executed) call — the only
#: shape that may cross back into model context. Deliberately free of
#: anything executable: no handler output, no "ok" marker, no token.
AWAITING_APPROVAL = "awaiting_approval"


def _args_diff(tool: AITool, args: dict[str, Any]) -> list[dict]:
    """Card diff rows: what will run, in user language."""
    rows = [{"field": "tool", "label": "Tool", "after": tool.key}]
    for name, value in args.items():
        rows.append({"field": name, "label": name.replace("_", " ").title(), "after": value})
    return rows


def _summary(tool: AITool, args: dict[str, Any]) -> str:
    joined = ", ".join(f"{k}={str(v)[:60]}" for k, v in list(args.items())[:4])
    detail = f"({joined})" if joined else ""
    return f"{tool.title} {detail}".strip()[:300]


async def emit_tool_confirmation(
    db: AsyncSession,
    *,
    tool: AITool,
    user_id: uuid.UUID,
    args: Any,
    chat_session_id: uuid.UUID | None = None,
) -> dict:
    """Turn one destructive call into its confirmation card. NOTHING
    executes here — the return value is the model-facing reference."""
    from app.services.profile_proposal_service import ProfileProposalService

    args_dict = args if isinstance(args, dict) else args.model_dump(mode="json")
    proposal = await ProfileProposalService(db).create(
        user_id,
        kind=ProposalKind.TOOL_EXECUTION.value,
        action=ProposalAction.CREATE.value,
        payload={
            "tool": tool.key,
            "args": _jsonable(args_dict),
            "summary": _summary(tool, args_dict),
        },
        chat_session_id=chat_session_id,
    )
    from app.services.profile_proposal_service import notify_proposals

    await notify_proposals(db, user_id, [proposal], chat_session_id)
    return {
        "status": AWAITING_APPROVAL,
        "proposal_id": str(proposal.id),
        "tool": tool.key,
        "detail": (
            "This tool is destructive: nothing ran. A confirmation card was "
            "sent to the user — execution happens only if they approve that "
            "exact call."
        ),
    }


def _jsonable(args: dict[str, Any]) -> dict[str, Any]:
    """Model args are JSON-shaped already; coerce defensively so a stray
    non-JSON value can never break card persistence."""
    import json

    try:
        return json.loads(json.dumps(args, default=str))
    except (TypeError, ValueError):
        return {k: str(v)[:300] for k, v in args.items()}


async def apply_tool_execution(db: AsyncSession, proposal: ProfileProposal) -> dict:
    """The card's apply: re-validate, execute the STORED args exactly
    once, audit the run. Called only from the proposal service's approve
    path (status already terminal — a crash mid-apply leaves an approved
    card with a resolve_error, never a retryable pending one)."""
    from app.ai.tools.base import ToolScope
    from app.ai.tools.registry import _coerce_tool_args, get_tool

    payload = dict(proposal.payload_json or {})
    tool = get_tool(str(payload.get("tool") or ""))
    if tool.kind != "tool":
        raise DomainError(f"Tool {tool.key} is no longer a callable tool")
    if tool.effective_risk_class is not ToolRiskClass.DESTRUCTIVE:
        raise DomainError(f"Tool {tool.key} is no longer destructive — this card is void")
    if tool.scope is not ToolScope.WRITE:  # pragma: no cover — implied by the class gate
        raise DomainError(f"Tool {tool.key} lost its write scope — this card is void")
    parsed = _coerce_tool_args(tool.input_model, dict(payload.get("args") or {}), tool.key)

    started = time.monotonic()
    handler = tool.handler
    assert handler is not None, "callable tools always carry a handler"
    try:
        result = await handler(db, ToolContext(user_id=proposal.user_id), parsed)
    except DomainError as exc:
        await _audit(
            db,
            proposal,
            tool.key,
            payload.get("args") or {},
            False,
            str(exc)[:1000],
            (time.monotonic() - started) * 1000,
        )
        raise
    except Exception as exc:
        duration_ms = (time.monotonic() - started) * 1000
        await _audit(
            db,
            proposal,
            tool.key,
            payload.get("args") or {},
            False,
            f"{type(exc).__name__}: {exc}"[:1000],
            duration_ms,
        )
        raise DomainError(f"tool execution failed: {exc}") from exc
    duration_ms = (time.monotonic() - started) * 1000
    await _audit(db, proposal, tool.key, payload.get("args") or {}, True, None, duration_ms)
    return {"kind": "tool_execution", "tool": tool.key, "result": result}


async def _audit(
    db: AsyncSession,
    proposal: ProfileProposal,
    tool_key: str,
    args: dict,
    ok: bool,
    error: str | None,
    duration_ms: float,
) -> None:
    """The execution audit row (the proposal row itself is the
    proposal-side audit) — same funnel as every tool-class effect."""
    from app.ai.gateway import _record

    try:
        await _record(
            db,
            proposal.user_id,
            AITaskType.TOOL_RUN,
            "tool",
            f"tool:{tool_key}",
            {"args": _jsonable(args), "ok": ok, "error": error},
            None,
            None,
            duration_ms,
            "ok" if ok else "error",
            error or "",
            model_name="tool",
            provider_type="tool",
        )
        await db.commit()
    except Exception:
        logger.exception("tool_run audit row failed (tool %s)", tool_key)
        await db.rollback()
