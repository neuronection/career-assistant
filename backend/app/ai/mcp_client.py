"""MCP client transport plumbing — the AI-layer module
that builds fastmcp clients from bridge server rows.

Protocol imports (fastmcp/mcp) stay inside the AI layer (alignment
rule R2); the bridge service keeps registration, allowlist and audit
orchestration and delegates here.
"""

from shlex import split as shlex_split
from typing import Any

from fastmcp import Client

from app.core.errors import DomainError
from app.models.mcp_bridge_model import AIMCPServer


def client_for(row: AIMCPServer):
    """The fastmcp client for a server row (factored for test injection)."""
    if row.transport == "http":
        from fastmcp.client.transports import StreamableHttpTransport

        headers = {"Authorization": f"Bearer {row.token}"} if row.token else {}
        transport: Any = StreamableHttpTransport(row.url, headers=headers)
    elif row.transport == "stdio":
        from fastmcp.client.transports import StdioTransport

        parts = shlex_split(row.command)
        if not parts:
            raise DomainError("stdio command is empty")
        transport = StdioTransport(parts[0], parts[1:])
    else:
        raise DomainError(f"Unknown MCP transport: {row.transport}")
    return Client(transport), transport
