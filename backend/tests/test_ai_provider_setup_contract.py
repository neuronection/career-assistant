"""Uniform BYOK contract-test matrix (family plan 17 Layer 4, §15; plan 26
Phase 4 — career port of the study 20-case reference + health's scope cases).

Case manifest (normative semantics, names indicative):

1.  happy path per preset — curated persisted, caps inferred, defaults bound;
2.  idempotent re-run appends the fetched catalog, never replaces, dedupes;
3.  manual-row adoption (earliest first) + preset_key stamp;
4.  never clobbers live assignments (chat/vision/stt);
5.  dead-id assignments rebind;
6.  invalid key → classified error, persists nothing;
7.  unknown preset → typed error, no fetch;
8.  hanging fetch → timeout; local refused → local_not_running;
9.  classifier table incl. suspectedVendor prefix hints;
10. snapshot-suffix curation match + zero-match fallback (curated_missed);
11. capability inference split (whisper-1 → stt; tts-* → tts);
12. set-default: task-scoped binding with capability guards + cross-provider
    rejection.
13. bind_decision capability-aware gap-fill (declared slots, never live);
14. bind_decision=false binds nothing;
15. live decision slots never clobbered (fill empty only);
16. decision-only preset (wire type `decision`) validates via the decision
    probe — ok path persists + binds, failure persists nothing;
17. probe timeout classifies `timeout`;
18. probe is no oracle without a valid key (401/402/403 classification);
19. slot separation enforced both directions + `open-args` never assignable;
20. preset catalog decision data shape (provisional rides `presets`, not
    `presetOrder`).

Scope cases (health precedent — career is scope-aware):
14b. USER-scope setup never clobbers SYSTEM or other users' rows;
15b. scope-aware setup creates rows at the requested scope.

Resolution precedence (plan 100): per-task override > capability-slot
default; derived-task inheritance; the `default` pseudo-task is gone for
good (no row can bring it back).
"""

from typing import Any
from uuid import UUID

import httpx
import pytest
from sqlalchemy import select

from app.ai.providers import setup as byok_setup
from app.ai.providers.errors import classify_provider_error, extract_error_status
from app.ai.providers.presets import (
    KEY_PREFIX_HINTS,
    PRESET_ORDER,
    SETUP_PRESETS,
)
from app.ai.providers.presets import guess_preset_for_key as _guess_preset_for_key
from app.ai.providers.service import infer_caps
from app.models.ai_provider_model import AIModel, AIProvider, AITaskAssignment
from app.models.user_model import User


