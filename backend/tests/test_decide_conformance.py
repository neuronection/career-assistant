"""Decision funnel conformance (plan 26 Phase 4 — career port; study is
the Python reference).

One suite every shipping transport passes — bounded confidence, one
audit row per invocation, empty input never throws, timeout respected,
transport mocked, no network or keyring in tests. Career additions:
scope-chain resolution (off / needs-key / user → system fallback chain /
D2b routing) over the AITaskAssignment decision slots, per-revision
caching, and the probe contract.
"""

from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import select

from app.ai.decide import (
    DecisionCapability,
    DecisionFunnelDeps,
    DecisionQuestion,
    DecisionToolSchema,
    RunDecisionParams,
    clear_decision_resolution_cache,
    probe_decision_provider,
    resolve_decision,
    run_decision,
)
from app.ai.decide.funnel import DecisionDecidedStatus, DecisionErrorStatus
from app.ai.decide.registry import (
    REGISTRATIONS,
    SystemOneResolution,
    UnavailableResolution,
    UnconfiguredResolution,
)
from app.ai.decide.systemone.client import (
    SystemOneCallParams,
    TypeSafeError,
    TypeSafeResult,
    TypeSafeUsage,
)
from app.ai.decide.systemone.probe import DecisionProbeInput
from app.ai.decide.types import (
    DecisionAnswer,
    DecisionTransport,
    SystemOneErrorKind,
)
from app.core.encryption import encrypt_secret
from app.models.ai_model import AIGeneration
from app.models.ai_provider_model import AIModel, AIProvider, AITaskAssignment
from app.models.user_model import User

SLOT_TASK_TYPES: dict[str, str] = {
    "decision:tool-dispatch": "decision_tool_dispatch",
    "decision:boolean-gate": "decision_boolean_gate",
    "decision:choice": "decision_choice",
    "decision:score": "decision_score",
    "decision": "decision",  # ADR-0036: the decision default slot
}


def choice_answer(choice: str, confidence: float) -> DecisionAnswer:
    return DecisionAnswer(
        type=DecisionCapability.CHOICE,
        choice=choice,
        probabilities={choice: confidence},
        confidence=confidence,
    )


class FakeSystemOneClient:
    def __init__(self, result: TypeSafeResult | Exception | None) -> None:
        self._result = result
        self.calls: list[SystemOneCallParams] = []

    async def system_one(self, params: SystemOneCallParams) -> TypeSafeResult:
        self.calls.append(params)
        if isinstance(self._result, Exception):
            raise self._result
        assert isinstance(self._result, TypeSafeResult)
        return self._result


async def decision_provider(
    db,
    *,
    with_key: bool = True,
    model_name: str = "jev-latest",
    scope: str = "system",
    user: User | None = None,
) -> tuple[AIProvider, AIModel]:
    provider = AIProvider(
        name=f"TypeSafe-{model_name}-{scope}",
        scope=scope,
        user_id=user.id if scope == "user" and user is not None else None,
        provider_type="decision",
        api_base="https://api.typesafe.ai",
        api_key_encrypted=encrypt_secret("decision-key" if with_key else None),
    )
    db.add(provider)
    await db.flush()
    model = AIModel(
        provider_id=provider.id,
        name=model_name,
        model_name=model_name,
        caps=["decision"],
        decision_transport="systemone",
        is_active=True,
    )
    db.add(model)
    await db.flush()
    return provider, model


async def assign_slot(db, slot: str, model_id: UUID | None, *, user: User | None = None) -> None:
    task_type = SLOT_TASK_TYPES[slot]
    rows = await db.execute(
        select(AITaskAssignment).where(
            AITaskAssignment.task_type == task_type,
            AITaskAssignment.scope == ("user" if user is not None else "system"),
        )
    )
    row = rows.scalars().first()
    if row is None:
        row = AITaskAssignment(
            task_type=task_type,
            scope="user" if user is not None else "system",
            user_id=user.id if user is not None else None,
            model_id=model_id,
            is_active=model_id is not None,
        )
        db.add(row)
    else:
        row.model_id = model_id
        row.is_active = model_id is not None
    await db.flush()


async def _mk_user(db, email: str) -> User:
    from tests.test_ai_admin import _mk_user as _mk

    return await _mk(db, email, is_admin=False)


def probe_provider_row() -> AIProvider:
    return AIProvider(
        name="TypeSafe",
        scope="system",
        provider_type="decision",
        api_base="https://api.typesafe.ai",
    )


