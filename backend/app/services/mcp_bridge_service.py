"""MCP client bridge service: registration, discovery,
namespaced invocation — audited and budgeted through the gateway funnel.

Server/stdio endpoints are trusted admin input; the fastmcp client owns
the protocol. Tool enablement is an explicit allowlist per server: a
refresh may discover NEW tools but never widens access on its own.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import DomainError, NotFoundError
from app.models.enums import AITaskType
from app.models.mcp_bridge_model import AIMCPServer


def namespaced_key(server_name: str, tool_name: str) -> str:
    return f"mcp.{server_name}.{tool_name}"


class MCPBridgeService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ------------------------------------------------------------ registry

    async def list_servers(self) -> list[AIMCPServer]:
        rows = await self.db.execute(select(AIMCPServer).order_by(AIMCPServer.name))
        return list(rows.scalars().all())

    async def get_server(self, server_id: uuid.UUID) -> AIMCPServer:
        row = await self.db.get(AIMCPServer, server_id)
        if row is None:
            raise NotFoundError("MCP server not found")
        return row

    async def register(
        self,
        *,
        name: str,
        transport: str,
        url: str = "",
        command: str = "",
        token: str = "",
        created_by: Optional[uuid.UUID] = None,
    ) -> AIMCPServer:
        if transport not in ("http", "stdio"):
            raise DomainError("transport must be http or stdio")
        if transport == "http" and not url:
            raise DomainError("http servers need a url")
        if transport == "stdio" and not command:
            raise DomainError("stdio servers need a command")
        existing = await self.db.execute(
            select(AIMCPServer).where(AIMCPServer.name == name)
        )
        if existing.scalars().first() is not None:
            raise DomainError(f"MCP server '{name}' already registered")
        row = AIMCPServer(
            name=name,
            transport=transport,
            url=url,
            command=command,
            created_by=created_by,
        )
        row.token = token
        self.db.add(row)
        await self.db.commit()
        await self.db.refresh(row)
        return row

    async def remove(self, server_id: uuid.UUID) -> None:
        row = await self.get_server(server_id)
        await self.db.delete(row)
        await self.db.commit()

    async def set_enabled(self, server_id: uuid.UUID, enabled: bool) -> AIMCPServer:
        row = await self.get_server(server_id)
        row.enabled = enabled
        await self.db.commit()
        await self.db.refresh(row)
        return row

    async def set_tool_enabled(
        self, server_id: uuid.UUID, tool_name: str, enabled: bool
    ) -> AIMCPServer:
        row = await self.get_server(server_id)
        discovered = {t.get("name") for t in row.discovered_tools or []}
        if tool_name not in discovered:
            raise DomainError(f"Unknown tool for this server: {tool_name}")
        allow = set(row.enabled_tools or [])
        if enabled:
            allow.add(tool_name)
        else:
            allow.discard(tool_name)
        row.enabled_tools = sorted(allow)
        await self.db.commit()
        await self.db.refresh(row)
        return row

    # ------------------------------------------------------------ discovery

    async def refresh(self, server_id: uuid.UUID) -> AIMCPServer:
        """Re-discover the server's tools (explicit; never auto-widens)."""
        row = await self.get_server(server_id)
        client, _ = self._client_for(row)
        tools = []
        try:
            async with client as session:
                listed = await session.list_tools()
                tools = [
                    {"name": t.name, "description": t.description or ""} for t in listed
                ]
        except Exception as exc:  # noqa: BLE001 — surface as domain error
            raise DomainError(f"MCP refresh failed: {exc}") from exc
        # Keep allowlist entries that still exist; new tools start disabled.
        discovered_names = {t["name"] for t in tools}
        row.discovered_tools = tools
        row.enabled_tools = [
            name for name in (row.enabled_tools or []) if name in discovered_names
        ]
        row.last_synced_at = datetime.now(timezone.utc)
        await self.db.commit()
        await self.db.refresh(row)
        return row

    def _client_for(self, row: AIMCPServer):
        """The fastmcp client (built by the AI-layer module; factored
        for test injection)."""
        from app.ai.mcp_client import client_for

        return client_for(row)

    async def invoke(
        self,
        server_id: uuid.UUID,
        tool_name: str,
        arguments: dict,
        *,
        user_id: Optional[uuid.UUID] = None,
    ) -> dict:
        """Execute one enabled, namespaced tool — audited + budgeted."""
        from app.ai.gateway import _record

        row = await self.get_server(server_id)
        if not row.enabled:
            raise DomainError("This MCP server is disabled")
        if tool_name not in (row.enabled_tools or []):
            raise DomainError(f"Tool '{tool_name}' is not enabled on this server")
        client, _ = self._client_for(row)
        started = datetime.now(timezone.utc)
        try:
            async with client as session:
                result = await session.call_tool(tool_name, arguments or {})
            payload = {
                "content": [
                    getattr(block, "text", None)
                    for block in (result.content or [])
                    if getattr(block, "text", None) is not None
                ],
                "is_error": bool(getattr(result, "is_error", False)),
            }
            status = "error" if getattr(result, "is_error", False) else "ok"
        except Exception as exc:  # noqa: BLE001 — audited, then raised
            await _record(
                self.db,
                user_id,
                AITaskType.MCP_TOOL_CALL,
                row.transport,
                f"mcp:{row.name}:{tool_name}",
                None,
                None,
                None,
                (datetime.now(timezone.utc) - started).total_seconds() * 1000,
                "error",
                f"{type(exc).__name__}: {exc}",
            )
            await self.db.commit()
            raise DomainError(f"MCP call failed: {exc}") from exc

        await _record(
            self.db,
            user_id,
            AITaskType.MCP_TOOL_CALL,
            row.transport,
            f"mcp:{row.name}:{tool_name}",
            payload,
            None,
            None,
            (datetime.now(timezone.utc) - started).total_seconds() * 1000,
            status,
            model_name=row.name,
            provider_type="mcp",
        )
        await self.db.commit()
        return payload
