"""In-process MCP probe for the plan-119 tests (no real sockets).

The FastMCP Streamable-HTTP app runs over ``httpx.ASGITransport``; the
server's per-request session seam points at the test session so fixture
data is visible across the request boundary. Production opens its own
sessions.
"""

import contextlib
import json
from uuid import UUID

import httpx

from app.services.admin import mcp_tokens
from tests.conftest import _uid

INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 0,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "probe", "version": "0"},
    },
}


class Probe:
    """A minimal JSON-RPC MCP client over the ASGI transport."""

    def __init__(self, http: httpx.AsyncClient, token: str | None):
        self.http = http
        self.token = token
        self.session_id: str | None = None
        self.next_id = 0
        self.initialize: httpx.Response | None = None

    def _headers(self, *, session: bool = True) -> dict:
        headers = {"Accept": "application/json, text/event-stream"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if session and self.session_id:
            headers["mcp-session-id"] = self.session_id
        return headers

    @staticmethod
    def _payload(response: httpx.Response) -> dict:
        for line in response.text.splitlines():
            if line.startswith("data:"):
                return json.loads(line[5:].strip())
        return response.json() if response.text.strip() else {}

    async def start(self) -> None:
        response = await self.http.post(
            "/mcp", json=INITIALIZE, headers=self._headers(session=False)
        )
        self.initialize = response
        if response.status_code != 200:
            return
        self.session_id = response.headers.get("mcp-session-id")
        await self.http.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            headers=self._headers(),
        )

    async def rpc(self, method: str, params: dict | None = None) -> dict:
        self.next_id += 1
        response = await self.http.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": self.next_id,
                "method": method,
                "params": params or {},
            },
            headers=self._headers(),
        )
        return self._payload(response)

    async def tools(self) -> list[str]:
        payload = await self.rpc("tools/list")
        return [entry["name"] for entry in payload.get("result", {}).get("tools", [])]

    async def resources(self) -> list[str]:
        payload = await self.rpc("resources/list")
        return [entry["uri"] for entry in payload.get("result", {}).get("resources", [])]

    async def resource_templates(self) -> list[str]:
        payload = await self.rpc("resources/templates/list")
        return [
            entry["uriTemplate"] for entry in payload.get("result", {}).get("resourceTemplates", [])
        ]

    async def prompts(self) -> list[str]:
        payload = await self.rpc("prompts/list")
        return [entry["name"] for entry in payload.get("result", {}).get("prompts", [])]

    async def call(self, name: str, args: dict | None = None) -> dict:
        return await self.rpc("tools/call", {"name": name, "arguments": args or {}})

    async def read(self, uri: str) -> dict:
        return await self.rpc("resources/read", {"uri": uri})


def tool_payload(response: dict) -> dict:
    result = response.get("result") or {}
    content = result.get("content") or []
    if content and content[0].get("type") == "text":
        return json.loads(content[0]["text"])
    return result


@contextlib.asynccontextmanager
async def mcp_probe(db, plaintext: str | None, monkeypatch):
    import app.ai.mcp_server as mcp_module

    @contextlib.asynccontextmanager
    async def _shared():
        yield db

    monkeypatch.setattr(mcp_module, "_session", _shared)
    app = mcp_module.build_mcp_server().http_app()
    transport = httpx.ASGITransport(app=app)
    async with (
        app.lifespan(app),
        httpx.AsyncClient(transport=transport, base_url="http://mcp.test") as http,
    ):
        probe = Probe(http, plaintext)
        await probe.start()
        yield probe


async def read_token(db, auth_headers, *, label: str = "Laptop") -> str:
    _row, plaintext = await mcp_tokens.mint(
        db, UUID(_uid(auth_headers)), label=label, scopes=["read"]
    )
    await db.commit()
    return plaintext


async def write_token(db, auth_headers, *, label: str = "CLI") -> str:
    await mcp_tokens.set_write_enabled(db, True)
    _row, plaintext = await mcp_tokens.mint(
        db, UUID(_uid(auth_headers)), label=label, scopes=["read", "write"]
    )
    await db.commit()
    return plaintext
