"""MCP server: the app's read-scope AI tools exposed over
the Model Context Protocol via FastMCP.

Transport = Streamable HTTP mounted at ``/mcp`` (loopback in desktop /
self-host deployments) so external MCP clients (Claude Desktop, IDE
agents) can drive career data. Governance:

- **Token auth** — a locally generated bearer token persisted in the
  data dir; rotation invalidates the old
  token. Every verification re-reads the file, so rotation is live.
- **Read-only by default** — only read-scope registry tools are
  exposed; write opt-in rides a later admin setting.
- **Same funnel** — handlers execute through the tool registry's
  ``run_tool`` with their own DB session; rate limiting (the shared
  limiter) wraps the ASGI app per client host.
"""

import inspect
import json
import secrets
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from app.core.config import settings
from app.core.ratelimit import limiter


class MCPTokenStore:
    """The instance MCP token, persisted in the data dir."""

    def __init__(self, directory: Optional[Path] = None):
        self._path = Path(directory) if directory else None

    def _file(self) -> Path:
        base = self._path if self._path is not None else settings.data_dir_path
        base.mkdir(parents=True, exist_ok=True)
        return base / "mcp_token.json"

    def read(self) -> Optional[dict]:
        path = self._file()
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return None

    def rotate(self, user_id: Optional[str]) -> dict:
        info = {
            "token": secrets.token_urlsafe(32),
            "user_id": user_id,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        path = self._file()
        path.write_text(json.dumps(info))
        try:
            path.chmod(0o600)
        except OSError:  # noqa: BLE001 — Windows may ignore chmod
            pass
        return info


_TOKEN_STORE: Optional[MCPTokenStore] = None


def token_store() -> MCPTokenStore:
    global _TOKEN_STORE
    if _TOKEN_STORE is None:
        _TOKEN_STORE = MCPTokenStore()
    return _TOKEN_STORE


def _dynamic_handler(tool):
    """An async handler whose signature mirrors the tool's pydantic
    input model, so FastMCP derives a flat JSON Schema for MCP clients."""

    async def handler(**kwargs):
        from app.ai.tools import run_tool
        from app.core.database import AsyncSessionLocal

        token_info = token_store().read() or {}
        bound_user = token_info.get("user_id")
        user_id = uuid.UUID(str(bound_user)) if bound_user else None
        if tool.requires_user and user_id is None:
            raise ValueError(
                "This tool requires a bound user; rotate the MCP token "
                "as a signed-in admin to bind one."
            )
        async with AsyncSessionLocal() as db:
            result = await run_tool(db, tool.key, user_id, args=dict(kwargs))
            return json.loads(json.dumps(result, default=str))

    parameters = []
    annotations: dict[str, Any] = {}
    for name, field_info in tool.input_model.model_fields.items():
        annotations[name] = field_info.annotation
        default = (
            field_info.default
            if field_info.is_required() is False and field_info.default is not None
            else (
                field_info.default_factory()
                if field_info.default_factory is not None
                else ...
            )
        )
        # Keyword-only: pydantic models allow required-after-optional
        # fields, plain signatures don't.
        parameters.append(
            inspect.Parameter(
                name,
                inspect.Parameter.KEYWORD_ONLY,
                annotation=field_info.annotation,
                default=default,
            )
        )
    handler.__signature__ = inspect.Signature(parameters)
    handler.__annotations__ = annotations
    handler.__doc__ = tool.description
    return handler


def build_mcp_server():
    """The FastMCP server exposing the registry's read-scope tools."""
    from fastmcp import FastMCP
    from fastmcp.server.auth.providers.jwt import AccessToken
    from fastmcp.server.auth import TokenVerifier
    from app.ai.tools import list_tools

    class InstanceTokenVerifier(TokenVerifier):
        async def verify_token(self, token: str):
            info = token_store().read()
            if (
                info
                and info.get("token")
                and secrets.compare_digest(token, str(info["token"]))
            ):
                return AccessToken(
                    token=token, client_id="local-mcp", scopes=[], expires_at=None
                )
            return None

    mcp = FastMCP(
        "career-assistant",
        instructions=(
            "Read-scope career tools: postings search/detail, fit, "
            "notifications state. Governed by the tool registry."
        ),
        auth=InstanceTokenVerifier(),
    )

    for tool_data in list_tools():
        if tool_data["scope"] != "read":
            continue
        tool = _registry_tool(tool_data["key"])
        if tool is None:
            continue
        from fastmcp.tools import Tool

        mcp.add_tool(
            Tool.from_function(
                _dynamic_handler(tool),
                name=tool.key,
                description=tool.description,
            )
        )
    return mcp


def _registry_tool(key: str):
    from app.ai.tools import get_tool

    try:
        return get_tool(key)
    except Exception:  # noqa: BLE001 — a vanished registry entry
        return None


def _mcp_rate_limit_middleware(asgi_app):
    """Per-client-host rate limiting around the MCP ASGI app."""

    async def middleware(scope, receive, send):
        if scope.get("type") != "http":
            await asgi_app(scope, receive, send)
            return
        client = scope.get("client") or ("unknown", 0)
        retry_after = limiter.check("mcp", str(client[0]))
        if retry_after is not None:
            body = json.dumps(
                {"detail": f"rate limited; retry in {retry_after}s"}
            ).encode()
            await send(
                {
                    "type": "http.response.start",
                    "status": 429,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"retry-after", str(retry_after).encode()),
                        (b"content-length", str(len(body)).encode()),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return
        await asgi_app(scope, receive, send)

    return middleware


def build_mcp_asgi_app():
    """The rate-limited ASGI app to mount at ``/mcp``."""
    return _mcp_rate_limit_middleware(build_mcp_server().http_app())


def _default_limits() -> tuple[tuple[str, int, int], ...]:
    return (("mcp", 120, 60),)
