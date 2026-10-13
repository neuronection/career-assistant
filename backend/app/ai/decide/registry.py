"""Decision transport registry (ADR-0019/0020 + ADR-0032 D6).

One registration per transport (``resolve/create/audit/probe``); callers
never switch on engine kind. Resolution reads the ``decision_*``
assignment rows — the caller's own row first, then the system row (the
scope chain is career's primary → fallback chain) — then routes by the
transport's declared capability matrix (D2b). ``off`` is a resolution
result, never an error.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_provider_model import AIModel, AIProvider, AITaskAssignment
from app.models.user_model import User

from .systemone.client import SystemOneClient, resolve_systemone_base_url
from .systemone.engine import SystemOneDecisionEngine, SystemOneEngineParams
from .systemone.probe import DecisionProbeInput, DecisionProbeResult, probe_decision_provider
from .types import (
    SYSTEMONE_DECISION_CAPS,
    DecisionCapability,
    DecisionEngine,
    DecisionTransport,
    decision_slot_for_task,
)


@dataclass
class DecisionEngineDeps:
    """Call seams: the request's user, a client/transport override for
    tests, and hooks (audit identity, cache revision, pin observation)."""

    db: AsyncSession
    user: User | None = None
    get_api_key: Callable[[AIProvider], str | None] | None = None
    config_revision: Callable[[AsyncSession], Awaitable[str]] | None = None
    observe_resolved_model: Callable[[str, str], None] | None = None
    client: SystemOneClient | None = None
    transport: object | None = None

    def api_key_of(self, provider: AIProvider) -> str | None:
        if self.get_api_key is not None:
            return self.get_api_key(provider)
        return provider.api_key


@dataclass(frozen=True)
class OffResolution:
    kind = "off"


@dataclass(frozen=True)
class UnconfiguredResolution:
    kind = "unconfigured"
    reason: str


@dataclass(frozen=True)
class UnavailableResolution:
    kind = "unavailable"
    reason: str
    code: str | None = None
    provider_id: UUID | None = None


@dataclass(frozen=True)
class SystemOneResolution:
    kind = "systemone"
    provider: AIProvider
    model: AIModel
    api_key: str
    base_url: str


DecisionResolution = (
    OffResolution | UnconfiguredResolution | UnavailableResolution | SystemOneResolution
)


@dataclass(frozen=True)
class AuditMeta:
    provider_id: UUID | None
    model: str


@dataclass(frozen=True)
class DecisionTransportRegistration:
    transport: DecisionTransport
    capabilities: frozenset[DecisionCapability]
    display_name: str
    resolve_candidate: Callable[[AIProvider, AIModel, DecisionEngineDeps], DecisionResolution]
    create: Callable[[DecisionResolution, DecisionEngineDeps], DecisionEngine]
    audit: Callable[[DecisionResolution], AuditMeta | None]
    probe: Callable[[DecisionProbeInput], Awaitable[DecisionProbeResult]]


def _resolve_systemone_candidate(
    provider: AIProvider, model: AIModel, deps: DecisionEngineDeps
) -> DecisionResolution:
    base_url = resolve_systemone_base_url(provider, model)
    if base_url is None:
        return UnavailableResolution(reason="The provider base URL is missing or invalid.")
    api_key = deps.api_key_of(provider)
    if not api_key:
        return UnavailableResolution(
            reason="No API key is set for the decision provider.",
            code="needs-key",
            provider_id=provider.id,
        )
    return SystemOneResolution(provider=provider, model=model, api_key=api_key, base_url=base_url)


def _create_systemone(resolution: DecisionResolution, deps: DecisionEngineDeps) -> DecisionEngine:
    if not isinstance(resolution, SystemOneResolution):
        raise ValueError("systemone registration received a non-systemone resolution")
    return SystemOneDecisionEngine(
        SystemOneEngineParams(
            api_key=resolution.api_key,
            base_url=resolution.base_url,
            model=resolution.model.model_name,
            client=deps.client,
            transport=deps.transport,
        )
    )


def _audit_systemone(resolution: DecisionResolution) -> AuditMeta | None:
    if not isinstance(resolution, SystemOneResolution):
        return None
    return AuditMeta(provider_id=resolution.provider.id, model=resolution.model.model_name)


SYSTEMONE_REGISTRATION = DecisionTransportRegistration(
    transport=DecisionTransport.SYSTEMONE,
    capabilities=frozenset(SYSTEMONE_DECISION_CAPS),
    display_name="TypeSafe System One",
    resolve_candidate=_resolve_systemone_candidate,
    create=_create_systemone,
    audit=_audit_systemone,
    probe=probe_decision_provider,
)

REGISTRATIONS: dict[DecisionTransport, DecisionTransportRegistration] = {
    DecisionTransport.SYSTEMONE: SYSTEMONE_REGISTRATION,
}


def get_decision_transport_registration(
    transport: DecisionTransport,
) -> DecisionTransportRegistration:
    return REGISTRATIONS[transport]


def decision_transport_capabilities(
    transport: DecisionTransport,
) -> frozenset[DecisionCapability]:
    return REGISTRATIONS[transport].capabilities


def decision_transport_display_name(transport: DecisionTransport) -> str:
    return REGISTRATIONS[transport].display_name


def decision_transport_of(provider: AIProvider, model: AIModel) -> DecisionTransport | None:
    if model.decision_transport:
        try:
            return DecisionTransport(model.decision_transport)
        except ValueError:
            return None
    if provider.provider_type == "decision":
        return DecisionTransport.SYSTEMONE
    return None


DECISION_TASK_TYPES: tuple[str, ...] = (
    "decision_tool_dispatch",
    "decision_boolean_gate",
    "decision_choice",
    "decision_score",
)


async def _assigned_candidates(
    db: AsyncSession, capability: DecisionCapability, user_id: UUID | None
) -> list[AITaskAssignment]:
    """The slot's rows, primary (the caller's own) before the system row —
    the scope chain is the fallback chain."""
    wanted = [
        task
        for task in DECISION_TASK_TYPES
        if decision_slot_for_task(task) == f"decision:{capability.value}"
    ]
    if not wanted:
        return []
    rows = await db.execute(
        select(AITaskAssignment)
        .where(
            AITaskAssignment.task_type == wanted[0],
            AITaskAssignment.is_active.is_(True),
            AITaskAssignment.model_id.is_not(None),
        )
        .order_by(AITaskAssignment.created_at)
    )
    all_rows = list(rows.scalars())
    scoped: list[AITaskAssignment] = []
    for row in all_rows:
        if user_id is not None and row.scope == "user" and row.user_id == user_id:
            scoped.append(row)
    system_rows = [row for row in all_rows if row.scope == "system"]
    seen: set[UUID] = set()
    candidates: list[AITaskAssignment] = []
    for row in [*scoped, *system_rows]:
        if row.id in seen:
            continue
        seen.add(row.id)
        candidates.append(row)
    return candidates


async def default_config_revision(db: AsyncSession) -> str:
    """Stateless fingerprint of the decision slot rows + referenced
    models/providers — survives multi-process web mode (study's
    adaptation of desktop's per-config counter)."""
    parts: list[str] = []
    for task_type in DECISION_TASK_TYPES:
        slot = decision_slot_for_task(task_type) or task_type
        rows = await db.execute(
            select(AITaskAssignment).where(AITaskAssignment.task_type == task_type)
        )
        entries: list[str] = []
        for row in rows.scalars():
            model_id = row.model_id
            if model_id is None:
                entries.append("none")
                continue
            model = (
                (await db.execute(select(AIModel).where(AIModel.id == model_id))).scalars().first()
            )
            if model is None:
                entries.append("dead")
                continue
            provider = (
                (await db.execute(select(AIProvider).where(AIProvider.id == model.provider_id)))
                .scalars()
                .first()
            )
            entries.append(
                ":".join(
                    str(value)
                    for value in (
                        str(model.id),
                        int(model.is_active),
                        model.decision_transport or "-",
                        int(provider.is_active) if provider is not None else "-",
                    )
                )
            )
        parts.append(f"{slot}={','.join(entries)}")
    return ";".join(parts)


_RESOLUTION_CACHE: dict[str, tuple[str, DecisionResolution]] = {}


def clear_decision_resolution_cache() -> None:
    _RESOLUTION_CACHE.clear()


async def _compute_resolution(
    capability: DecisionCapability, db: AsyncSession, deps: DecisionEngineDeps
) -> DecisionResolution:
    user_id = deps.user.id if deps.user is not None else None
    candidates = await _assigned_candidates(db, capability, user_id)
    if not candidates:
        return OffResolution()
    rejections: list[str] = []
    last_index = len(candidates) - 1
    for index, row in enumerate(candidates):
        model_id = row.model_id
        assert model_id is not None
        model = (await db.execute(select(AIModel).where(AIModel.id == model_id))).scalars().first()
        if model is None or not model.is_active:
            rejections.append(f"Model '{model_id}' is not registered or inactive.")
            continue
        provider = (
            (await db.execute(select(AIProvider).where(AIProvider.id == model.provider_id)))
            .scalars()
            .first()
        )
        if provider is None or not provider.is_active:
            rejections.append(f"Model '{model.model_name}' has no active provider.")
            continue
        transport = decision_transport_of(provider, model)
        is_decision_model = "decision" in (model.caps or [])
        if transport is None or not is_decision_model:
            rejections.append(f"Model '{model.model_name}' is not a decision model.")
            continue
        registration = REGISTRATIONS[transport]
        if capability not in registration.capabilities:
            rejections.append(
                f"The transport of '{model.model_name}' does not serve decision:{capability.value}."
            )
            continue
        resolution = registration.resolve_candidate(provider, model, deps)
        if isinstance(resolution, UnavailableResolution) and index != last_index:
            rejections.append(resolution.reason)
            continue
        return resolution
    return UnconfiguredResolution(
        reason=rejections[0] if rejections else "No decision model is assigned."
    )


async def resolve_decision(
    capability: DecisionCapability,
    db: AsyncSession,
    deps: DecisionEngineDeps | None = None,
) -> DecisionResolution:
    deps = deps or DecisionEngineDeps(db=db)
    revision_source = deps.config_revision or default_config_revision
    revision = await revision_source(db)
    cached = _RESOLUTION_CACHE.get(capability.value)
    if cached is not None and cached[0] == revision:
        return cached[1]
    resolution = await _compute_resolution(capability, db, deps)
    _RESOLUTION_CACHE[capability.value] = (revision, resolution)
    return resolution


def engine_readiness(resolution: DecisionResolution) -> dict[str, str | None]:
    if isinstance(resolution, SystemOneResolution):
        return {"state": "ready", "reason": None}
    if isinstance(resolution, OffResolution):
        return {"state": "unavailable", "reason": "No decision model is assigned."}
    if isinstance(resolution, UnavailableResolution) and resolution.code == "needs-key":
        return {
            "state": "needs-key",
            "reason": f"provider:{resolution.provider_id or ''}",
        }
    if isinstance(resolution, UnavailableResolution):
        return {"state": "unavailable", "reason": resolution.reason}
    assert isinstance(resolution, UnconfiguredResolution)
    return {"state": "unavailable", "reason": resolution.reason}