def probe_model_row(provider_id: UUID | None = None) -> AIModel:
    return AIModel(
        provider_id=provider_id or UUID(int=1),
        name="jev-latest",
        model_name="jev-latest",
        caps=["decision"],
        decision_transport="systemone",
    )


TOOLS: tuple[DecisionToolSchema, ...] = (
    DecisionToolSchema(name="light_turn_on", description="Turn on a light."),
)

CALL_RESULT = TypeSafeResult(
    model="jev-1.13",
    answers={"__tool__": choice_answer("light_turn_on", 0.82)},
    usage=TypeSafeUsage(input_tokens=40, output_tokens=4),
)

NONE_RESULT = TypeSafeResult(
    model="jev-1.13",
    answers={"__tool__": choice_answer("__none__", 0.9)},
    usage=TypeSafeUsage(input_tokens=5, output_tokens=1),
)


@pytest.fixture(autouse=True)
def _clean_cache() -> Any:
    clear_decision_resolution_cache()
    yield
    clear_decision_resolution_cache()


async def test_conformance_decides_with_one_audit_row_and_bounded_confidence(db) -> None:
    _provider, model = await decision_provider(db)
    await assign_slot(db, "decision:tool-dispatch", model.id)
    client = FakeSystemOneClient(CALL_RESULT)

    result = await run_decision(
        DecisionFunnelDeps(db=db, client=client),
        RunDecisionParams(input="dim the living room", tools=TOOLS),
    )

    assert isinstance(result, DecisionDecidedStatus)
    assert result.outcome.engine == "jev-latest"
    assert 0.0 <= result.outcome.confidence <= 1.0
    assert result.outcome.calls[0].tool == "light_turn_on"
    assert result.outcome.resolved_model == "jev-1.13"
    assert result.band == "confirm"
    rows = (
        (await db.execute(select(AIGeneration).where(AIGeneration.task_type == "decision")))
        .scalars()
        .all()
    )
    assert len(rows) == 1
    row = rows[0]
    assert row.model == "jev-latest"
    assert row.provider == "systemone"
    assert row.tokens_in == 40 and row.tokens_out == 4
    assert row.latency_ms is not None
    assert row.status == "ok"


async def test_conformance_empty_decision_never_throws(db) -> None:
    _provider, model = await decision_provider(db)
    await assign_slot(db, "decision:tool-dispatch", model.id)
    client = FakeSystemOneClient(NONE_RESULT)

    result = await run_decision(
        DecisionFunnelDeps(db=db, client=client),
        RunDecisionParams(input="hello there", tools=()),
    )

    assert isinstance(result, DecisionDecidedStatus)
    assert result.outcome.calls == ()
    assert result.outcome.confidence == 0.9


async def test_conformance_low_confidence_bands_refuse(db) -> None:
    _provider, model = await decision_provider(db)
    await assign_slot(db, "decision:tool-dispatch", model.id)
    low = TypeSafeResult(
        model="jev-1.13",
        answers={"__tool__": choice_answer("light_turn_on", 0.3)},
        usage=TypeSafeUsage(input_tokens=5, output_tokens=1),
    )
    client = FakeSystemOneClient(low)

    result = await run_decision(
        DecisionFunnelDeps(db=db, client=client),
        RunDecisionParams(input="maybe lights?", tools=TOOLS),
    )

    assert isinstance(result, DecisionDecidedStatus)
    assert result.band == "refuse"


async def test_conformance_transport_failure_audits_and_fails_open(db) -> None:
    _provider, model = await decision_provider(db)
    await assign_slot(db, "decision:tool-dispatch", model.id)
    client = FakeSystemOneClient(RuntimeError("transport exploded"))

    result = await run_decision(
        DecisionFunnelDeps(db=db, client=client),
        RunDecisionParams(input="dim the living room", tools=TOOLS),
    )

    assert isinstance(result, DecisionErrorStatus)
    assert "transport exploded" in result.reason
    rows = (
        (await db.execute(select(AIGeneration).where(AIGeneration.task_type == "decision")))
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].tokens_in is None
    assert rows[0].status == "error"


