"""BYOK one-click provider setup (§15 frozen contract, plan 100 batch B).

Fetch-first validation (nothing persists on classified failure), curated
allowlists (exact-or-snapshot-suffix with the ``curated_missed``
zero-match fallback), append-union catalog persistence, capability-aware
gap-fill that never clobbers live slots (chat/vision/stt + decision),
dead-id rebinding, ``preset_key`` adoption of matching manual rows —
all strictly scope-local: a setup at USER scope never touches SYSTEM
rows and vice versa (health-precedent scope-awareness).
"""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.decide.registry import DECISION_DEFAULT_TASK_TYPE
from app.ai.decide.systemone.probe import (
    DecisionProbeInput,
    DecisionProbeResult,
    probe_decision_provider,
)
from app.ai.providers.errors import ClassifiedProviderError, classify_provider_error
from app.ai.providers.presets import ALL_PRESETS, decision_probe_model_id
from app.ai.providers.service import infer_caps
from app.core.encryption import encrypt_secret
from app.models.ai_provider_model import AIModel, AIProvider, AITaskAssignment
from app.models.user_model import User

FETCH_TIMEOUT_SECONDS = 10.0


class UnknownPresetError(Exception):
    pass


class CrossProviderModelError(Exception):
    pass


class SetupError(Exception):
    def __init__(self, classified: ClassifiedProviderError, vendor_message: str) -> None:
        super().__init__(vendor_message)
        self.classified = classified
        self.vendor_message = vendor_message


@dataclass
class SetupOptions:
    curated_ids: list[str] | None = None
    bind_chat: bool = True
    bind_vision: bool = True
    bind_stt: bool = True
    bind_embeddings: bool = True
    bind_decision: bool = True


@dataclass(frozen=True)
class SetupOutcome:
    provider_id: UUID
    catalog_count: int
    curated_missed: bool
    assigned_chat_model: str | None = None
    assigned_vision_model: str | None = None
    assigned_stt_model: str | None = None
    assigned_embeddings_model: str | None = None
    assigned_decision_slots: dict[str, str] | None = None


@dataclass
class _PersistedModel:
    model_name: str
    caps: list[str]


@dataclass(frozen=True)
class RemoteModel:
    external_id: str
    caps: tuple[str, ...]


