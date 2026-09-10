from typing import Optional
from uuid import UUID

import httpx
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.chat_models import discover_google_models, token_cap_kwargs
from app.core.config import settings
from app.core.encryption import MASK_MARKER, encrypt_secret
from app.core.errors import PermissionDeniedError, ValidationError
from app.models.ai_provider_model import AIModel, AIProvider, AITaskAssignment
from app.models.enums import AIProviderType, AITaskTier
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


def _validate_tier(tier: Optional[str]) -> Optional[str]:
    """Normalise/validate a model-tier value."""
    if tier is None:
        return None
    try:
        return AITaskTier(tier).value
    except ValueError as exc:
        raise ValidationError(f"Unknown model tier: {tier}") from exc


def _validate_reasoning_effort(effort: Optional[str]) -> Optional[str]:
    """Normalise a reasoning-effort value (empty string clears the knob).

    Free text on purpose: OpenAI-style levels (none/minimal/low/medium/
    high/xhigh/max) cover the UI presets, and the "Custom…" fallback in
    the registry must keep working for provider-specific tokens.
    """
    if effort is None:
        return None
    return effort.strip() or None


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
        is_local: Optional[bool] = None,
        country: Optional[str] = None,
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
            is_local=is_local,
            country=country,
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
        is_local: Optional[bool] = None,
        country: Optional[str] = None,
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
        if is_local is not None:
            provider.is_local = is_local
        if country is not None:
            provider.country = country
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
        reasoning_effort: Optional[str] = None,
        tier: Optional[str] = None,
        caps: Optional[list[str]] = None,
    ) -> AIModel:
        """Add a model to a provider (tier declares which tier it serves)."""
        provider = await self.get_provider(provider_id, user)
        if provider.scope == "system" and not user.is_admin:
            raise ValidationError("Only admins can add models to global providers")
        model = AIModel(
            provider_id=provider.id,
            name=name,
            model_name=model_name,
            temperature=temperature,
            max_tokens=max_tokens,
            reasoning_effort=_validate_reasoning_effort(reasoning_effort),
            tier=_validate_tier(tier),
            caps=caps,
        )
        self.db.add(model)
        await self.db.commit()
        await self.db.refresh(model)
        return model

    async def update_model(
        self,
        model_id: UUID,
        user: User,
        *,
        name: Optional[str] = None,
        is_active: Optional[bool] = None,
        reasoning_effort: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        caps: Optional[list[str]] = None,
        set_temperature: bool = False,
        set_max_tokens: bool = False,
        set_reasoning_effort: bool = False,
        set_caps: bool = False,
    ) -> AIModel:
        """Edit a registered model (``set_*`` flags clear optional caps)."""
        rows = await self.db.execute(select(AIModel).where(AIModel.id == model_id))
        model = rows.scalars().first()
        if model is None:
            raise ValidationError("Model not found")
        provider = await self.get_provider(model.provider_id, user)
        if provider.scope == "system" and not user.is_admin:
            raise PermissionDeniedError("Only admins can edit global models")
        if name is not None:
            model.name = name
        if is_active is not None:
            model.is_active = is_active
        if set_reasoning_effort:
            model.reasoning_effort = _validate_reasoning_effort(reasoning_effort)
        if set_temperature:
            model.temperature = temperature
        if set_max_tokens:
            model.max_tokens = max_tokens
        if set_caps:
            model.caps = caps
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
        tier: str | None = None,
    ) -> AITaskAssignment:
        """Create/update the assignment for a task at a scope.

        ``model_id`` binds a concrete model (explicit override); a ``tier``
        with no model routes the task to the best model registered for that
        tier; both ``None`` clears the assignment.
        """
        if scope == "system" and not user.is_admin:
            raise PermissionDeniedError(
                "Only admins can change global task assignments"
            )
        tier = _validate_tier(tier)
        provider_id = None
        if model_id is not None:
            tier = None
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
        assignment_rows = await self.db.execute(
            select(AITaskAssignment).where(
                AITaskAssignment.task_type == task_type,
                AITaskAssignment.scope == scope,
                AITaskAssignment.user_id == (user.id if scope == "user" else None),
            )
        )
        assignment = assignment_rows.scalars().first()
        if assignment is None:
            assignment = AITaskAssignment(
                task_type=task_type,
                scope=scope,
                user_id=user.id if scope == "user" else None,
            )
            self.db.add(assignment)
        assignment.provider_id = provider_id
        assignment.model_id = model_id
        assignment.tier = tier
        assignment.is_active = model_id is not None or tier is not None
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

    async def fetch_external_models(
        self,
        provider_id: UUID,
        user: User,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ) -> list[dict]:
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
        if provider.provider_type == "google":
            return await self._fetch_external_models_google(provider)
        if provider.provider_type not in ("openai", "openai_compatible"):
            raise ValidationError(
                f"External model listing is not supported for {provider.provider_type}"
            )

        headers = {"Authorization": f"Bearer {provider.api_key or 'missing'}"}
        url = f"{provider.api_base.rstrip('/')}/models"
        try:
            async with httpx.AsyncClient(transport=transport) as client:
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

    async def _fetch_external_models_google(self, provider: AIProvider) -> list[dict]:
        """Gemini catalog — delegated to the model factory, the single
        google-genai import site (AI-layer import boundary)."""
        try:
            return await discover_google_models(provider.api_key, provider.api_base)
        except Exception as exc:
            raise ValidationError(f"Failed to fetch external models: {exc}") from exc

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

    async def run_test(
        self,
        user: User,
        *,
        provider_id: UUID,
        model_id: UUID,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ) -> dict:
        """Ping a provider/model with a minimal completion (plain httpx)."""
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
        if provider.provider_type == "google":
            return await self._run_test_google(provider, model, transport)
        url = f"{provider.api_base.rstrip('/')}/chat/completions"
        payload = {
            "model": model.model_name,
            "messages": [{"role": "user", "content": "Reply with the single word: OK"}],
            **token_cap_kwargs(provider.provider_type, 5, provider.api_base),
        }
        if model.temperature is not None:
            # Unset means "omit" — reasoning models reject non-default values.
            payload["temperature"] = model.temperature
        headers = {"Authorization": f"Bearer {provider.api_key or 'missing'}"}
        try:
            async with httpx.AsyncClient(transport=transport, timeout=20.0) as client:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                data = response.json()
            reply = (data["choices"][0]["message"]["content"] or "").strip()
            return {"ok": True, "reply": reply[:200]}
        except httpx.HTTPStatusError as exc:
            detail = f"Error code: {exc.response.status_code} - {exc.response.text}"
            return {"ok": False, "error": detail[:300]}
        except Exception as exc:
            return {"ok": False, "error": str(exc)[:300]}

    async def _run_test_google(
        self,
        provider: AIProvider,
        model: AIModel,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ) -> dict:
        """Connection test for native Gemini providers.

        The Gemini API has no OpenAI chat-completions wire, so instead of
        the raw REST ping this builds the real factory chat model (1-token
        cap) and invokes it — the transport seam keeps tests offline.
        """
        from app.ai.chat_models import build_chat_model
        from app.ai.providers.resolution import ResolvedModel

        resolved = ResolvedModel(
            provider_type=provider.provider_type,
            base_url=provider.api_base,
            api_key=provider.api_key,
            model_name=model.model_name,
            source="connection-test",
            temperature=model.temperature,
            max_tokens=5,
        )
        try:
            chat = build_chat_model(resolved, transport=transport)
            response = await chat.ainvoke("Reply with the single word: OK")
            content = response.content
            reply = content.strip() if isinstance(content, str) else str(content)
            return {"ok": True, "reply": reply[:200]}
        except Exception as exc:
            return {"ok": False, "error": str(exc)[:300]}
