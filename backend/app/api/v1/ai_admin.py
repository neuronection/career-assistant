from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.budgets import usage_rollups as usage_rollups_view
from app.ai.providers.resolution import known_task_types, resolve_task_model
from app.ai.providers.presets import PRESETS, PRESET_ORDER
from app.ai.providers.service import AIProviderService
from app.ai.tools import list_tools
from app.core.config import settings
from app.core.database import get_db
from app.core.encryption import mask_secret
from app.core.errors import DomainError
from app.models.ai_model import AIBudget
from app.models.user_model import User
from app.schemas.ai_admin import (
    AssignmentOut,
    AssignmentSet,
    BudgetCreate,
    BudgetOut,
    ConfigSummary,
    EffectiveAssignment,
    ModelCreate,
    ModelOut,
    ModelUpdate,
    ProviderCreate,
    ProviderOut,
    ProviderUpdate,
    TestResult,
    UsageRollup,
)
from app.services.deps import get_current_user, require_admin

router = APIRouter(prefix="/ai", tags=["ai-settings"])


def _provider_out(provider, user: User) -> dict:
    """Serialise a provider with a masked key."""
    return {
        "id": provider.id,
        "name": provider.name,
        "scope": provider.scope,
        "user_id": provider.user_id,
        "provider_type": provider.provider_type,
        "api_base": provider.api_base,
        "api_key": mask_secret(provider.api_key),
        "is_active": provider.is_active,
        "is_local": provider.is_local,
        "country": provider.country,
        "is_mine": provider.scope == "system" or provider.user_id == user.id,
        "created_at": provider.created_at,
    }