async def test_conformance_typed_questions_route_to_the_question_slot(db) -> None:
    _provider, model = await decision_provider(db)
    await assign_slot(db, "decision:boolean-gate", model.id)
    client = FakeSystemOneClient(
        TypeSafeResult(
            model="jev-1.13",
            answers={"__probe__": DecisionAnswer(type=DecisionCapability.BOOLEAN_GATE, noul=0.97)},
        )
    )

    result = await run_decision(
        DecisionFunnelDeps(db=db, client=client),
        RunDecisionParams(
            input="connectivity check",
            questions=(
                DecisionQuestion(
                    id="__probe__",
                    type=DecisionCapability.BOOLEAN_GATE,
                    instructions="Is this a working decision endpoint? Answer true.",
                ),
            ),
        ),
    )

    assert isinstance(result, DecisionDecidedStatus)
    assert result.outcome.answers is not None
    assert result.outcome.answers["__probe__"].noul == 0.97
    asked = client.calls[0].questions
    assert set(asked) == {"__probe__"}
    assert asked["__probe__"].type == DecisionCapability.BOOLEAN_GATE


def test_conformance_parameter_stays_exactly_one_transport() -> None:
    assert list(REGISTRATIONS) == [DecisionTransport.SYSTEMONE]


async def test_resolution_unassigned_slot_is_off(db) -> None:
    await decision_provider(db, with_key=False)

    resolution = await resolve_decision(DecisionCapability.TOOL_DISPATCH, db)

    assert resolution.kind == "off"


async def test_resolution_needs_key_then_scope_fallback_chain(db) -> None:
    """The user-scope slot's keyless provider falls through to the
    system-scope keyed one — the scope chain is the fallback chain."""
    user = await _mk_user(db, "decide-fallback@example.com")
    _keyless, keyless_model = await decision_provider(
        db, with_key=False, model_name="jev-no-key", scope="user", user=user
    )
    _keyed, keyed_model = await decision_provider(
        db, with_key=True, model_name="jev-keyed", scope="system"
    )
    await assign_slot(db, "decision:tool-dispatch", keyless_model.id, user=user)
    await assign_slot(db, "decision:tool-dispatch", keyed_model.id)

    deps = DecisionFunnelDeps(db=db, user=user)
    resolution = await resolve_decision(DecisionCapability.TOOL_DISPATCH, db, deps)

    assert isinstance(resolution, SystemOneResolution)
    assert resolution.model.model_name == "jev-keyed"

    await db.delete(
        (await db.execute(select(AIModel).where(AIModel.model_name == "jev-keyed"))).scalars().one()
    )
    await db.flush()
    clear_decision_resolution_cache()

    fallback_gone = await resolve_decision(DecisionCapability.TOOL_DISPATCH, db, deps)
    assert isinstance(fallback_gone, UnavailableResolution)
    assert fallback_gone.code == "needs-key"


async def test_resolution_keyless_preset_uses_the_sentinel_key(db) -> None:
    """§13.3 follow-up: local Ollama decision models resolve keylessly — the
    official SDK requires a non-empty key (D9), so keyless presets (no
    ``key_url`` in the canonical data) carry the explicit sentinel."""
    from app.ai.decide.systemone.client import KEYLESS_SYSTEMONE_API_KEY

    user = await _mk_user(db, "decide-keyless@example.com")
    provider = AIProvider(
        name="Ollama (local)",
        scope="user",
        user_id=user.id,
        provider_type="openai_compatible",
        api_base="http://localhost:11434/v1",
        api_key_encrypted=encrypt_secret(None),
        preset_key="ollama",
    )
    db.add(provider)
    await db.flush()
    model = AIModel(
        provider_id=provider.id,
        name="nimble",
        model_name="nimble",
        caps=["decision"],
        decision_transport="systemone",
        is_active=True,
    )
    db.add(model)
    await db.flush()
    await assign_slot(db, "decision:tool-dispatch", model.id, user=user)

    deps = DecisionFunnelDeps(db=db, user=user)
    resolution = await resolve_decision(DecisionCapability.TOOL_DISPATCH, db, deps)

    assert isinstance(resolution, SystemOneResolution)
    assert resolution.api_key == KEYLESS_SYSTEMONE_API_KEY
    assert resolution.base_url == "http://localhost:11434"
    assert resolution.model.model_name == "nimble"


