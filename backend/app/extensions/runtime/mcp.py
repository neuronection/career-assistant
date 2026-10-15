"""The T3 script tier's host-side support (plan 32 Phase 2 / ADR-0040
D9): the audit adapter mapping every MCP tool call onto the existing
audit funnel (``ai_generations`` rows via the gateway, exactly like the
MCP bridge). The connector itself stays a pure normalizer over an
injected call — this module owns the host-side obligations.

fastmcp/mcp imports stay in ``app/ai`` (ADR-0012; the structure probe
pins it): client construction and error classification are delegated
through :mod:`app.ai.mcp_client`, which returns plain charter data.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.extensions.sdk import AuditFn, ExternalEffect


def mcp_effect_auditor(db: AsyncSession, source_key: str) -> AuditFn:
    """One audit row per MCP tool call, through the same funnel the MCP
    bridge uses (``AITaskType.MCP_TOOL_CALL``, provider ``mcp``). Rows
    ride the caller's transaction — sync commits them with the source
    run, atomically."""

    async def audit(effect: ExternalEffect) -> None:
        if effect.kind != "mcp_tool_call":
            return
        from app.ai.gateway import _record
        from app.models.enums import AITaskType

        transport = str(effect.meta.get("transport") or "stdio")
        await _record(
            db,
            None,
            AITaskType.MCP_TOOL_CALL,
            transport,
            f"mcp:{source_key}:{effect.ref}",
            {
                "arguments": effect.arguments,
                "meta": effect.meta,
                "ok": effect.ok,
                "error": effect.error,
            },
            None,
            None,
            effect.latency_ms,
            "ok" if effect.ok else "error",
            effect.error[:1000],
            model_name=source_key,
            provider_type="mcp",
        )

    return audit