@router.get("/config/summary", response_model=ConfigSummary)
async def config_summary(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> ConfigSummary:
    """Effective model per task for the caller + management rights flag."""
    tasks = []
    for task in known_task_types():
        resolved = await resolve_task_model(db, task["value"], user.id)
        tasks.append(
            EffectiveAssignment(
                task_type=task["value"],
                source=resolved.source if resolved else "unconfigured",
                provider_type=resolved.provider_type if resolved else "none",
                model_name=resolved.model_name if resolved else "not configured",
                api_base=resolved.base_url if resolved else "",
                tier=resolved.tier if resolved else None,
            )
        )
    return ConfigSummary(
        tasks=tasks, can_manage_global=user.is_admin, mock_allowed=settings.is_dev
    )


@router.get("/tasks")
async def tasks(user: User = Depends(get_current_user)) -> list[dict]:
    """Assignable task types."""
    return known_task_types()


@router.get("/providers", response_model=list[ProviderOut])
async def list_providers(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[ProviderOut]:
    """Visible providers (global + personal), keys masked."""
    rows = await AIProviderService(db).list_providers(user)
    return [ProviderOut.model_validate(_provider_out(p, user)) for p in rows]


@router.get("/providers/presets")
async def provider_presets(
    user: User = Depends(get_current_user),
) -> dict[str, dict]:
    """The settings form's provider catalog (name/type/base URL/local).

    Static metadata — the client never has to hardcode endpoint URLs;
    ``local`` presets default the hosting toggle. Must be declared before
    ``/providers/{provider_id}``.
    """
    return {key: dict(PRESETS[key]) for key in PRESET_ORDER}


@router.post("/providers", response_model=ProviderOut, status_code=201)
async def create_provider(
    data: ProviderCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProviderOut:
    """Add a provider (scope=user for personal; scope=system needs admin)."""
    try:
        provider = await AIProviderService(db).create_provider(
            user,
            name=data.name,
            provider_type=data.provider_type,
            api_base=data.api_base,
            api_key=data.api_key,
            scope=data.scope,
            is_local=data.is_local,
            country=data.country,
        )
    except DomainError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    return ProviderOut.model_validate(_provider_out(provider, user))


@router.put("/providers/{provider_id}", response_model=ProviderOut)
async def update_provider(
    provider_id: UUID,
    data: ProviderUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProviderOut:
    """Update a provider; send api_key "***" to keep the current key."""
    try:
        provider = await AIProviderService(db).update_provider(
            provider_id,
            user,
            name=data.name,
            provider_type=data.provider_type,
            api_base=data.api_base,
            api_key=data.api_key,
            is_active=data.is_active,
            is_local=data.is_local,
            country=data.country,
        )
    except DomainError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return ProviderOut.model_validate(_provider_out(provider, user))


@router.delete("/providers/{provider_id}", status_code=204)
async def delete_provider(
    provider_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a provider and its models/assignments."""
    try:
        await AIProviderService(db).delete_provider(provider_id, user)
    except DomainError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.get("/providers/{provider_id}/models", response_model=list[ModelOut])
async def list_models(
    provider_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ModelOut]:
    """Models of a provider."""
    rows = await AIProviderService(db).list_models(provider_id, user)
    return [ModelOut.model_validate(m) for m in rows]


@router.post(
    "/providers/{provider_id}/models", response_model=ModelOut, status_code=201
)
async def add_model(
    provider_id: UUID,
    data: ModelCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ModelOut:
    """Add a model to a provider."""
    try:
        model = await AIProviderService(db).add_model(
            provider_id,
            user,
            name=data.name,
            model_name=data.model_name,
            temperature=data.temperature,
            max_tokens=data.max_tokens,
            reasoning_effort=data.reasoning_effort,
            tier=data.tier,
            caps=data.caps,
        )
    except DomainError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return ModelOut.model_validate(model)


@router.put("/models/{model_id}", response_model=ModelOut)
async def update_model(
    model_id: UUID,
    data: ModelUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ModelOut:
    """Edit a registered model; omitted fields stay unchanged."""
    try:
        model = await AIProviderService(db).update_model(
            model_id,
            user,
            name=data.name,
            is_active=data.is_active,
            reasoning_effort=data.reasoning_effort,
            temperature=data.temperature,
            max_tokens=data.max_tokens,
            caps=data.caps,
            set_temperature="temperature" in data.model_fields_set,
            set_max_tokens="max_tokens" in data.model_fields_set,
            set_reasoning_effort="reasoning_effort" in data.model_fields_set,
            set_caps="caps" in data.model_fields_set,
        )
    except DomainError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return ModelOut.model_validate(model)


@router.delete("/models/{model_id}", status_code=204)
async def delete_model(
    model_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a model."""
    try:
        await AIProviderService(db).delete_model(model_id, user)
    except DomainError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.get("/providers/{provider_id}/fetch-external-models")
async def fetch_external_models(
    provider_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Available models from the provider's API catalog (mock returns canned ids)."""
    try:
        return await AIProviderService(db).fetch_external_models(provider_id, user)
    except DomainError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.get("/models")
async def list_all_models(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[dict]:
    """All visible models with provider info (for assignment pickers)."""
    pairs = await AIProviderService(db).list_all_models(user)
    return [
        {
            "id": model.id,
            "provider_id": model.provider_id,
            "name": model.name,
            "model_name": model.model_name,
            "tier": model.tier,
            "provider_name": provider.name,
            "provider_scope": provider.scope,
            "provider_type": provider.provider_type,
        }
        for model, provider in pairs
    ]


@router.get("/assignments", response_model=list[AssignmentOut])
async def list_assignments(
    scope: str = "user",
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[AssignmentOut]:
    """Stored assignments at a scope ('user' or 'system'; system = admin view)."""
    if scope == "system" and not user.is_admin:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only admins can view global assignments"
        )
    rows = await AIProviderService(db).list_assignments(user, scope)
    return [AssignmentOut.model_validate(a) for a in rows]


@router.put("/assignments/{task_type}", response_model=AssignmentOut)
async def set_assignment(
    task_type: str,
    data: AssignmentSet,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AssignmentOut:
    """Assign a model — or a tier — to a task. model_id=null + tier=null clears."""
    if task_type not in {t["value"] for t in known_task_types()}:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown task type")
    try:
        assignment = await AIProviderService(db).set_assignment(
            user,
            task_type=task_type,
            scope=data.scope,
            model_id=data.model_id,
            tier=data.tier,
        )
    except DomainError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return AssignmentOut.model_validate(assignment)


@router.get("/tools")
async def tools(user: User = Depends(get_current_user)) -> list[dict]:
    """Registered AI tools."""
    return list_tools()


@router.post("/embeddings/recompute")
async def recompute_embeddings(
    limit: int = 50,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Embed stale/un-embedded postings.

    Admin-triggered batch pass; the gateway ``embed`` task carries the
    provider config (DB-only) and the audit funnel."""
    from app.services.embedding_service import EmbeddingService

    result = await EmbeddingService(db).recompute_postings(
        limit=max(1, min(limit, 200))
    )
    return result


@router.get("/embeddings/status")
async def embeddings_status(
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Embedding store coverage per entity kind."""
    from app.services.embedding_service import EmbeddingService

    return await EmbeddingService(db).status()


# ------------------------------------------------------- MCP bridge (41b)


@router.get("/mcp/token")
async def mcp_token_status(user: User = Depends(require_admin)) -> dict:
    """The instance MCP server token status (never the token itself)."""
    from app.ai.mcp_server import token_store

    info = token_store().read()
    return {
        "provisioned": bool(info and info.get("token")),
        "bound_user_id": (info or {}).get("user_id"),
        "created_at": (info or {}).get("created_at"),
    }


@router.post("/mcp/token")
async def rotate_mcp_token(
    user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> dict:
    """Generate a fresh MCP token bound to the calling admin — the old
    token is invalidated immediately. Shown once."""
    from app.ai.mcp_server import token_store

    info = token_store().rotate(str(user.id))
    return {"token": info["token"], "bound_user_id": info["user_id"]}


@router.get("/mcp/servers")
async def list_mcp_servers(
    user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> list[dict]:
    """Registered external MCP servers."""
    from app.services.mcp_bridge_service import MCPBridgeService

    rows = await MCPBridgeService(db).list_servers()
    return [
        {
            "id": str(row.id),
            "name": row.name,
            "transport": row.transport,
            "url": row.url,
            "command": row.command,
            "token_masked": row.token_masked,
            "enabled": row.enabled,
            "discovered_tools": row.discovered_tools or [],
            "enabled_tools": row.enabled_tools or [],
            "last_synced_at": (
                row.last_synced_at.isoformat() if row.last_synced_at else None
            ),
        }
        for row in rows
    ]


@router.post("/mcp/servers", status_code=201)
async def register_mcp_server(
    payload: dict,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Register an external MCP server (disabled by default)."""
    from app.services.mcp_bridge_service import MCPBridgeService

    row = await MCPBridgeService(db).register(
        name=str(payload.get("name") or ""),
        transport=str(payload.get("transport") or "http"),
        url=str(payload.get("url") or ""),
        command=str(payload.get("command") or ""),
        token=str(payload.get("token") or ""),
        created_by=user.id,
    )
    return {"id": str(row.id), "name": row.name, "enabled": row.enabled}


@router.post("/mcp/servers/{server_id}/refresh")
async def refresh_mcp_server(
    server_id: UUID,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Re-discover the server's tools (new tools start disabled)."""
    from app.services.mcp_bridge_service import MCPBridgeService

    row = await MCPBridgeService(db).refresh(server_id)
    return {
        "id": str(row.id),
        "discovered_tools": row.discovered_tools or [],
        "enabled_tools": row.enabled_tools or [],
        "last_synced_at": (
            row.last_synced_at.isoformat() if row.last_synced_at else None
        ),
    }


@router.post("/mcp/servers/{server_id}/tools/{tool_name}")
async def set_mcp_tool_enabled(
    server_id: UUID,
    tool_name: str,
    payload: dict,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Enable/disable one namespaced tool (explicit allowlist)."""
    from app.services.mcp_bridge_service import MCPBridgeService

    row = await MCPBridgeService(db).set_tool_enabled(
        server_id, tool_name, bool(payload.get("enabled"))
    )
    return {"id": str(row.id), "enabled_tools": row.enabled_tools or []}


@router.post("/mcp/servers/{server_id}/invoke")
async def invoke_mcp_tool(
    server_id: UUID,
    payload: dict,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Execute one enabled tool on an external MCP server — audited and
    budgeted through the ``mcp_tool_call`` task."""
    from app.services.mcp_bridge_service import MCPBridgeService

    result = await MCPBridgeService(db).invoke(
        server_id,
        str(payload.get("tool") or ""),
        payload.get("arguments") or {},
        user_id=user.id,
    )
    return result


@router.post("/test", response_model=TestResult)
async def test_connection(
    provider_id: UUID,
    model_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TestResult:
    """Send a tiny completion to verify provider credentials."""
    result = await AIProviderService(db).run_test(
        user, provider_id=provider_id, model_id=model_id
    )
    if result["ok"]:
        return TestResult(ok=True, reply=result.get("reply", ""))
    return TestResult(ok=False, error=result.get("error", "unknown error"))


@router.get("/budgets", response_model=list[BudgetOut])
async def list_budgets(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[BudgetOut]:
    """Active + inactive token budgets (admin-only)."""
    if not user.is_admin:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only admins can manage AI budgets"
        )
    rows = await db.execute(select(AIBudget).order_by(AIBudget.name))
    return [BudgetOut.model_validate(b) for b in rows.scalars().all()]


@router.post("/budgets", response_model=BudgetOut, status_code=201)
async def create_budget(
    data: BudgetCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BudgetOut:
    """Add a token budget with a hard stop (admin-only)."""
    if not user.is_admin:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only admins can manage AI budgets"
        )
    if data.task_type is not None and data.task_type not in {
        t["value"] for t in known_task_types()
    }:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown task type")
    exists = await db.execute(
        select(AIBudget).where(AIBudget.name == data.name).limit(1)
    )
    if exists.scalars().first() is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Budget name already exists")
    budget = AIBudget(
        name=data.name,
        task_type=data.task_type,
        user_id=data.user_id,
        window=data.window,
        max_tokens=data.max_tokens,
    )
    db.add(budget)
    await db.commit()
    await db.refresh(budget)
    return BudgetOut.model_validate(budget)


@router.delete("/budgets/{budget_id}", status_code=204)
async def delete_budget(
    budget_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Remove a budget (admin-only)."""
    if not user.is_admin:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only admins can manage AI budgets"
        )
    rows = await db.execute(select(AIBudget).where(AIBudget.id == budget_id))
    budget = rows.scalars().first()
    if budget is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Budget not found")
    await db.delete(budget)
    await db.commit()


@router.get("/usage/rollups", response_model=list[UsageRollup])
async def usage_rollups(
    window: str = "day",
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[UsageRollup]:
    """Per-task token/call rollups from the audit ledger (admin-only)."""
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only admins can view AI usage")
    if window not in ("day", "month"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "window must be day|month")
    return [UsageRollup.model_validate(r) for r in await usage_rollups_view(db, window)]