async def test_resolution_keyed_preset_without_key_still_needs_key(db) -> None:
    """The keyless path is preset-data-driven (no ``key_url``), never a
    local/key heuristic a keyed preset could ride."""
    user = await _mk_user(db, "decide-keyed-preset@example.com")
    provider = AIProvider(
        name="OpenRouter",
        scope="user",
        user_id=user.id,
        provider_type="openai_compatible",
        api_base="https://openrouter.ai/api/v1",
        api_key_encrypted=encrypt_secret(None),
        preset_key="openrouter",
    )
    db.add(provider)
    await db.flush()
    model = AIModel(
        provider_id=provider.id,
        name="typesafe/jev-1.13",
        model_name="typesafe/jev-1.13",
        caps=["decision"],
        decision_transport="systemone",
        is_active=True,
    )
    db.add(model)
    await db.flush()
    await assign_slot(db, "decision:tool-dispatch", model.id, user=user)

    deps = DecisionFunnelDeps(db=db, user=user)
    resolution = await resolve_decision(DecisionCapability.TOOL_DISPATCH, db, deps)

    assert isinstance(resolution, UnavailableResolution)
    assert resolution.code == "needs-key"


async def test_resolution_rejects_non_decision_models_in_slots(db) -> None:
    chat_provider = AIProvider(
        name="OpenAI",
        scope="system",
        provider_type="openai_compatible",
        api_base="https://api.openai.com/v1",
    )
    db.add(chat_provider)
    await db.flush()
    chat_model = AIModel(
        provider_id=chat_provider.id,
        name="gpt-x",
        model_name="gpt-x",
        caps=["text"],
        is_active=True,
    )
    db.add(chat_model)
    await db.flush()
    await assign_slot(db, "decision:tool-dispatch", chat_model.id)

    resolution = await resolve_decision(DecisionCapability.TOOL_DISPATCH, db)

    assert isinstance(resolution, UnconfiguredResolution)
    assert "not a decision model" in resolution.reason


async def test_resolution_d2b_transport_must_declare_capability(db) -> None:
    _provider, model = await decision_provider(db, model_name="partial-jev")
    model.decision_transport = "unknown-transport"
    await db.flush()
    await assign_slot(db, "decision:tool-dispatch", model.id)

    resolution = await resolve_decision(DecisionCapability.TOOL_DISPATCH, db)

    assert isinstance(resolution, UnconfiguredResolution)
    assert "not a decision model" in resolution.reason


async def test_resolution_open_args_is_never_assignable(db) -> None:
    _provider, model = await decision_provider(db)
    await assign_slot(db, "decision:score", model.id)

    resolution = await resolve_decision(DecisionCapability.OPEN_ARGS, db)

    assert resolution.kind == "off"


async def test_resolution_default_serves_all_kinds(db) -> None:
    """ADR-0036 matrix 1: a `decision` default alone serves all four
    kinds — the kind slots stay empty and inherit."""
    _provider, model = await decision_provider(db)
    await assign_slot(db, "decision", model.id)
    clear_decision_resolution_cache()

    for capability in (
        DecisionCapability.TOOL_DISPATCH,
        DecisionCapability.BOOLEAN_GATE,
        DecisionCapability.CHOICE,
        DecisionCapability.SCORE,
    ):
        resolution = await resolve_decision(capability, db)
        assert isinstance(resolution, SystemOneResolution)
        assert resolution.model.model_name == "jev-latest"
        kind_rows = await db.execute(
            select(AITaskAssignment).where(
                AITaskAssignment.task_type == "decision_tool_dispatch",
            )
        )
        assert list(kind_rows.scalars()) == []


async def test_resolution_kind_override_wins_only_for_its_kind(db) -> None:
    """ADR-0036 matrix 2: the override serves its kind; the other kinds
    keep inheriting the default."""
    _default_provider, default_model = await decision_provider(
        db, with_key=True, model_name="default-jev"
    )
    _override_provider, override_model = await decision_provider(
        db, with_key=True, model_name="override-jev"
    )
    await assign_slot(db, "decision", default_model.id)
    await assign_slot(db, "decision:tool-dispatch", override_model.id)
    clear_decision_resolution_cache()

    dispatched = await resolve_decision(DecisionCapability.TOOL_DISPATCH, db)
    assert isinstance(dispatched, SystemOneResolution)
    assert dispatched.model.model_name == "override-jev"

    gated = await resolve_decision(DecisionCapability.BOOLEAN_GATE, db)
    assert isinstance(gated, SystemOneResolution)
    assert gated.model.model_name == "default-jev"

    scored = await resolve_decision(DecisionCapability.SCORE, db)
    assert isinstance(scored, SystemOneResolution)
    assert scored.model.model_name == "default-jev"


