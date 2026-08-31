from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.providers.resolution import known_task_types, resolve_task_model
from app.ai.providers.service import AIProviderService
from app.core.config import settings
from app.core.database import get_db
from app.core.encryption import mask_secret
from app.core.errors import DomainError
from app.models.user_model import User
from app.schemas.ai_admin import (
    AssignmentOut,
    AssignmentSet,
    ConfigSummary,
    EffectiveAssignment,
    ModelCreate,
    ModelOut,
    ProviderCreate,
    ProviderOut,
    ProviderUpdate,
    TestResult,
)
from app.services.deps import get_current_user

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
    """Assign a model to a task. model_id=null clears (falls back to defaults)."""
    if task_type not in {t["value"] for t in known_task_types()}:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown task type")
    try:
        assignment = await AIProviderService(db).set_assignment(
            user, task_type=task_type, scope=data.scope, model_id=data.model_id
        )
    except DomainError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return AssignmentOut.model_validate(assignment)


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
