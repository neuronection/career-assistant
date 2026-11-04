"""The embedding-model profile registry (plan 52 T2a): precedence, CRUD, API.

The curated catalog is code; an admin row is the explicit override. These
tests pin the precedence (admin → curated → fallback), the no-name-guessing
rule, the bounded validation, the admin guard and the report integration —
without touching chunk writes or a space.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.ai.tokenizers import (
    CURATED_OPENAI_MODELS,
    EmbeddingModelProfile,
    fallback_profile,
    provider_class,
    resolve_embedding_profile,
    resolve_tokenizer_spec,
)
from app.core.errors import ValidationError
from app.models.ai_provider_model import AIModel, AIProvider, AITaskAssignment
from app.models.embedding_profile_model import EmbeddingModelProfile as EmbeddingModelProfileRow
from app.models.identity_model import AuditEvent
from app.services import embedding_profiles
from app.storage import retrieval_ops as ops
from app.storage.tokenizer_contract import TokenizerKind, TokenizerSource

PATH = "/api/v1/admin/retrieval/model-profiles"
REPORT_PATH = "/api/v1/admin/retrieval/tokenizer"


def _override_payload(**overrides):
    payload = {
        "provider_class": "openai",
        "model": "text-embedding-3-small",
        "tokenizer_kind": "heuristic",
        "tokenizer_identifier": "utf8-heuristic-v1",
        "max_input_tokens": 2048,
        "batch_max_items": 16,
        "batch_max_tokens": 2048,
        "chunk_max_tokens": 128,
        "chunk_overlap_tokens": 16,
        "chunk_max_chars": 500,
    }
    payload.update(overrides)
    return payload


def _built_override(**overrides) -> EmbeddingModelProfile:
    payload = _override_payload(**overrides)
    return embedding_profiles.build_override(
        provider=payload["provider_class"],
        model=payload["model"],
        tokenizer_kind=payload["tokenizer_kind"],
        tokenizer_identifier=payload["tokenizer_identifier"],
        tokenizer_revision=payload.get("tokenizer_revision"),
        tokenizer_artifact_sha256=payload.get("tokenizer_artifact_sha256"),
        max_input_tokens=payload["max_input_tokens"],
        batch_max_items=payload["batch_max_items"],
        batch_max_tokens=payload["batch_max_tokens"],
        chunk_max_tokens=payload["chunk_max_tokens"],
        chunk_overlap_tokens=payload["chunk_overlap_tokens"],
        chunk_max_chars=payload["chunk_max_chars"],
    )


def test_curated_catalog_is_the_three_openai_embeddings():
    profile = resolve_embedding_profile("openai_compatible", "text-embedding-3-small")
    assert profile.source is TokenizerSource.CURATED
    assert profile.tokenizer.kind is TokenizerKind.TIKTOKEN
    assert profile.tokenizer.identifier == "cl100k_base"
    assert profile.exact is True
    assert profile.override is False
    assert profile.chunk.max_chunk_tokens == 512
    assert profile.chunk.overlap_tokens == 64
    assert profile.chunk.max_chars == 1600
    assert profile.batch_max_items == 2048
    assert profile.chunk.fits(profile.tokenizer.max_input_tokens)

    curated = {
        (entry.provider_class, entry.model)
        for entry in embedding_profiles.CURATED_EMBEDDING_PROFILES
    }
    assert curated == {("openai", model) for model in CURATED_OPENAI_MODELS}
    assert all(source == "openai" for source, _model in curated)


def test_resolver_precedence_admin_then_curated_then_fallback():
    admin = _built_override()
    assert admin.source is TokenizerSource.ADMIN
    assert admin.override is True

    resolved = resolve_embedding_profile(
        "openai_compatible", "text-embedding-3-small", override=admin
    )
    assert resolved is admin, "an explicit admin row wins over the curated catalog"

    curated = resolve_embedding_profile("openai_compatible", "text-embedding-3-small")
    assert curated.source is TokenizerSource.CURATED

    unknown = resolve_embedding_profile("ollama", "nomic-embed-text")
    assert unknown.source is TokenizerSource.FALLBACK
    assert unknown.tokenizer.kind is TokenizerKind.HEURISTIC
    assert unknown.exact is False
    assert unknown.max_input_assumed is True


def test_override_for_another_pair_is_ignored():
    admin = _built_override(provider_class="openai", model="text-embedding-3-large")
    resolved = resolve_embedding_profile(
        "openai_compatible", "text-embedding-3-small", override=admin
    )
    assert resolved.source is TokenizerSource.CURATED
    assert resolved.model == "text-embedding-3-small"


def test_no_model_name_guessing_across_provider_classes():
    """A known OpenAI name served by another provider class stays fallback."""
    for provider in ("google", "ollama", "mock", "unknown"):
        resolved = resolve_embedding_profile(provider, "text-embedding-3-small")
        assert resolved.source is TokenizerSource.FALLBACK, provider
        assert resolved.tokenizer.kind is TokenizerKind.HEURISTIC, provider
    assert provider_class("openai_compatible") == "openai"
    assert provider_class("OpenAI") == "openai"


def test_build_override_rejects_invalid_bounds_and_unsupported_kinds():
    with pytest.raises(ValidationError):
        _built_override(chunk_max_tokens=128, chunk_overlap_tokens=64)
    with pytest.raises(ValidationError):
        _built_override(max_input_tokens=100, chunk_max_tokens=256)
    with pytest.raises(ValidationError):
        _built_override(batch_max_tokens=64, chunk_max_tokens=128)
    with pytest.raises(ValidationError):
        _built_override(tokenizer_kind="hf_tokenizers", tokenizer_identifier="org/model")
    with pytest.raises(ValidationError):
        _built_override(tokenizer_kind="tiktoken", tokenizer_identifier="o200k_base")
    with pytest.raises(ValidationError):
        _built_override(tokenizer_artifact_sha256="a" * 64)
    with pytest.raises(ValidationError):
        _built_override(tokenizer_identifier="")


async def test_profile_api_lists_curated_and_resolves_a_preview(client, auth_headers):
    response = await client.get(PATH, headers=auth_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["state"] == "ok"
    assert body["token_aware_writes"] is False
    assert len(body["curated"]) == 3
    assert body["overrides"] == []
    assert body["resolution"]["source"] in ("fallback", "curated", "admin")
    assert body["bounds"]["supported_kinds"] == ["tiktoken", "heuristic"]
    ops.assert_no_raw_text(body)

    preview = await client.get(
        PATH,
        params={"provider": "openai_compatible", "model": "text-embedding-3-small"},
        headers=auth_headers,
    )
    assert preview.status_code == 200, preview.text
    resolution = preview.json()["resolution"]
    assert resolution["source"] == "curated"
    assert resolution["exact"] is True
    assert resolution["chunk"]["max_chunk_tokens"] == 512
    assert resolution["batch_max_items"] == 2048


async def test_profile_api_save_update_and_delete(client, db, auth_headers):
    payload = _override_payload()
    saved = await client.put(PATH, json=payload, headers=auth_headers)
    assert saved.status_code == 200, saved.text
    profile = saved.json()["profile"]
    assert profile["source"] == "admin"
    assert profile["exact"] is False
    assert profile["chunk"] == {
        "max_chunk_tokens": 128,
        "overlap_tokens": 16,
        "max_chars": 500,
    }

    preview = await client.get(
        PATH,
        params={"provider": "openai_compatible", "model": "text-embedding-3-small"},
        headers=auth_headers,
    )
    resolution = preview.json()["resolution"]
    assert resolution["source"] == "admin"
    assert resolution["override"] is True
    assert resolution["max_input_tokens"] == 2048
    assert resolution["batch_max_tokens"] == 2048

    google = await client.get(
        PATH,
        params={"provider": "google", "model": "text-embedding-3-small"},
        headers=auth_headers,
    )
    assert google.json()["resolution"]["source"] == "fallback", "no name guessing"

    updated = await client.put(
        PATH,
        json={**_override_payload(), "max_input_tokens": 4096, "batch_max_tokens": 4096},
        headers=auth_headers,
    )
    assert updated.status_code == 200, updated.text
    rows = (
        (
            await db.execute(
                select(EmbeddingModelProfileRow).where(
                    EmbeddingModelProfileRow.provider_class == "openai",
                    EmbeddingModelProfileRow.model_name == "text-embedding-3-small",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1, "the unique (provider_class, model_name) scope updates in place"
    assert rows[0].max_input_tokens == 4096

    audits = (
        (await db.execute(select(AuditEvent).where(AuditEvent.action == "vector.model.changed")))
        .scalars()
        .all()
    )
    assert any("model_profile:openai/text-embedding-3-small" in row.resource for row in audits), (
        "the change uses the existing vector.* audit group"
    )

    deleted = await client.delete(
        PATH,
        params={"provider": "openai", "model": "text-embedding-3-small"},
        headers=auth_headers,
    )
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["deleted"] is True
    assert deleted.json()["resolution"]["source"] == "curated"

    again = await client.delete(
        PATH,
        params={"provider": "openai", "model": "text-embedding-3-small"},
        headers=auth_headers,
    )
    assert again.status_code == 200
    assert again.json()["deleted"] is False, "delete is idempotent"


@pytest.mark.parametrize(
    "overrides",
    [
        {"chunk_max_tokens": 128, "chunk_overlap_tokens": 64},
        {"max_input_tokens": 100, "chunk_max_tokens": 256},
        {"batch_max_tokens": 64, "chunk_max_tokens": 128},
        {"tokenizer_kind": "hf_tokenizers", "tokenizer_identifier": "org/model"},
        {"tokenizer_kind": "tiktoken", "tokenizer_identifier": "o200k_base"},
        {"tokenizer_artifact_sha256": "a" * 64},
    ],
)
async def test_profile_api_rejects_invalid_profiles(client, auth_headers, overrides):
    response = await client.put(
        PATH, json={**_override_payload(), **overrides}, headers=auth_headers
    )
    assert response.status_code == 400, response.text


async def test_profile_api_rejects_out_of_bounds_at_the_model(client, auth_headers):
    for overrides in (
        {"max_input_tokens": embedding_profiles.MAX_INPUT_TOKENS + 1},
        {"batch_max_items": 0},
        {"chunk_max_tokens": 31},
        {"chunk_max_chars": 0},
        {"tokenizer_artifact_sha256": "not-a-sha"},
    ):
        response = await client.put(
            PATH, json={**_override_payload(), **overrides}, headers=auth_headers
        )
        assert response.status_code == 422, (overrides, response.text)


async def test_profile_endpoints_are_admin_only(client, auth_headers):
    from tests.conftest import register_user

    nonadmin = await register_user(client, "model-profile-nonadmin@example.com")
    assert (await client.get(PATH)).status_code == 401
    assert (await client.get(PATH, headers=nonadmin)).status_code == 403
    payload = _override_payload()
    assert (await client.put(PATH, json=payload)).status_code == 401
    assert (await client.put(PATH, json=payload, headers=nonadmin)).status_code == 403
    assert (
        await client.delete(PATH, params={"provider": "openai", "model": "m"})
    ).status_code == 401
    assert (
        await client.delete(PATH, params={"provider": "openai", "model": "m"}, headers=nonadmin)
    ).status_code == 403


async def test_tokenizer_report_reflects_the_admin_profile(client, db, auth_headers):
    from app.models.enums import AITaskType

    provider = AIProvider(
        name="openai-embed-test",
        scope="system",
        provider_type="openai_compatible",
        api_base="https://api.openai.com/v1",
    )
    model = AIModel(provider=provider, name="embed-small", model_name="text-embedding-3-small")
    db.add_all([provider, model])
    await db.flush()
    db.add(
        AITaskAssignment(
            task_type=AITaskType.EMBED.value,
            scope="system",
            provider_id=provider.id,
            model_id=model.id,
        )
    )
    await db.commit()

    before = await client.get(REPORT_PATH, headers=auth_headers)
    assert before.status_code == 200, before.text
    body = before.json()
    assert body["model"]["model"] == "text-embedding-3-small"
    assert body["profile"]["source"] == "curated"
    assert body["profile"]["exact"] is True

    saved = await client.put(PATH, json=_override_payload(), headers=auth_headers)
    assert saved.status_code == 200, saved.text

    after = await client.get(REPORT_PATH, headers=auth_headers)
    body = after.json()
    assert body["profile"]["source"] == "admin"
    assert body["profile"]["chunk"]["max_chunk_tokens"] == 128
    assert body["tokenizer"]["kind"] == "heuristic"
    assert body["tokenizer"]["exact"] is False
    assert body["chunking"]["token_aware"] is False, "T2a never activates token-aware writes"
    ops.assert_no_raw_text(body)


def test_fallback_profile_is_conservative_and_never_exact():
    fallback = fallback_profile("ollama", "nomic-embed-text")
    assert fallback.source is TokenizerSource.FALLBACK
    assert fallback.exact is False
    assert fallback.tokenizer.kind is TokenizerKind.HEURISTIC
    assert fallback.chunk.max_chunk_tokens <= fallback.tokenizer.max_input_tokens
    assert fallback.chunk.overlap_tokens * 2 < fallback.chunk.max_chunk_tokens


def test_resolve_tokenizer_spec_matches_the_profile():
    assert (
        resolve_tokenizer_spec("openai_compatible", "text-embedding-3-large")
        == resolve_embedding_profile("openai_compatible", "text-embedding-3-large").tokenizer
    )
