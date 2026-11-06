"""MCP server v2 (plan 119): the registry projected over the Model
Context Protocol — tools, resources and prompts, token-scoped.

Transport = Streamable HTTP mounted at ``/mcp`` (loopback in desktop /
self-host deployments). Governance:

- **Token auth** — bearer secrets live hashed in ``mcp_tokens`` (plan
  113); rotation revokes the predecessor and links the chain. Every
  verification re-reads the table, so revoke/rotate is live.
- **Scopes are typed and enforced per component** — ``read`` exposes the
  read-scope registry tools and the user-data resources; ``write`` (only
  when the admin ``mcp.write_enabled`` switch is on) adds the write
  tools. FastMCP auth checks filter both ``tools/list`` and every call.
- **Same funnel** — handlers execute through the tool registry's
  ``run_tool`` with their own DB session; every call is audited on the
  ``mcp_tool_call`` ledger and budget-checked; the shared limiter wraps
  the ASGI app per client host.
"""

import inspect
import json
import time
import uuid
from typing import Any

from app.core.config import settings
from app.middleware import RATE_LIMIT_POLICY
from app.models.enums import McpTokenScope

READ_SCOPE = McpTokenScope.READ.value
WRITE_SCOPE = McpTokenScope.WRITE.value


def _session():
    """A fresh session for one MCP request (tests patch this seam so the
    server shares the test transaction)."""
    from app.core.database import AsyncSessionLocal

    return AsyncSessionLocal()


def _access_token():
    """The current request's AccessToken (None outside an authenticated
    MCP request)."""
    from fastmcp.server.dependencies import get_access_token

    return get_access_token()


def _claims(access=None) -> dict:
    token = access or _access_token()
    return dict((token.claims or {}) if token is not None else {})


def _bound_user(claims: dict) -> uuid.UUID | None:
    value = claims.get("user_id")
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


def _token_of(context):
    """The AccessToken behind an AuthContext (or None)."""
    return getattr(context, "token", context)


def _read_scope(context) -> bool:
    token = _token_of(context)
    return bool(token is not None and READ_SCOPE in (token.scopes or []))


def _bound_read_scope(context) -> bool:
    """Read scope AND a token bound to a user — the user-data resources."""
    token = _token_of(context)
    return _read_scope(context) and bool(_bound_user(dict(token.claims or {})))


async def _write_scope(context) -> bool:
    """Write scope AND the admin switch on (default OFF)."""
    token = _token_of(context)
    if not (token is not None and WRITE_SCOPE in (token.scopes or [])):
        return False
    from app.services.admin import mcp_tokens

    async with _session() as db:
        return await mcp_tokens.write_enabled(db)


def token_verifier():
    """Build the FastMCP token verifier over the ``mcp_tokens`` table."""
    from fastmcp.server.auth import TokenVerifier

    class InstanceTokenVerifier(TokenVerifier):
        async def verify_token(self, token: str):
            from fastmcp.server.auth.providers.jwt import AccessToken

            from app.services.admin import mcp_tokens

            async with _session() as db:
                row = await mcp_tokens.resolve(db, token)
                if row is None:
                    return None
                await db.commit()
                claims = {
                    "token_id": str(row.id),
                    "user_id": str(row.user_id) if row.user_id is not None else None,
                    "label": row.label,
                }
                scopes = list(row.scopes or [READ_SCOPE])
            return AccessToken(
                token=token,
                client_id=f"mcp:{row.id}",
                scopes=scopes,
                claims=claims,
            )

    return InstanceTokenVerifier()


async def _audit_call(
    db,
    *,
    user_id: uuid.UUID | None,
    token_label: str,
    request_id: str,
    tool_key: str,
    args: dict,
    ok: bool,
    error: str,
    duration_ms: float,
) -> None:
    """One `mcp_tool_call` audit row (the recent-call view reads these)."""
    from app.ai.gateway import _record
    from app.models.enums import AITaskType

    try:
        await _record(
            db,
            user_id,
            AITaskType.MCP_TOOL_CALL,
            "http",
            f"mcp-server:{token_label or 'unbound'}:{tool_key}",
            {
                "args": json.loads(json.dumps(args, default=str)),
                "ok": ok,
                "request_id": request_id,
                "tool": tool_key,
            },
            None,
            None,
            duration_ms,
            "ok" if ok else "error",
            error,
            model_name=token_label or "mcp",
            provider_type="mcp",
        )
        await db.commit()
    except Exception:
        import logging

        logging.getLogger(__name__).exception("mcp tool audit write failed")