def install_catalog(
    monkeypatch: pytest.MonkeyPatch,
    result: list[byok_setup.RemoteModel] | Exception,
) -> list[tuple[str, str, str | None]]:
    calls: list[tuple[str, str, str | None]] = []

    async def fake_fetch(
        provider_type: str,
        base_url: str,
        api_key: str | None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> list[byok_setup.RemoteModel]:
        calls.append((provider_type, base_url, api_key))
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(byok_setup, "fetch_remote_models", fake_fetch)
    return calls


def wire_catalog(model_ids: list[str]) -> list[byok_setup.RemoteModel]:
    return [byok_setup.RemoteModel(external_id=m, caps=tuple(infer_caps(m))) for m in model_ids]


async def models_of(db, provider_id=None) -> list[AIModel]:
    query = select(AIModel).order_by(AIModel.model_name)
    if provider_id is not None:
        query = query.where(AIModel.provider_id == provider_id)
    return list((await db.execute(query)).scalars())


async def seed_manual_provider(
    db,
    *,
    provider_type: str = "openai_compatible",
    base_url: str = "https://api.openai.com/v1",
    name: str = "Manual row",
    scope: str = "user",
    user_id=None,
    preset_key: str | None = None,
) -> AIProvider:
    provider = AIProvider(
        name=name,
        scope=scope,
        user_id=user_id,
        provider_type=provider_type,
        api_base=base_url,
        preset_key=preset_key,
    )
    db.add(provider)
    await db.flush()
    return provider


async def add_model(db, provider_id, model_name: str, caps: list[str]) -> AIModel:
    model = AIModel(
        provider_id=provider_id,
        name=model_name,
        model_name=model_name,
        caps=caps,
        is_active=True,
    )
    db.add(model)
    await db.flush()
    return model


async def _mk_user(db, email: str, is_admin: bool = False) -> User:
    from tests.test_ai_admin import _mk_user as _mk

    return await _mk(db, email, is_admin=is_admin)


def test_preset_metadata_uniformity() -> None:
    assert list(SETUP_PRESETS) == list(PRESET_ORDER)
    assert sorted(PRESET_ORDER) == [
        "deepseek",
        "gemini",
        "groq",
        "mistral",
        "ollama",
        "openai",
        "openrouter",
    ]
    assert SETUP_PRESETS["ollama"]["local"] is True
    assert SETUP_PRESETS["gemini"]["type"] == "google"
    assert SETUP_PRESETS["gemini"]["base_url"] == "https://generativelanguage.googleapis.com"
    assert [hint["prefix"] for hint in KEY_PREFIX_HINTS] == [
        "sk-ant-",
        "sk-or-v1-",
        "gsk_",
        "AIza",
        "sk-",
    ]
    assert _guess_preset_for_key("sk-ant-api03-xyz") == "anthropic"
    assert _guess_preset_for_key("gsk_abc") == "groq"
    assert _guess_preset_for_key("totally-random") is None
    assert _guess_preset_for_key("") is None


async def test_case_1_happy_path_openai_binds_chat_vision_and_stt(
    db, monkeypatch: pytest.MonkeyPatch, auth_headers
) -> None:
    user = await _current_user(db, auth_headers)
    calls = install_catalog(
        monkeypatch, wire_catalog(["gpt-5.6-terra", "gpt-5.6-luna", "whisper-1"])
    )
    outcome = await byok_setup.setup_provider_from_preset(db, user, "openai", "  sk-live-key  ")

    assert outcome.catalog_count == 3
    assert outcome.assigned_chat_model == "gpt-5.6-terra"
    assert outcome.assigned_vision_model == "gpt-5.6-terra"
    assert outcome.assigned_stt_model == "whisper-1"
    assert calls == [("openai", "https://api.openai.com/v1", "sk-live-key")]
    provider = (
        (await db.execute(select(AIProvider).where(AIProvider.id == outcome.provider_id)))
        .scalars()
        .first()
    )
    assert provider is not None and provider.preset_key == "openai"
    assert provider.api_key == "sk-live-key"
    by_id = {m.model_name: m for m in await models_of(db, provider.id)}
    assert by_id["whisper-1"].caps == ["stt"]
    assert by_id["gpt-5.6-terra"].is_active is True
    chat = await _slot_row(db, "text", user)
    vision = await _slot_row(db, "vision", user)
    stt = await _slot_row(db, "stt", user)
    assert chat is not None and chat.model_id == by_id["gpt-5.6-terra"].id
    assert vision is not None and vision.model_id == by_id["gpt-5.6-terra"].id
    assert stt is not None and stt.model_id == by_id["whisper-1"].id


async def _current_user(db, auth_headers) -> User:
    from tests.conftest import user_id_from_headers

    user_id = user_id_from_headers(auth_headers)
    return (await db.execute(select(User).where(User.id == UUID(user_id)))).scalars().one()


async def _slot_row(db, task_type: str, user: User):
    rows = await db.execute(
        select(AITaskAssignment).where(
            AITaskAssignment.task_type == task_type,
            AITaskAssignment.scope == "user",
            AITaskAssignment.user_id == user.id,
        )
    )
    return rows.scalars().first()


async def test_case_1_happy_path_gemini_maps_wire_type(
    db, monkeypatch: pytest.MonkeyPatch, auth_headers
) -> None:
    user = await _current_user(db, auth_headers)
    calls = install_catalog(monkeypatch, wire_catalog(["gemini-3.8-flash"]))
    outcome = await byok_setup.setup_provider_from_preset(db, user, "gemini", "AIza-key")

    provider = (
        (await db.execute(select(AIProvider).where(AIProvider.id == outcome.provider_id)))
        .scalars()
        .first()
    )
    assert provider is not None
    assert provider.provider_type == "google"
    assert provider.api_base == "https://generativelanguage.googleapis.com"
    assert outcome.assigned_chat_model == "gemini-3.8-flash"
    assert outcome.assigned_vision_model == "gemini-3.8-flash"
    assert calls[0][0] == "google"


async def test_case_1_happy_path_ollama_keyless(
    db, monkeypatch: pytest.MonkeyPatch, auth_headers
) -> None:
    user = await _current_user(db, auth_headers)
    calls = install_catalog(monkeypatch, wire_catalog(["llama3.3"]))
    outcome = await byok_setup.setup_provider_from_preset(db, user, "ollama", "")

    provider = (
        (await db.execute(select(AIProvider).where(AIProvider.id == outcome.provider_id)))
        .scalars()
        .first()
    )
    assert provider is not None
    assert provider.is_local is True
    assert provider.api_key is None
    assert outcome.assigned_chat_model is None
    assert calls[0][2] is None


async def test_case_2_re_setup_appends_the_fetched_catalog_and_dedupes(
    db, monkeypatch: pytest.MonkeyPatch, auth_headers
) -> None:
    user = await _current_user(db, auth_headers)
    install_catalog(monkeypatch, wire_catalog(["gpt-5.6-terra", "gpt-5.6-luna"]))
    first = await byok_setup.setup_provider_from_preset(db, user, "openai", "sk-first")
    manual_model = await add_model(db, first.provider_id, "old-favorite", ["text"])

    await byok_setup.setup_provider_from_preset(db, user, "openai", "sk-second")

    provider = (
        (await db.execute(select(AIProvider).where(AIProvider.id == first.provider_id)))
        .scalars()
        .first()
    )
    assert provider is not None
    assert provider.api_key == "sk-second"
    models = await models_of(db, provider.id)
    assert sorted(m.model_name for m in models) == [
        "gpt-5.6-luna",
        "gpt-5.6-terra",
        "old-favorite",
    ]
    assert (
        await db.execute(select(AIModel).where(AIModel.id == manual_model.id))
    ).scalars().first() is not None
    terra_rows = [m for m in models if m.model_name == "gpt-5.6-terra"]
    assert len(terra_rows) == 1


async def test_case_3_adopts_manual_row_earliest_first_and_stamps(
    db, monkeypatch: pytest.MonkeyPatch, auth_headers
) -> None:
    user = await _current_user(db, auth_headers)
    install_catalog(monkeypatch, wire_catalog(["gpt-5.6-terra"]))
    earliest = await seed_manual_provider(
        db, name="My OpenAI", provider_type="openai", user_id=user.id
    )
    later = await seed_manual_provider(
        db, name="Other OpenAI", provider_type="openai", user_id=user.id
    )

    outcome = await byok_setup.setup_provider_from_preset(db, user, "openai", "sk-new")

    adopted = (
        (await db.execute(select(AIProvider).where(AIProvider.id == outcome.provider_id)))
        .scalars()
        .first()
    )
    assert adopted is not None and adopted.id == earliest.id
    assert adopted.name == "My OpenAI"
    assert adopted.preset_key == "openai"
    reloaded_later = (
        (await db.execute(select(AIProvider).where(AIProvider.id == later.id))).scalars().first()
    )
    assert reloaded_later is not None and reloaded_later.preset_key is None


async def test_case_4_never_clobbers_live_assignments(
    db, monkeypatch: pytest.MonkeyPatch, auth_headers
) -> None:
    user = await _current_user(db, auth_headers)
    install_catalog(monkeypatch, wire_catalog(["gpt-5.6-terra", "whisper-1"]))
    provider = await seed_manual_provider(db, user_id=user.id)
    custom = await add_model(db, provider.id, "my-custom-model", ["text", "vision"])
    for slot in ("text", "vision", "stt"):
        db.add(
            AITaskAssignment(
                task_type=slot,
                scope="user",
                user_id=user.id,
                provider_id=provider.id,
                model_id=custom.id,
                is_active=True,
            )
        )
    await db.flush()

    outcome = await byok_setup.setup_provider_from_preset(db, user, "openai", "sk-key")

    assert outcome.assigned_chat_model is None
    assert outcome.assigned_vision_model is None
    assert outcome.assigned_stt_model is None
    for slot in ("text", "vision", "stt"):
        row = await _slot_row(db, slot, user)
        assert row is not None and row.model_id == custom.id


async def test_case_5_dead_id_assignments_rebind(
    db, monkeypatch: pytest.MonkeyPatch, auth_headers
) -> None:
    user = await _current_user(db, auth_headers)
    install_catalog(monkeypatch, wire_catalog(["gpt-5.6-terra"]))
    dead_provider = await seed_manual_provider(db, name="Dying", user_id=user.id)
    dead_model = await add_model(db, dead_provider.id, "dead-model", ["text", "vision"])
    db.add(
        AITaskAssignment(
            task_type="text",
            scope="user",
            user_id=user.id,
            provider_id=dead_provider.id,
            model_id=dead_model.id,
            is_active=True,
        )
    )
    await db.flush()
    dead_model.is_active = False
    await db.flush()

    outcome = await byok_setup.setup_provider_from_preset(db, user, "openai", "sk-key")

    by_id = {m.model_name: m for m in await models_of(db)}
    assert outcome.assigned_chat_model == "gpt-5.6-terra"
    chat = await _slot_row(db, "text", user)
    assert chat is not None and chat.model_id == by_id["gpt-5.6-terra"].id


async def test_case_6_invalid_key_persists_nothing(
    db, monkeypatch: pytest.MonkeyPatch, auth_headers
) -> None:
    user = await _current_user(db, auth_headers)

    async def boom(
        provider_type: str,
        base_url: str,
        api_key: str | None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> list[byok_setup.RemoteModel]:
        request = httpx.Request("GET", base_url)
        response = httpx.Response(
            401, request=request, json={"error": {"message": "Incorrect API key"}}
        )
        raise httpx.HTTPStatusError(
            "Client error '401 Unauthorized'", request=request, response=response
        )

    monkeypatch.setattr(byok_setup, "fetch_remote_models", boom)

    with pytest.raises(byok_setup.SetupError) as excinfo:
        await byok_setup.setup_provider_from_preset(db, user, "openai", "sk-bad")

    assert excinfo.value.classified.code.value == "invalid_key"
    await db.rollback()
    assert list((await db.execute(select(AIProvider))).scalars()) == []
    assert list((await db.execute(select(AIModel))).scalars()) == []


async def test_case_7_unknown_preset_typed_error_without_fetch(
    db, monkeypatch: pytest.MonkeyPatch, auth_headers
) -> None:
    user = await _current_user(db, auth_headers)
    calls = install_catalog(monkeypatch, wire_catalog(["gpt-5.6-terra"]))

    with pytest.raises(byok_setup.UnknownPresetError):
        await byok_setup.setup_provider_from_preset(db, user, "not-a-preset", "sk-key")

    assert calls == []


async def test_case_8_hanging_fetch_times_out_and_local_refused_is_local_not_running(
    db, monkeypatch: pytest.MonkeyPatch, auth_headers
) -> None:
    user = await _current_user(db, auth_headers)
    install_catalog(monkeypatch, httpx.ReadTimeout("timed out"))
    with pytest.raises(byok_setup.SetupError) as timeout_error:
        await byok_setup.setup_provider_from_preset(db, user, "openai", "sk-key")
    assert timeout_error.value.classified.code.value == "timeout"

    user = await _current_user(db, auth_headers)
    install_catalog(monkeypatch, httpx.ConnectError("connection refused"))
    with pytest.raises(byok_setup.SetupError) as refused_error:
        await byok_setup.setup_provider_from_preset(db, user, "ollama", "")
    assert refused_error.value.classified.code.value == "local_not_running"


def test_case_9_classifier_table_and_suspectedVendor_hints() -> None:
    def status_error(status: int, message: str = "err") -> httpx.HTTPStatusError:
        request = httpx.Request("GET", "https://x.test")
        response = httpx.Response(status, request=request, text=message)
        return httpx.HTTPStatusError(message, request=request, response=response)

    def code(error: Exception, **kwargs: Any) -> str:
        return classify_provider_error(error, local_provider=False, **kwargs).code.value

    assert code(status_error(401)) == "invalid_key"
    assert code(status_error(402)) == "insufficient_credit"
    assert (
        code(status_error(400, "failed with status 400: insufficient_quota"))
        == "insufficient_credit"
    )
    assert code(status_error(429)) == "new_user_quota"
    assert (
        code(status_error(403, "ORGANIZATION_RESTRICTED: region not supported"))
        == "region_unavailable"
    )
    assert code(status_error(403, "forbidden")) == "unknown"
    assert code(httpx.ReadTimeout("aborted")) == "timeout"
    assert (
        classify_provider_error(httpx.ConnectError("ECONNREFUSED"), local_provider=True).code.value
        == "local_not_running"
    )
    assert code(httpx.ConnectError("fetch failed")) == "unknown"

    mis_pasted = classify_provider_error(
        status_error(401),
        local_provider=False,
        api_key="sk-or-v1-abc",
        attempted_preset="openai",
    )
    assert mis_pasted.code.value == "invalid_key"
    assert mis_pasted.suspected_vendor == "openrouter"
    assert (
        classify_provider_error(
            status_error(401),
            local_provider=False,
            api_key="sk-ant-api03-x",
            attempted_preset="openai",
        ).suspected_vendor
        == "anthropic"
    )
    assert (
        classify_provider_error(
            status_error(401),
            local_provider=False,
            api_key="sk-abc123",
            attempted_preset="openai",
        ).suspected_vendor
        is None
    )
    assert extract_error_status("API request failed with status 401: bad key") == 401
    assert extract_error_status("fetch failed") is None


async def test_case_10_snapshot_suffix_curation_and_zero_match_fallback(
    db, monkeypatch: pytest.MonkeyPatch, auth_headers
) -> None:
    user = await _current_user(db, auth_headers)
    install_catalog(monkeypatch, wire_catalog(["gpt-5.6-terra-2026-09-11", "gpt-oss-120b"]))
    outcome = await byok_setup.setup_provider_from_preset(db, user, "openai", "sk-key")

    assert outcome.curated_missed is False
    assert outcome.catalog_count == 1
    assert outcome.assigned_chat_model == "gpt-5.6-terra-2026-09-11"

    install_catalog(monkeypatch, wire_catalog(["gpt-99-turbo", "gpt-99-mini"]))
    drifted = await byok_setup.setup_provider_from_preset(db, user, "openai", "sk-key")

    assert drifted.curated_missed is True
    assert drifted.catalog_count == 2
    assert drifted.assigned_chat_model is None


def test_case_11_capability_inference_split() -> None:
    assert infer_caps("whisper-1") == ["stt"]
    assert infer_caps("whisper-large-v3") == ["stt"]
    assert infer_caps("tts-1") == ["tts"]
    assert infer_caps("tts-1-hd") == ["tts"]
    assert infer_caps("text-embedding-3-small") == ["embeddings"]
    assert infer_caps("gpt-5.6-terra") == ["text", "vision", "tools"]
    assert "decision" not in infer_caps("decision-jev-latest")


async def test_case_12_set_default_task_scoping_guards_and_cross_provider_rejection(
    client, auth_headers, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_catalog(monkeypatch, wire_catalog(["gpt-5.6-terra", "text-only"]))

    setup = await client.post(
        "/api/v1/ai/providers/openai/setup",
        json={"api_key": "sk-test"},
        headers=auth_headers,
    )
    assert setup.status_code == 200, setup.text
    provider_id = setup.json()["provider"]["id"]

    tasks_before = (await client.get("/api/v1/ai/tasks", headers=auth_headers)).json()
    chat_before = next(t for t in tasks_before if t["value"] == "chat")
    assert chat_before.get("requires") == "text"

    bound = await client.put(
        f"/api/v1/ai/providers/{provider_id}/set-default",
        json={"model_name": "gpt-5.6-terra"},
        headers=auth_headers,
    )
    assert bound.status_code == 200, bound.text

    guard = await client.put(
        f"/api/v1/ai/providers/{provider_id}/set-default",
        json={"model_name": "text-only", "task": "cv_ocr"},
        headers=auth_headers,
    )
    assert guard.status_code == 422

    other = await client.post(
        "/api/v1/ai/providers",
        json={
            "name": "Other",
            "provider_type": "openai_compatible",
            "api_base": "https://other.test/v1",
        },
        headers=auth_headers,
    )
    assert other.status_code == 201, other.text
    other_id = other.json()["id"]
    shared = await client.post(
        f"/api/v1/ai/providers/{other_id}/models",
        json={"name": "shared-model", "model_name": "shared-model"},
        headers=auth_headers,
    )
    assert shared.status_code == 201, shared.text
    cross = await client.put(
        f"/api/v1/ai/providers/{provider_id}/set-default",
        json={"model_name": "shared-model"},
        headers=auth_headers,
    )
    assert cross.status_code == 409

    custom = await client.put(
        f"/api/v1/ai/providers/{provider_id}/set-default",
        json={"model_name": "brand-new-model"},
        headers=auth_headers,
    )
    assert custom.status_code == 200, custom.text


def test_setup_options_use_contract_names() -> None:
    options = byok_setup.SetupOptions()
    assert hasattr(options, "curated_ids")
    assert hasattr(options, "bind_chat")
    assert hasattr(options, "bind_vision")
    assert hasattr(options, "bind_stt")
    assert hasattr(options, "bind_decision")
    from app.ai.providers.errors import ProviderErrorCode

    assert ProviderErrorCode.TIMEOUT.value == "timeout"


async def test_case_14_scope_isolation_user_setup_never_clobbers_system_rows(
    db, monkeypatch: pytest.MonkeyPatch, auth_headers
) -> None:
    """USER-scope setup must leave SYSTEM rows (and other users') alone."""
    user = await _current_user(db, auth_headers)
    other = await _mk_user(db, "scope-other@example.com", is_admin=False)
    sys_provider = await seed_manual_provider(
        db, name="System row", scope="system", provider_type="openai_compatible"
    )
    sys_model = await add_model(db, sys_provider.id, "system-model", ["text", "vision"])
    db.add(
        AITaskAssignment(
            task_type="text",
            scope="system",
            provider_id=sys_provider.id,
            model_id=sys_model.id,
            is_active=True,
        )
    )
    other_provider = await seed_manual_provider(
        db, name="Other's row", scope="user", user_id=other.id
    )
    other_model = await add_model(db, other_provider.id, "other-model", ["text", "vision"])
    db.add(
        AITaskAssignment(
            task_type="text",
            scope="user",
            user_id=other.id,
            provider_id=other_provider.id,
            model_id=other_model.id,
            is_active=True,
        )
    )
    await db.flush()
    install_catalog(monkeypatch, wire_catalog(["gpt-5.6-terra", "whisper-1"]))

    outcome = await byok_setup.setup_provider_from_preset(db, user, "openai", "sk-mine")

    assert outcome.assigned_chat_model == "gpt-5.6-terra"
    rows = (
        (await db.execute(select(AITaskAssignment).where(AITaskAssignment.task_type == "text")))
        .scalars()
        .all()
    )
    by_owner = {(row.scope, row.user_id): row for row in rows}
    assert by_owner[("system", None)].model_id == sys_model.id
    assert by_owner[("user", other.id)].model_id == other_model.id
    mine = by_owner.get(("user", user.id))
    assert mine is not None and mine.model_id != sys_model.id
    stamped = (
        (await db.execute(select(AIProvider).where(AIProvider.id == outcome.provider_id)))
        .scalars()
        .first()
    )
    assert stamped is not None and stamped.scope == "user"


async def test_case_15_scope_aware_setup_creates_rows_at_the_requested_scope(
    db, client, auth_headers, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Admins may run the SAME one-click setup at system scope; the rows
    (provider, models, slot fills) land there, not in the admin's own."""
    install_catalog(monkeypatch, wire_catalog(["gpt-5.6-terra", "whisper-1"]))

    setup_user = await client.post(
        "/api/v1/ai/providers/openai/setup",
        json={"api_key": "sk-user"},
        headers=auth_headers,
    )
    assert setup_user.status_code == 200, setup_user.text
    assert setup_user.json()["provider"]["scope"] == "user"

    setup_system = await client.post(
        "/api/v1/ai/providers/openai/setup",
        json={"api_key": "sk-sys", "scope": "system"},
        headers=auth_headers,
    )
    assert setup_system.status_code == 200, setup_system.text
    assert setup_system.json()["provider"]["scope"] == "system"

    rows = (
        (await db.execute(select(AITaskAssignment).where(AITaskAssignment.task_type == "text")))
        .scalars()
        .all()
    )
    scopes = {(row.scope, row.user_id) for row in rows}
    assert ("system", None) in scopes
    assert any(scope == "user" for scope, _ in scopes)


async def test_resolution_precedence_per_task_overrides_slot_default(
    db, auth_headers, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.ai.providers.resolution import resolve_task_model

    user = await _current_user(db, auth_headers)
    install_catalog(monkeypatch, wire_catalog(["gpt-5.6-terra", "whisper-1"]))
    await byok_setup.setup_provider_from_preset(db, user, "openai", "sk-key")
    by_id = {m.model_name: m for m in await models_of(db)}

    resolved = await resolve_task_model(db, "chat", user.id)
    assert resolved.source == "user:text"
    assert resolved.model_name == "gpt-5.6-terra"

    db.add(
        AITaskAssignment(
            task_type="chat",
            scope="user",
            user_id=user.id,
            provider_id=by_id["gpt-5.6-terra"].provider_id,
            model_id=by_id["whisper-1"].id,
            is_active=True,
        )
    )
    await db.flush()
    resolved = await resolve_task_model(db, "chat", user.id)
    assert resolved.source == "user:chat"
    assert resolved.model_name == "whisper-1"

    derived = await resolve_task_model(db, "assist", user.id)
    assert derived.source == "user:text"
    assert derived.model_name == "gpt-5.6-terra"


async def test_resolution_default_pseudo_task_is_gone(db, client, auth_headers) -> None:
    """No row can bring the `default` pseudo-task back: the assignments
    API rejects it and resolution never reports a `default` source."""
    tasks = (await client.get("/api/v1/ai/tasks", headers=auth_headers)).json()
    assert all(t["value"] != "default" for t in tasks)
    assert {"text", "vision", "stt", "tts"}.issubset({t["value"] for t in tasks})

    rejected = await client.put(
        "/api/v1/ai/assignments/default",
        json={"scope": "user", "model_id": None},
        headers=auth_headers,
    )
    assert rejected.status_code == 404