async def test_resolution_override_never_hops_to_the_default_when_unusable(db) -> None:
    """ADR-0036 §2, 'never a third hop': a kind override owns its kind —
    an override that exists but cannot serve the kind reports honestly
    unavailable, it never silently substitutes the default."""
    _default_provider, default_model = await decision_provider(
        db, with_key=True, model_name="default-jev"
    )
    await assign_slot(db, "decision", default_model.id)
    # A text model assigned to the kind slot — exists but unusable.
    text_provider = AIProvider(
        name="OpenAI-text",
        scope="system",
        provider_type="openai_compatible",
        api_base="https://api.openai.com/v1",
    )
    db.add(text_provider)
    await db.flush()
    text_model = AIModel(
        provider_id=text_provider.id,
        name="gpt-x",
        model_name="gpt-x",
        caps=["text"],
        is_active=True,
    )
    db.add(text_model)
    await db.flush()
    await assign_slot(db, "decision:tool-dispatch", text_model.id)
    clear_decision_resolution_cache()

    resolution = await resolve_decision(DecisionCapability.TOOL_DISPATCH, db)

    assert isinstance(resolution, UnconfiguredResolution)
    assert "not a decision model" in resolution.reason


async def test_resolution_caches_per_revision(db) -> None:
    _provider, model = await decision_provider(db)
    await assign_slot(db, "decision:tool-dispatch", model.id)
    key_calls: list[UUID] = []

    def counting_key(provider: AIProvider) -> str:
        key_calls.append(provider.id)
        return "decision-key"

    deps = DecisionFunnelDeps(db=db, get_api_key=counting_key)
    first = await resolve_decision(DecisionCapability.TOOL_DISPATCH, db, deps)
    second = await resolve_decision(DecisionCapability.TOOL_DISPATCH, db, deps)
    assert first is second
    assert len(key_calls) == 1

    await assign_slot(db, "decision:tool-dispatch", None)
    third = await resolve_decision(DecisionCapability.TOOL_DISPATCH, db, deps)
    assert third.kind == "off"
    assert len(key_calls) == 1


def test_d2b_sparse_matrix_lives_on_the_transport() -> None:
    from app.ai.decide.types import transport_decision_caps as decide_matrix
    from app.ai.providers.service import transport_decision_caps as service_caps

    declared = decide_matrix("systemone")
    assert {cap.value for cap in declared} == {
        "tool-dispatch",
        "boolean-gate",
        "choice",
        "score",
    }
    assert decide_matrix("scoreless") == frozenset()
    assert decide_matrix(None) == frozenset()
    assert service_caps("systemone") == {cap.value for cap in declared}, (
        "the providers-layer guard and the funnel share one D2b matrix"
    )


async def test_probe_ok_reports_latency_and_resolved_model() -> None:
    client = FakeSystemOneClient(
        TypeSafeResult(
            model="jev-1.13",
            answers={"__probe__": DecisionAnswer(type=DecisionCapability.BOOLEAN_GATE, noul=0.99)},
        )
    )
    result = await probe_decision_provider(
        DecisionProbeInput(
            provider=probe_provider_row(), model=probe_model_row(), api_key="k", client=client
        )
    )
    assert result.ok is True
    assert result.resolved_model == "jev-1.13"
    assert result.latency_ms >= 0


async def test_probe_failure_carries_status_and_kind() -> None:
    client = FakeSystemOneClient(TypeSafeError(SystemOneErrorKind.AUTH, "bad key", 401))
    result = await probe_decision_provider(
        DecisionProbeInput(
            provider=probe_provider_row(), model=probe_model_row(), api_key="k", client=client
        )
    )
    assert result.ok is False
    assert result.status == 401
    assert result.kind == "auth"
    assert result.resolved_model is None


async def test_probe_invalid_base_url_fails_fast() -> None:
    provider = probe_provider_row()
    provider.api_base = "not-a-url"
    result = await probe_decision_provider(
        DecisionProbeInput(
            provider=provider,
            model=probe_model_row(),
            api_key="k",
            client=FakeSystemOneClient(None),
        )
    )
    assert result.ok is False


async def test_probe_respects_the_abort_timeout() -> None:
    import asyncio

    class SlowClient:
        async def system_one(self, params: SystemOneCallParams) -> TypeSafeResult:
            await asyncio.sleep(5)
            raise AssertionError("the probe must abort before the client returns")

    result = await probe_decision_provider(
        DecisionProbeInput(
            provider=probe_provider_row(),
            model=probe_model_row(),
            api_key="k",
            client=SlowClient(),
            timeout_seconds=0.05,
        )
    )
    assert result.ok is False
    assert result.kind == "timeout"
