""": task registry + model-tier routing."""

import pytest
from sqlalchemy import select

from app.ai.providers.resolution import resolve_task_model
from app.ai.providers.service import AIProviderService
from app.ai.tasks import TASKS_BY_NAME, task_tier
from app.core.security import hash_password
from app.core.encryption import encrypt_secret
from app.models.ai_model import AIGeneration
from app.models.ai_provider_model import AIModel, AIProvider, AITaskAssignment
from app.models.enums import AICapability, AITaskTier, AITaskType
from app.models.user_model import User


def test_registry_covers_every_task_type():
    for task in AITaskType:
        task_def = TASKS_BY_NAME.get(task.value)
        assert task_def is not None, f"no TaskDef for {task.value}"
        assert task_def.tier in {t.value for t in AITaskTier}
        assert task_def.requires in {c.value for c in AICapability}
        assert task_def.description
    assert len(TASKS_BY_NAME) == len(AITaskType)


def test_plan_41a_tier_defaults():
    assert task_tier("target_resolve") == "fast"
    assert task_tier("posting_extract") == "strong"
    assert task_tier("chat") == "fast"
    assert task_tier("match_score") == "strong"
    assert task_tier("cv_ocr") == "fast"
    assert task_tier("cv_template_review") == "strong"


async def _mk_user(db, email: str) -> User:
    user = User(email=email, password_hash=hash_password("password123"))
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def _mk_tiered_model(
    db,
    *,
    scope: str,
    user: User,
    name: str,
    tier: str,
    provider_name: str,
) -> tuple[AIProvider, AIModel]:
    provider = AIProvider(
        name=provider_name,
        scope=scope,
        user_id=user.id if scope == "user" else None,
        provider_type="openai_compatible",
        api_base="https://api.example.com/v1",
        api_key_encrypted=encrypt_secret("sk-secret-123"),
    )
    db.add(provider)
    await db.flush()
    model = AIModel(provider_id=provider.id, name=name, model_name=name, tier=tier)
    db.add(model)
    await db.flush()
    return provider, model


async def _bind_tier(db, user: User, *, task_type: str, scope: str, tier: str):
    db.add(
        AITaskAssignment(
            task_type=task_type,
            scope=scope,
            user_id=user.id if scope == "user" else None,
            tier=tier,
        )
    )
    await db.commit()


async def test_tier_assignment_routes_to_classified_model(db):
    user = await _mk_user(db, "tier-route@example.com")
    provider, model = await _mk_tiered_model(
        db,
        scope="system",
        user=user,
        name="fast-mini",
        tier="fast",
        provider_name="sys-prov",
    )

    await _bind_tier(db, user, task_type="chat", scope="system", tier="fast")

    resolved = await resolve_task_model(db, "chat", user.id)
    assert resolved is not None
    assert resolved.model_name == "fast-mini"
    assert resolved.provider_type == "openai_compatible"
    assert resolved.tier == "fast"
    assert resolved.source == "system:chat (tier:fast)"
    assert resolved.base_url == provider.api_base


async def test_user_tier_model_beats_system_tier_model(db):
    owner = await _mk_user(db, "tier-owner@example.com")
    await _mk_tiered_model(
        db,
        scope="system",
        user=owner,
        name="system-fast",
        tier="fast",
        provider_name="a-sys",
    )
    mine_provider, _ = await _mk_tiered_model(
        db,
        scope="user",
        user=owner,
        name="my-fast",
        tier="fast",
        provider_name="b-mine",
    )
    await _bind_tier(db, owner, task_type="chat", scope="system", tier="fast")

    resolved = await resolve_task_model(db, "chat", owner.id)
    assert resolved.model_name == "my-fast"
    assert resolved.source == "system:chat (tier:fast)"


async def test_explicit_model_binding_beats_tier_binding(db):
    user = await _mk_user(db, "tier-vs-model@example.com")
    await _mk_tiered_model(
        db,
        scope="system",
        user=user,
        name="fast-mini",
        tier="fast",
        provider_name="sys-prov",
    )
    explicit_provider, explicit_model = await _mk_tiered_model(
        db,
        scope="system",
        user=user,
        name="explicit-strong",
        tier="strong",
        provider_name="sys-prov",
    )
    await _bind_tier(db, user, task_type="chat", scope="system", tier="fast")
    db.add(
        AITaskAssignment(
            task_type="chat",
            scope="system",
            provider_id=explicit_provider.id,
            model_id=explicit_model.id,
        )
    )
    await db.commit()

    resolved = await resolve_task_model(db, "chat", user.id)
    assert resolved.model_name == "explicit-strong"
    assert resolved.source == "system:chat"


