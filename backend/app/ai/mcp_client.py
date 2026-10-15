"""MCP client transport plumbing — the AI-layer module that builds
fastmcp clients, both for bridge server rows and for connector transport
specs (the T3 script tier, plan 32 Phase 2).

Protocol imports (fastmcp/mcp) stay inside the AI layer (alignment
rule R2); the bridge service and the mcp connector keep registration,
allowlist and audit orchestration and delegate here. Exceptions leave
this module classified as plain charter triples — SDK types never
cross into app/extensions/.
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


def client_for_spec(
    *,
    transport: str,
    url: str = "",
    command: str = "",
    token: str = "",
    timeout_seconds: int = 30,
) -> Client:
    """The fastmcp client for a connector transport spec (T3 script tier).

    ``stdio`` spawns ride the mcp SDK's sanitized environment
    (``get_default_environment`` — PATH preserved, everything else
    dropped), which keeps spawned scripts resolvable in frozen builds
    (the study packaging lesson). ``timeout_seconds`` bounds the whole
    session; per-tool calls pass their own timeout on top.
    """
    if transport == "http":
        from fastmcp.client.transports import StreamableHttpTransport

        if not url:
            raise DomainError("http MCP servers need a url")
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        spec: Any = StreamableHttpTransport(url, headers=headers)
    elif transport == "stdio":
        from fastmcp.client.transports import StdioTransport

        parts = shlex_split(command)
        if not parts:
            raise DomainError("stdio command is empty")
        spec = StdioTransport(parts[0], parts[1:])
    else:
        raise DomainError(f"Unknown MCP transport: {transport}")
    return Client(spec, timeout=timeout_seconds)


def classify_tool_error(exc: Exception, timeout_seconds: int = 30) -> tuple[str, str, str]:
    """Map a fastmcp tool-call failure to a charter ``(code, detail,
    retryable)`` triple — the only error shape that crosses back into
    ``app/extensions/`` (SDK exception types stay here).

    Timeout (request deadline or session init) → ``unreachable``
    (charter meaning: transport-level failure, retryable); spawn and
    connection failures likewise; tool-reported errors and everything
    else → ``provider`` (upstream-side, retryable).
    """
    from mcp.shared.exceptions import MCPError
    from mcp.types import REQUEST_TIMEOUT

    if isinstance(exc, MCPError) and exc.code == REQUEST_TIMEOUT:
        return ("unreachable", f"tool call timed out after {timeout_seconds}s", "yes")
    if isinstance(exc, TimeoutError) or (
        isinstance(exc, RuntimeError) and isinstance(exc.__cause__, TimeoutError)
    ):
        return ("unreachable", f"MCP session timed out after {timeout_seconds}s", "yes")
    if isinstance(exc, (ConnectionError, OSError)):
        return ("unreachable", f"{type(exc).__name__}: {exc}"[:500], "yes")
    return ("provider", f"{type(exc).__name__}: {exc}"[:500], "yes")