def _dynamic_handler(tool):
    """An async handler whose signature mirrors the tool's pydantic
    input model, so FastMCP derives a flat JSON Schema for MCP clients."""

    async def handler(**kwargs):
        from app.ai.budgets import enforce_budgets
        from app.ai.tools import run_tool
        from app.models.enums import AITaskType

        claims = _claims()
        user_id = _bound_user(claims)
        label = str(claims.get("label") or "")
        request_id = str(uuid.uuid4())
        if tool.requires_user and user_id is None:
            raise ValueError(
                "This tool requires a token bound to a user; mint one as a "
                "signed-in admin in Settings → Tools → Connectors → MCP."
            )
        started = time.monotonic()
        async with _session() as db:
            await enforce_budgets(db, AITaskType.MCP_TOOL_CALL, user_id)
            try:
                result = await run_tool(
                    db,
                    tool.key,
                    user_id,
                    args=dict(kwargs),
                    source="mcp",
                    origin={
                        "channel": "mcp",
                        "token_id": claims.get("token_id"),
                        "token_label": label,
                        "request_id": request_id,
                        "tool": tool.key,
                    },
                )
                payload = json.loads(json.dumps(result, default=str))
            except Exception as exc:
                await _audit_call(
                    db,
                    user_id=user_id,
                    token_label=label,
                    request_id=request_id,
                    tool_key=tool.key,
                    args=kwargs,
                    ok=False,
                    error=f"{type(exc).__name__}: {exc}"[:1000],
                    duration_ms=(time.monotonic() - started) * 1000,
                )
                raise
            await _audit_call(
                db,
                user_id=user_id,
                token_label=label,
                request_id=request_id,
                tool_key=tool.key,
                args=kwargs,
                ok=True,
                error="",
                duration_ms=(time.monotonic() - started) * 1000,
            )
            return payload

    parameters = []
    annotations: dict[str, Any] = {}
    for name, field_info in tool.input_model.model_fields.items():
        annotations[name] = field_info.annotation
        if field_info.is_required():
            default = ...
        elif field_info.default_factory is not None:
            default = field_info.default_factory()
        else:
            default = field_info.default
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


def _registry_tool(key: str):
    from app.ai.tools import get_tool

    try:
        return get_tool(key)
    except Exception:
        return None


async def _resource_payload(tool_key: str, args: dict | None = None) -> str:
    """Run one read tool for the token-bound user and serialize it."""
    from app.ai.tools import run_tool

    claims = _claims()
    user_id = _bound_user(claims)
    if user_id is None:
        raise ValueError("This resource requires a token bound to a user")
    async with _session() as db:
        result = await run_tool(db, tool_key, user_id, args=args or {})
    return json.dumps(result, indent=2, default=str)


