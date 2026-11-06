"""MCP server management API (plan 119.2): connection surface, token
lifecycle, live tool list, admin write switch and the call audit view.

All routes are admin-only (the instance MCP server is system-scope). The
plaintext secret appears exactly once, in the mint/rotation response.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.tools import list_tools
from app.core.database import get_db
from app.core.errors import ValidationError
from app.models.ai_model import AIGeneration
from app.models.enums import McpTokenScope
from app.models.user_model import User
from app.services.admin import mcp_tokens
from app.services.deps import require_admin

router = APIRouter(prefix="/ai/mcp", tags=["mcp"])


class McpTokenIn(BaseModel):
    """Mint request: a human label plus the closed scope list."""

    label: str = Field(default="", max_length=120)
    scopes: list[str] = Field(default_factory=lambda: ["read"])


class McpSettingsIn(BaseModel):
    """The admin write-scope switch (default OFF)."""

    write_enabled: bool = False


def _public(row) -> dict:
    data = mcp_tokens.public_token(row)
    data["bound_user_id"] = str(data["bound_user_id"]) if data["bound_user_id"] else None
    return data


def _projected_tools(write_ready: bool) -> list[dict]:
    """The live MCP surface = the registry projection (no second list)."""
    rows = []
    for entry in list_tools():
        if entry.get("kind") != "tool":
            continue
        if entry["scope"] == McpTokenScope.WRITE.value and not write_ready:
            continue
        rows.append(
            {
                "key": entry["key"],
                "title": entry["title"],
                "description": entry["description"],
                "scope": entry["scope"],
                "risk_class": entry["risk_class"],
            }
        )
    return rows


async def _mint_payload(db: AsyncSession, row, plaintext: str) -> dict:
    await db.commit()
    return {**_public(row), "token": plaintext}


@router.get("/status")
async def mcp_status(
    request: Request,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Endpoint URL, write switch and the projected surface counts."""
    write_ready = await mcp_tokens.write_enabled(db)
    tokens = await mcp_tokens.list_tokens(db)
    tools = _projected_tools(write_ready)
    base = str(request.base_url).rstrip("/")
    return {
        "endpoint": f"{base}/mcp",
        "transport": "streamable-http",
        "write_enabled": write_ready,
        "tools": tools,
        "read_tools": [t["key"] for t in tools if t["scope"] == McpTokenScope.READ.value],
        "write_tools": [t["key"] for t in tools if t["scope"] == McpTokenScope.WRITE.value],
        "active_tokens": sum(1 for row in tokens if row.revoked_at is None),
    }


@router.put("/settings")
async def update_mcp_settings(
    data: McpSettingsIn,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Flip the write-scope switch; write tools appear only while it is on."""
    enabled = await mcp_tokens.set_write_enabled(db, data.write_enabled)
    tools = _projected_tools(enabled)
    return {
        "write_enabled": enabled,
        "tools": tools,
        "write_tools": [
            entry["key"] for entry in tools if entry["scope"] == McpTokenScope.WRITE.value
        ],
    }


@router.get("/tokens")
async def list_mcp_tokens(
    user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> list[dict]:
    """Token metadata, newest first — never the hash or plaintext."""
    return [_public(row) for row in await mcp_tokens.list_tokens(db)]


@router.post("/tokens", status_code=201)
async def mint_mcp_token(
    data: McpTokenIn,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Mint a token bound to the calling admin; the plaintext is here once."""
    scopes = mcp_tokens.normalize_scopes(data.scopes)
    if McpTokenScope.WRITE.value in scopes and not await mcp_tokens.write_enabled(db):
        raise ValidationError("Enable MCP write access before minting a write token")
    row, plaintext = await mcp_tokens.mint(db, user.id, label=data.label, scopes=scopes)
    return await _mint_payload(db, row, plaintext)


@router.post("/tokens/{token_id}/rotate")
async def rotate_mcp_token(
    token_id: UUID,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Revoke the token and return its successor's one-time plaintext."""
    row, plaintext = await mcp_tokens.rotate(db, token_id)
    return await _mint_payload(db, row, plaintext)


@router.delete("/tokens/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_mcp_token(
    token_id: UUID,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Revoke a token (its next request answers 401)."""
    await mcp_tokens.revoke(db, token_id)
    await db.commit()


@router.get("/tools")
async def mcp_tools(
    user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> list[dict]:
    """The live tool list with scopes (write tools only while enabled)."""
    return _projected_tools(await mcp_tokens.write_enabled(db))


@router.get("/audit")
async def mcp_audit(
    limit: int = Query(default=25, ge=1, le=200),
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Recent MCP server calls from the audit ledger."""
    rows = (
        (
            await db.execute(
                select(AIGeneration)
                .where(
                    AIGeneration.task_type == "mcp_tool_call",
                    AIGeneration.provider == "mcp",
                    AIGeneration.prompt.like("mcp-server:%"),
                )
                .order_by(AIGeneration.created_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": str(row.id),
            "tool": (row.output or {}).get("tool"),
            "label": row.model,
            "status": row.status,
            "latency_ms": row.latency_ms,
            "request_id": (row.output or {}).get("request_id"),
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]
