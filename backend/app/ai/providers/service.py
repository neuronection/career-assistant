from typing import Optional
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.encryption import MASK_MARKER, encrypt_secret
from app.core.errors import PermissionDeniedError, ValidationError
from app.models.ai_provider_model import AIModel, AIProvider, AITaskAssignment
from app.models.enums import AIProviderType
from app.models.user_model import User


def _validate_provider_type(provider_type: str) -> str:
    """Normalise/validate a provider type value (mock is dev-only)."""
    try:
        validated = AIProviderType(provider_type).value
    except ValueError as exc:
        raise ValidationError(f"Unknown provider type: {provider_type}") from exc
    if validated == AIProviderType.MOCK.value and not settings.is_dev:
        raise ValidationError(
            "The mock provider is only available in development environments."
        )
    return validated


class AIProviderService:
    """CRUD for providers, models and task assignments (scoped)."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_providers(self, user: User) -> list[AIProvider]:
        """System providers + the caller's personal providers."""
        rows = await self.db.execute(
            select(AIProvider)
            .where(or_(AIProvider.scope == "system", AIProvider.user_id == user.id))
            .order_by(AIProvider.scope, AIProvider.name)
        )
        return list(rows.scalars().all())

    async def get_provider(self, provider_id: UUID, user: User) -> AIProvider:
        """Fetch a provider the caller can see."""
        rows = await self.db.execute(
            select(AIProvider).where(AIProvider.id == provider_id)
        )
        provider = rows.scalars().first()
        if provider is None:
            raise ValidationError("Provider not found")
        if provider.scope == "user" and provider.user_id != user.id:
            raise PermissionDeniedError("Not your provider")
        return provider

    async def create_provider(
        self,
        user: User,
        *,
        name: str,
        provider_type: str,
        api_base: str,
        api_key: Optional[str],
        scope: str = "user",
    ) -> AIProvider:
        """Create a provider; system scope requires admin."""
        if scope == "system" and not user.is_admin:
            raise PermissionDeniedError("Only admins can add global providers")
        provider = AIProvider(
            name=name,
            scope=scope,
            user_id=user.id if scope == "user" else None,
            provider_type=_validate_provider_type(provider_type),
            api_base=api_base,
            api_key_encrypted=encrypt_secret(api_key),
        )
        self.db.add(provider)
        await self.db.commit()
        await self.db.refresh(provider)
        return provider

    async def update_provider(
        self,
        provider_id: UUID,
        user: User,
        *,
        name: Optional[str] = None,
        provider_type: Optional[str] = None,
        api_base: Optional[str] = None,
        api_key: Optional[str] = None,
        is_active: Optional[bool] = None,
    ) -> AIProvider:
        """Update a provider; ``***`` preserves the existing key."""
        provider = await self.get_provider(provider_id, user)
        if provider.scope == "system" and not user.is_admin:
            raise PermissionDeniedError("Only admins can edit global providers")
        if name is not None:
            provider.name = name
        if provider_type is not None:
            provider.provider_type = _validate_provider_type(provider_type)
        if api_base is not None:
            provider.api_base = api_base
        if is_active is not None:
            provider.is_active = is_active
        if api_key is not None and api_key != MASK_MARKER:
            provider.api_key_encrypted = encrypt_secret(api_key)
        self.db.add(provider)
        await self.db.commit()
        await self.db.refresh(provider)
        return provider

    async def delete_provider(self, provider_id: UUID, user: User) -> None:
        """Delete a provider the caller owns (or any global one if admin)."""
        provider = await self.get_provider(provider_id, user)
        if provider.scope == "system" and not user.is_admin:
            raise PermissionDeniedError("Only admins can delete global providers")
        await self.db.delete(provider)
        await self.db.commit()

    async def list_models(self, provider_id: UUID, user: User) -> list[AIModel]:
        """Models of a provider the caller can see."""
        await self.get_provider(provider_id, user)
        rows = await self.db.execute(
            select(AIModel)
            .where(AIModel.provider_id == provider_id)
            .order_by(AIModel.name)
        )
        return list(rows.scalars().all())

    async def add_model(
        self,
        provider_id: UUID,
        user: User,
        *,
        name: str,
        model_name: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> AIModel:
        """Add a model to a provider."""
        provider = await self.get_provider(provider_id, user)
        if provider.scope == "system" and not user.is_admin:
            raise PermissionDeniedError(
                "Only admins can add models to global providers"
            )
        model = AIModel(
            provider_id=provider.id,
            name=name,
            model_name=model_name,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        self.db.add(model)
        await self.db.commit()
        await self.db.refresh(model)
        return model

    async def delete_model(self, model_id: UUID, user: User) -> None:
        """Delete a model (and its assignments)."""
        rows = await self.db.execute(select(AIModel).where(AIModel.id == model_id))
        model = rows.scalars().first()
        if model is None:
            raise ValidationError("Model not found")
        provider = await self.get_provider(model.provider_id, user)
        if provider.scope == "system" and not user.is_admin:
            raise PermissionDeniedError("Only admins can delete global models")
        await self.db.delete(model)
        await self.db.commit()

    async def set_assignment(
        self,
        user: User,
        *,
        task_type: str,
        scope: str,
        model_id: UUID | None,
    ) -> AITaskAssignment:
        """Create/update the assignment for a task at a scope (None clears)."""
        if scope == "system" and not user.is_admin:
            raise PermissionDeniedError(
                "Only admins can change global task assignments"
            )
        provider_id = None
        if model_id is not None:
            rows = await self.db.execute(select(AIModel).where(AIModel.id == model_id))
            model = rows.scalars().first()
            if model is None:
                raise ValidationError("Model not found")
            provider = await self.get_provider(model.provider_id, user)
            if provider.scope != scope and not (
                scope == "system" and provider.scope == "system"
            ):
                raise PermissionDeniedError("Model belongs to another scope")
            provider_id = provider.id
        rows = await self.db.execute(
            select(AITaskAssignment).where(
                AITaskAssignment.task_type == task_type,
                AITaskAssignment.scope == scope,
                AITaskAssignment.user_id == (user.id if scope == "user" else None),
            )
        )
        assignment = rows.scalars().first()
        if assignment is None:
            assignment = AITaskAssignment(
                task_type=task_type,
                scope=scope,
                user_id=user.id if scope == "user" else None,
            )
            self.db.add(assignment)
        assignment.provider_id = provider_id
        assignment.model_id = model_id
        assignment.is_active = model_id is not None
        await self.db.commit()
        await self.db.refresh(assignment)
        return assignment

    async def list_assignments(self, user: User, scope: str) -> list[AITaskAssignment]:
        """Assignments at one scope visible to the caller."""
        query = select(AITaskAssignment).where(AITaskAssignment.scope == scope)
        if scope == "user":
            query = query.where(AITaskAssignment.user_id == user.id)
        rows = await self.db.execute(query)
        return list(rows.scalars().all())

    async def fetch_external_models(self, provider_id: UUID, user: User) -> list[dict]:
        """Fetch available models from the provider's /models API endpoint.

        Works with OpenAI-style catalogs (openai + openai_compatible); mock
        providers return a canned list.
        """
        provider = await self.get_provider(provider_id, user)
        if provider.provider_type == "mock":
            if not settings.is_dev:
                raise ValidationError(
                    "The mock provider is only available in development."
                )
            return [
                {"id": "mock-large", "name": "Mock Large", "owned_by": "mock"},
                {"id": "mock-small", "name": "Mock Small", "owned_by": "mock"},
            ]
        if provider.provider_type not in ("openai", "openai_compatible"):
            raise ValidationError(
                f"External model listing is not supported for {provider.provider_type}"
            )

        import httpx

        headers = {"Authorization": f"Bearer {provider.api_key or 'missing'}"}
        url = f"{provider.api_base.rstrip('/')}/models"
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=headers, timeout=10.0)
                response.raise_for_status()
                data = response.json()
        except Exception as exc:
            raise ValidationError(f"Failed to fetch external models: {exc}") from exc

        models = [
            {
                "id": item.get("id"),
                "name": item.get("id"),
                "owned_by": item.get("owned_by"),
            }
            for item in data.get("data", [])
            if item.get("id")
        ]
        models.sort(key=lambda m: m["name"])
        return models

    async def list_all_models(self, user: User) -> list[tuple[AIModel, AIProvider]]:
        """All active models the caller can see, joined with their provider."""
        rows = await self.db.execute(
            select(AIModel, AIProvider)
            .join(AIProvider, AIModel.provider_id == AIProvider.id)
            .where(
                AIModel.is_active.is_(True),
                or_(AIProvider.scope == "system", AIProvider.user_id == user.id),
            )
            .order_by(AIProvider.name, AIModel.name)
        )
        return [(model, provider) for model, provider in rows.all()]

    async def run_test(self, user: User, *, provider_id: UUID, model_id: UUID) -> dict:
        """Ping a provider/model with a minimal completion."""
        provider = await self.get_provider(provider_id, user)
        rows = await self.db.execute(select(AIModel).where(AIModel.id == model_id))
        model = rows.scalars().first()
        if model is None or model.provider_id != provider.id:
            raise ValidationError("Model not found on this provider")
        if provider.provider_type == "mock":
            if not settings.is_dev:
                raise ValidationError(
                    "The mock provider is only available in development."
                )
            return {"ok": True, "reply": "mock provider: always OK"}
        try:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(
                api_key=provider.api_key or "missing",
                base_url=provider.api_base,
                timeout=20,
            )
            response = await client.chat.completions.create(
                model=model.model_name,
                messages=[
                    {"role": "user", "content": "Reply with the single word: OK"}
                ],
                max_tokens=5,
                temperature=0,
            )
            reply = (response.choices[0].message.content or "").strip()
            return {"ok": True, "reply": reply[:200]}
        except Exception as exc:
            return {"ok": False, "error": str(exc)[:300]}