def build_mcp_server():
    """The FastMCP server: registry tools + resources + prompts."""
    from fastmcp import FastMCP

    from app.ai.tools import list_tools

    mcp = FastMCP(
        "career-assistant",
        instructions=(
            "Career Assistant exposes the user's own career data. Read tools "
            "cover the catalog, live postings, profile digests, the "
            "application tracker, deadlines, saved searches, market history "
            "and fit breakdowns. Resources: career://profile, "
            "career://applications, career://saved-searches, "
            "career://cv/{id}. Prompts package the common flows. Write tools "
            "appear only for a write-scope token while the admin switch is on, "
            "and every write is an approval card — never a direct mutation."
        ),
        auth=token_verifier(),
    )

    for tool_data in list_tools():
        if tool_data.get("kind") != "tool":
            continue
        scope = tool_data["scope"]
        if scope not in (READ_SCOPE, WRITE_SCOPE):
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
                auth=_read_scope if scope == READ_SCOPE else _write_scope,
            )
        )

    @mcp.resource(
        "career://profile",
        name="Profile digest",
        description="Privacy-minimized profile overview (name, languages, counts).",
        mime_type="application/json",
        auth=_bound_read_scope,
    )
    async def profile_resource() -> str:
        return await _resource_payload("my_profile_digest")

    @mcp.resource(
        "career://applications",
        name="Application pipeline",
        description="The token owner's application rows with stages and dates.",
        mime_type="application/json",
        auth=_bound_read_scope,
    )
    async def applications_resource() -> str:
        return await _resource_payload("my_applications")

    @mcp.resource(
        "career://saved-searches",
        name="Saved searches",
        description="Saved searches (query, filters) with their ids.",
        mime_type="application/json",
        auth=_bound_read_scope,
    )
    async def saved_searches_resource() -> str:
        return await _resource_payload("my_saved_searches")

    @mcp.resource(
        "career://cv/{cv_id}",
        name="CV items",
        description="One owned CV's item ids and bullets (public-safe fields only).",
        mime_type="application/json",
        auth=_bound_read_scope,
    )
    async def cv_resource(cv_id: str) -> str:
        return await _resource_payload("read_cv_items", {"cv_id": cv_id})

    @mcp.prompt(
        name="tailor_cv_to_posting",
        description="Plan a CV tailored to one posting (references only).",
        auth=_read_scope,
    )
    def tailor_cv_to_posting(cv_id: str, posting_ref: str) -> str:
        return (
            f"Read career://cv/{cv_id} and the posting by its ref "
            f"({posting_ref}) with get_posting, then my_fit_breakdown for the "
            "posting. Compare the posting's requirements with the CV's "
            "bullets and propose concrete bullet/template changes only "
            "through the write tools, which always create approval cards. "
            "Never invent experience or metrics."
        )

    @mcp.prompt(
        name="prepare_interview_plan",
        description="Build an interview plan for one application (references only).",
        auth=_read_scope,
    )
    def prepare_interview_plan(application_id: str) -> str:
        return (
            f"Read my_application_timeline for application {application_id} to "
            "learn its stage and history, then my_deadlines. Ask which "
            "interview format is expected if it is not in the timeline. Base "
            "the plan on that application's posting (get_posting) and the "
            "candidate's own evidence — do not invent employers, dates or "
            "questions attributed to the company."
        )

    @mcp.prompt(
        name="summarize_my_fit",
        description="Explain one fit score from its dimensions (references only).",
        auth=_read_scope,
    )
    def summarize_my_fit(target: str) -> str:
        return (
            f"Call my_fit_breakdown with target {target} and narrate ONLY the "
            "returned dimensions and gate reasons (0-10, higher is better). "
            "If the result is an estimate (the posting is not deep-extracted) "
            "say so. Do not re-score or invent numbers."
        )

    return mcp


def _mcp_rate_limit_middleware(asgi_app):
    """Per-client-host rate limiting around the MCP ASGI app."""

    async def middleware(scope, receive, send):
        if scope.get("type") != "http":
            await asgi_app(scope, receive, send)
            return
        client = scope.get("client") or ("unknown", 0)
        retry_after = await RATE_LIMIT_POLICY.hit(f"mcp:{client[0]}", limit=settings.ratelimit_mcp)
        if retry_after is not None:
            body = json.dumps({"detail": f"rate limited; retry in {retry_after}s"}).encode()
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
    """The rate-limited ASGI app to mount at ``/mcp``.

    The inner FastMCP HTTP app serves at its root because Starlette's
    ``mount`` strips the ``/mcp`` prefix before dispatch; its ``lifespan``
    is re-attached to the wrapper so the parent app can compose it (the
    StreamableHTTP session manager's task group lives there).
    """
    inner = build_mcp_server().http_app(path="/")
    wrapped = _mcp_rate_limit_middleware(inner)
    wrapped.lifespan = inner.lifespan
    return wrapped


def _default_limits() -> tuple[tuple[str, int, int], ...]:
    return (("mcp", 120, 60),)