async def test_unclassified_models_never_match_a_tier(db):
    user = await _mk_user(db, "tier-none@example.com")
    provider = AIProvider(
        name="prov",
        scope="system",
        provider_type="openai_compatible",
        api_base="https://api.example.com/v1",
    )
    db.add(provider)
    await db.flush()
    db.add(AIModel(provider_id=provider.id, name="m", model_name="m"))
    await db.commit()
    await _bind_tier(db, user, task_type="chat", scope="system", tier="fast")

    assert await resolve_task_model(db, "chat", user.id) is None


async def test_audit_rows_carry_task_tier(db, client, auth_headers, seeded_catalog):
    job = (await client.get("/api/v1/jobs/nurse", headers=auth_headers)).json()
    await client.post(
        "/api/v1/match/score", json={"job_id": job["id"]}, headers=auth_headers
    )
    row = (
        (
            await db.execute(
                select(AIGeneration).where(AIGeneration.task_type == "match_score")
            )
        )
        .scalars()
        .first()
    )
    assert row is not None
    assert row.task_tier == "strong"


async def test_model_and_assignment_tier_api(client, auth_headers, db):
    created = await client.post(
        "/api/v1/ai/providers",
        json={"name": "T", "provider_type": "openai_compatible", "scope": "user"},
        headers=auth_headers,
    )
    provider_id = created.json()["id"]
    model = await client.post(
        f"/api/v1/ai/providers/{provider_id}/models",
        json={"name": "mini", "model_name": "mini-1", "tier": "fast"},
        headers=auth_headers,
    )
    assert model.status_code == 201, model.text
    assert model.json()["tier"] == "fast"

    bad = await client.post(
        f"/api/v1/ai/providers/{provider_id}/models",
        json={"name": "x", "model_name": "x", "tier": "huge"},
        headers=auth_headers,
    )
    assert bad.status_code == 422

    assignment = await client.put(
        "/api/v1/ai/assignments/chat",
        json={"scope": "user", "tier": "fast"},
        headers=auth_headers,
    )
    assert assignment.status_code == 200, assignment.text
    assert assignment.json()["tier"] == "fast"
    assert assignment.json()["model_id"] is None
    assert assignment.json()["is_active"] is True

    me = (await client.get("/api/v1/auth/me", headers=auth_headers)).json()
    from sqlalchemy import select as _select

    from app.models.user_model import User as _User

    user = (
        (await db.execute(_select(_User).where(_User.email == me["email"])))
        .scalars()
        .first()
    )
    resolved = await resolve_task_model(db, "chat", user.id)
    assert resolved is not None
    assert resolved.tier == "fast"
    assert "(tier:fast)" in resolved.source


async def test_set_assignment_model_clears_tier(db, client, auth_headers):
    created = await client.post(
        "/api/v1/ai/providers",
        json={"name": "T2", "provider_type": "openai_compatible", "scope": "user"},
        headers=auth_headers,
    )
    provider_id = created.json()["id"]
    model = await client.post(
        f"/api/v1/ai/providers/{provider_id}/models",
        json={"name": "big", "model_name": "big-1", "tier": "strong"},
        headers=auth_headers,
    )
    model_id = model.json()["id"]
    me = (await client.get("/api/v1/auth/me", headers=auth_headers)).json()
    from sqlalchemy import select as _select

    from app.models.user_model import User as _User

    user = (
        (await db.execute(_select(_User).where(_User.email == me["email"])))
        .scalars()
        .first()
    )
    service = AIProviderService(db)
    await service.set_assignment(
        user, task_type="assist", scope="user", model_id=None, tier="fast"
    )
    assignment = await service.set_assignment(
        user, task_type="assist", scope="user", model_id=model_id
    )
    assert assignment.tier is None
    assert str(assignment.model_id) == model_id


@pytest.mark.parametrize("tier", ["fast", "strong"])
async def test_validate_tier_accepts_known_values(db, tier):
    from app.ai.providers.service import _validate_tier

    assert _validate_tier(tier) == tier


async def test_validate_tier_rejects_unknown(db):
    from app.core.errors import ValidationError

    from app.ai.providers.service import _validate_tier

    with pytest.raises(ValidationError):
        _validate_tier("turbo")