async def fetch_remote_models(
    provider_type: str,
    base_url: str,
    api_key: str | None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> list[RemoteModel]:
    """Fetch a provider's model catalog (OpenAI wire, Gemini, or mock).

    The §15 fetch-first validation call: abort-timeout bounded, never
    retried here — classified failures bubble to the caller.
    """
    if provider_type == "google":
        from app.ai.chat_models import discover_google_models

        discovered = await discover_google_models(api_key, base_url)
        return [
            RemoteModel(external_id=item["id"], caps=tuple(infer_caps(item["id"])))
            for item in discovered
            if item.get("id")
        ]
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    url = f"{base_url.rstrip('/')}/models"
    async with httpx.AsyncClient(transport=transport, timeout=FETCH_TIMEOUT_SECONDS) as client:
        response = await client.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()
    return [
        RemoteModel(external_id=item["id"], caps=tuple(infer_caps(item["id"])))
        for item in data.get("data", [])
        if item.get("id")
    ]


async def _resolve_target_row(
    db: AsyncSession, preset_key: str, preset: dict[str, Any], scope: str, user_id: UUID | None
) -> AIProvider | None:
    """Scope-local adoption target: stamped rows first, then matching
    manual rows (earliest first) at the same scope."""
    stamped = await db.execute(
        select(AIProvider)
        .where(
            AIProvider.preset_key == preset_key,
            AIProvider.scope == scope,
            AIProvider.user_id == (user_id if scope == "user" else None),
        )
        .order_by(AIProvider.created_at, AIProvider.id)
        .limit(1)
    )
    existing = stamped.scalars().first()
    if existing is not None:
        return existing
    manual = await db.execute(
        select(AIProvider)
        .where(
            AIProvider.preset_key.is_(None),
            AIProvider.scope == scope,
            AIProvider.user_id == (user_id if scope == "user" else None),
            AIProvider.provider_type == preset["type"],
            AIProvider.api_base == preset["base_url"],
        )
        .order_by(AIProvider.created_at, AIProvider.id)
        .limit(1)
    )
    return manual.scalars().first()


async def _upsert_persisted_models(
    db: AsyncSession, provider: AIProvider, persist_catalog: list[_PersistedModel]
) -> dict[str, AIModel]:
    rows = await db.execute(select(AIModel).where(AIModel.provider_id == provider.id))
    existing = {model.model_name: model for model in rows.scalars()}
    persisted: dict[str, AIModel] = {}
    for item in persist_catalog:
        model = existing.get(item.model_name)
        if model is None:
            model = AIModel(
                provider_id=provider.id,
                name=item.model_name,
                model_name=item.model_name,
                caps=list(item.caps),
                is_active=True,
            )
            db.add(model)
            await db.flush()
        elif not model.caps:
            model.caps = list(item.caps)
        persisted[item.model_name] = model
    return persisted


def _match_curated(model_name: str, curated: list[str]) -> str | None:
    for curated_id in curated:
        if model_name == curated_id or model_name.startswith(f"{curated_id}-"):
            return curated_id
    return None


def _decision_model_specs(preset: dict[str, Any]) -> list[dict[str, Any]]:
    models = preset.get("decision_models") or []
    return [dict(entry) for entry in models]


async def _upsert_decision_models(
    db: AsyncSession, provider: AIProvider, specs: list[dict[str, Any]]
) -> dict[str, AIModel]:
    persisted: dict[str, AIModel] = {}
    rows = await db.execute(select(AIModel).where(AIModel.provider_id == provider.id))
    existing = {model.model_name: model for model in rows.scalars()}
    for entry in specs:
        external_id = str(entry["id"])
        transport = str(entry.get("transport") or "systemone")
        model = existing.get(external_id)
        if model is None:
            model = AIModel(
                provider_id=provider.id,
                name=str(entry.get("name") or external_id),
                model_name=external_id,
                caps=["decision"],
                decision_transport=transport,
                is_active=True,
            )
            db.add(model)
            await db.flush()
        else:
            model.caps = list(dict.fromkeys([*(model.caps or []), "decision"]))
            model.decision_transport = transport
            model.is_active = True
        persisted[external_id] = model
    return persisted


def _probe_error(result: DecisionProbeResult) -> Exception:
    """Rebuild an exception the shared classifier understands."""
    if result.kind == "timeout":
        return httpx.ReadTimeout(result.error or "decision probe timed out")
    if result.status is not None:
        request = httpx.Request("POST", "https://probe.invalid")
        response = httpx.Response(
            result.status, request=request, text=result.error or "decision probe failed"
        )
        return httpx.HTTPStatusError(
            f"Client error {result.status}", request=request, response=response
        )
    return RuntimeError(result.error or "decision probe failed")


async def setup_provider_from_preset(
    db: AsyncSession,
    user: User,
    preset_key: str,
    api_key: str | None,
    *,
    name: str | None = None,
    scope: str = "user",
    options: SetupOptions | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> SetupOutcome:
    """Run one-click setup for a canonical preset at the caller's scope.

    USER scope is the default; SYSTEM requires the caller to be an
    admin. Every write (adoption, catalog, key, gap-fill) stays strictly
    inside that scope.
    """
    if scope == "system" and not user.is_admin:
        from app.core.errors import PermissionDeniedError

        raise PermissionDeniedError("Only admins can set up global providers")
    options = options or SetupOptions()
    preset = ALL_PRESETS.get(preset_key)
    if preset is None:
        raise UnknownPresetError(f"unknown provider preset '{preset_key}'")

    decision_only = preset["type"] == "decision"
    user_id = user.id if scope == "user" else None
    existing = await _resolve_target_row(db, preset_key, preset, scope, user_id)
    key = "" if (preset["local"] and not decision_only) else (api_key or "").strip()
    if not key and existing is not None:
        key = existing.api_key or ""

    if existing is not None:
        existing.provider_type = preset["type"]
        existing.api_base = preset["base_url"]
        provider = existing
    else:
        provider = AIProvider(
            name=(name or "").strip() or preset["name"],
            scope=scope,
            user_id=user_id,
            provider_type=preset["type"],
            api_base=preset["base_url"],
            api_key_encrypted=encrypt_secret(None),
            is_local=preset["local"],
        )
        db.add(provider)
        await db.flush()
    provider.preset_key = preset_key
    await db.flush()

    decision_specs = _decision_model_specs(preset)
    catalog: list[_PersistedModel] = []
    try:
        if decision_only:
            # §15 single-source: the probe id derives from the synced
            # canonical preset data (specs → decision_default), never a
            # code literal.
            probe_id = decision_probe_model_id(preset)
            probe_model = AIModel(
                provider_id=provider.id,
                name=probe_id,
                model_name=probe_id,
                caps=["decision"],
                decision_transport="systemone",
            )
            result = await probe_decision_provider(
                DecisionProbeInput(
                    provider=provider, model=probe_model, api_key=key, transport=transport
                )
            )
            if not result.ok:
                raise _probe_error(result) from None
        else:
            for remote in await fetch_remote_models(
                preset["type"], provider.api_base, key or None, transport=transport
            ):
                catalog.append(
                    _PersistedModel(model_name=remote.external_id, caps=list(remote.caps))
                )
    except Exception as error:
        classified = classify_provider_error(
            error,
            local_provider=bool(preset["local"]),
            api_key=key or None,
            attempted_preset=preset_key,
        )
        await db.rollback()
        raise SetupError(classified, str(error)[:300]) from error

    use_preset_curated = options.curated_ids is None
    curated = preset["curated_models"] if use_preset_curated else options.curated_ids
    curated = curated or []
    persist_catalog = catalog
    for item in persist_catalog:
        if not item.caps:
            item.caps = infer_caps(item.model_name)

    def curated_match(item: _PersistedModel) -> str | None:
        return _match_curated(item.model_name, curated)

    any_curated_match = any(curated_match(item) is not None for item in persist_catalog)
    if curated:
        if any_curated_match:
            persist_catalog = [item for item in persist_catalog if curated_match(item)]
        elif not use_preset_curated:
            persist_catalog = []
    elif not use_preset_curated:
        persist_catalog = []
    curated_missed = bool(use_preset_curated and curated and not any_curated_match)

    by_wire_id = await _upsert_persisted_models(db, provider, persist_catalog)
    if key:
        provider.api_key_encrypted = encrypt_secret(key)
    await db.flush()

    assigned_chat: str | None = None
    assigned_vision: str | None = None
    assigned_stt: str | None = None
    assigned_embeddings: str | None = None

    preferred = preset["preferred_model"]
    preferred_model_id = preferred["id"] if preferred else None
    preferred_resolved_id = None
    if preferred_model_id:
        preferred_resolved_id = next(
            (
                item.model_name
                for item in persist_catalog
                if item.model_name == preferred_model_id
                or _match_curated(item.model_name, curated) == preferred_model_id
            ),
            None,
        )
    fallback_candidate_id = next(
        (
            item.model_name
            for curated_id in curated
            for item in persist_catalog
            if _match_curated(item.model_name, curated) == curated_id
        ),
        None,
    )
    assignment_candidate_id = preferred_resolved_id or fallback_candidate_id
    if preferred_resolved_id:
        assignment_vision_capable = bool(preferred and "vision" in (preferred.get("caps") or []))
    elif assignment_candidate_id:
        assignment_vision_capable = "vision" in (by_wire_id[assignment_candidate_id].caps or [])
    else:
        assignment_vision_capable = False

    chat_row, chat_model = await _slot_alive(db, "text", scope, user_id)
    vision_candidate_id: str | None = None
    vision_capable_flag = False
    chat_wire_id = chat_model.model_name if chat_model is not None else None
    if (
        chat_wire_id
        and chat_wire_id in by_wire_id
        and "vision" in (by_wire_id[chat_wire_id].caps or [])
    ):
        vision_candidate_id = chat_wire_id
        vision_capable_flag = True
    if vision_candidate_id is None and assignment_candidate_id:
        vision_candidate_id = assignment_candidate_id
        vision_capable_flag = assignment_vision_capable

    if options.bind_chat and assignment_candidate_id and chat_model is None:
        assigned_chat = assignment_candidate_id
        await _bind_slot(
            db, chat_row, "text", scope, user_id, provider, by_wire_id[assignment_candidate_id]
        )
    if options.bind_vision and vision_candidate_id and vision_capable_flag:
        vision_row, vision_model = await _slot_alive(db, "vision", scope, user_id)
        if vision_model is None:
            assigned_vision = vision_candidate_id
            await _bind_slot(
                db, vision_row, "vision", scope, user_id, provider, by_wire_id[vision_candidate_id]
            )

    stt_model_id = preset["stt_model"]
    stt_resolved_id = None
    if stt_model_id:
        stt_resolved_id = next(
            (
                item.model_name
                for item in persist_catalog
                if item.model_name == stt_model_id
                or _match_curated(item.model_name, curated) == stt_model_id
            ),
            None,
        )
    if options.bind_stt and stt_resolved_id:
        stt_row, stt_model = await _slot_alive(db, "stt", scope, user_id)
        if stt_model is None:
            assigned_stt = stt_resolved_id
            await _bind_slot(
                db, stt_row, "stt", scope, user_id, provider, by_wire_id[stt_resolved_id]
            )

    embeddings_model_id = preset["embeddings_model"]
    embeddings_resolved_id = None
    if embeddings_model_id:
        embeddings_resolved_id = next(
            (
                item.model_name
                for item in persist_catalog
                if item.model_name == embeddings_model_id
                or _match_curated(item.model_name, curated) == embeddings_model_id
            ),
            None,
        )
    if options.bind_embeddings and embeddings_resolved_id:
        embeddings_row, embeddings_model = await _slot_alive(db, "embeddings", scope, user_id)
        if embeddings_model is None:
            assigned_embeddings = embeddings_resolved_id
            await _bind_slot(
                db,
                embeddings_row,
                "embeddings",
                scope,
                user_id,
                provider,
                by_wire_id[embeddings_resolved_id],
            )

    decision_rows: dict[str, AIModel] = {}
    if decision_specs:
        decision_rows = await _upsert_decision_models(db, provider, decision_specs)
        await db.flush()

    assigned_decision: dict[str, str] = {}
    decision_default = preset.get("decision_default")
    if options.bind_decision and decision_rows and decision_default:
        candidate = decision_rows.get(str(decision_default))
        if candidate is None:
            candidate = next(iter(decision_rows.values()))
        # ADR-0036 §3: setup binds the `decision` default slot only — one
        # assignment, one review row; kind slots inherit.
        row, live_model = await _slot_alive(db, DECISION_DEFAULT_TASK_TYPE, scope, user_id)
        if live_model is None:
            assigned_decision[DECISION_DEFAULT_TASK_TYPE] = candidate.model_name
            await _bind_slot(
                db, row, DECISION_DEFAULT_TASK_TYPE, scope, user_id, provider, candidate
            )
        if assigned_decision:
            await db.flush()

    return SetupOutcome(
        provider_id=provider.id,
        catalog_count=len(persist_catalog) + len(decision_rows),
        curated_missed=curated_missed,
        assigned_chat_model=assigned_chat,
        assigned_vision_model=assigned_vision,
        assigned_stt_model=assigned_stt,
        assigned_embeddings_model=assigned_embeddings,
        assigned_decision_slots=assigned_decision or None,
    )


async def _slot_alive(
    db: AsyncSession, task_type: str, scope: str, user_id: UUID | None
) -> tuple[AITaskAssignment, AIModel | None]:
    """The slot's row and its LIVE model — a dead/inactive binding counts
    as empty (gap-fill may rebind it)."""
    rows = await db.execute(
        select(AITaskAssignment).where(
            AITaskAssignment.task_type == task_type,
            AITaskAssignment.scope == scope,
            AITaskAssignment.user_id == (user_id if scope == "user" else None),
        )
    )
    row = rows.scalars().first()
    if row is None:
        row = AITaskAssignment(
            task_type=task_type,
            scope=scope,
            user_id=user_id if scope == "user" else None,
        )
        db.add(row)
        await db.flush()
        return row, None
    if row.model_id is None:
        return row, None
    model_rows = await db.execute(select(AIModel).where(AIModel.id == row.model_id))
    model = model_rows.scalars().first()
    if model is None or not model.is_active:
        return row, None
    provider_rows = await db.execute(select(AIProvider).where(AIProvider.id == model.provider_id))
    provider = provider_rows.scalars().first()
    if provider is None or not provider.is_active:
        return row, None
    return row, model


async def _bind_slot(
    db: AsyncSession,
    row: AITaskAssignment,
    task_type: str,
    scope: str,
    user_id: UUID | None,
    provider: AIProvider,
    model: AIModel,
) -> None:
    row.provider_id = provider.id
    row.model_id = model.id
    row.tier = None
    row.is_active = True
    await db.flush()


async def set_default_model(
    db: AsyncSession,
    user: User,
    *,
    provider_id: UUID,
    model_name: str,
    task: str = "chat",
    scope: str = "user",
) -> AIModel:
    """Bind a provider's model as the default for one task (scope-aware).

    Creates the model row on the provider when it does not exist yet
    (capability-inferred; decision providers get the decision cap +
    transport), enforces the D4 slot-separation guard, and rejects a
    model name that already belongs to another provider (409 at the
    API layer).
    """
    from app.ai.providers.resolution import known_task_types
    from app.ai.providers.service import _check_assignment_capability

    if scope == "system" and not user.is_admin:
        from app.core.errors import PermissionDeniedError

        raise PermissionDeniedError("Only admins can change global defaults")
    task_info = next((t for t in known_task_types() if t["value"] == task), None)
    if task_info is None:
        from app.core.errors import ValidationError

        raise ValidationError(f"Unknown task type: {task}")
    provider_rows = await db.execute(select(AIProvider).where(AIProvider.id == provider_id))
    provider = provider_rows.scalars().first()
    if provider is None:
        from app.core.errors import ValidationError

        raise ValidationError("Provider not found")
    if provider.scope != scope or (scope == "user" and provider.user_id != user.id):
        from app.core.errors import PermissionDeniedError

        raise PermissionDeniedError("Provider belongs to another scope")
    model_name = model_name.strip()
    if not model_name:
        from app.core.errors import ValidationError

        raise ValidationError("model_name is required")

    rows = await db.execute(
        select(AIModel).where(AIModel.provider_id == provider_id, AIModel.model_name == model_name)
    )
    model = rows.scalars().first()
    if model is None:
        elsewhere = await db.execute(select(AIModel).where(AIModel.model_name == model_name))
        if elsewhere.scalars().first() is not None:
            raise CrossProviderModelError(f"model '{model_name}' belongs to another provider")
        decision_provider = provider.provider_type == "decision"
        model = AIModel(
            provider_id=provider_id,
            name=model_name,
            model_name=model_name,
            caps=["decision"] if decision_provider else infer_caps(model_name),
            decision_transport="systemone" if decision_provider else None,
            is_active=True,
        )
        db.add(model)
        await db.flush()
    await _check_assignment_capability(db, model, task, task_info.get("requires"))

    user_id = user.id if scope == "user" else None
    assignment_rows = await db.execute(
        select(AITaskAssignment).where(
            AITaskAssignment.task_type == task,
            AITaskAssignment.scope == scope,
            AITaskAssignment.user_id == user_id,
        )
    )
    assignment = assignment_rows.scalars().first()
    if assignment is None:
        assignment = AITaskAssignment(task_type=task, scope=scope, user_id=user_id)
        db.add(assignment)
    assignment.provider_id = provider.id
    assignment.model_id = model.id
    assignment.tier = None
    assignment.is_active = True
    await db.flush()
    return model
