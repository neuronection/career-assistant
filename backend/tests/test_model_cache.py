"""The process-local embedding client cache (plan 201 S2)."""

from types import SimpleNamespace

import httpx

from app.ai.model_cache import (
    MAX_EMBEDDING_MODELS,
    cached_embedding_models,
    embedding_model_key,
    get_embedding_model,
)


def _resolved(**overrides) -> SimpleNamespace:
    base = {
        "provider_type": "openai",
        "model_name": "text-embedding-3-small",
        "api_key": "sk-test-key",
        "base_url": "https://embeddings.example.invalid/v1",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_the_same_resolved_model_is_reused():
    resolved = _resolved()
    first = get_embedding_model(resolved)
    second = get_embedding_model(_resolved())
    assert second is first
    assert cached_embedding_models() == 1


def test_a_changed_provider_or_model_is_a_new_entry():
    first = get_embedding_model(_resolved())
    other_model = get_embedding_model(_resolved(model_name="text-embedding-3-large"))
    other_base = get_embedding_model(_resolved(base_url="https://other.example.invalid/v1"))
    other_key = get_embedding_model(_resolved(api_key="sk-other-key"))
    assert len({id(first), id(other_model), id(other_base), id(other_key)}) == 4
    assert cached_embedding_models() == 4


def test_an_injected_transport_bypasses_the_cache():
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={}))
    first = get_embedding_model(_resolved(), transport=transport)
    second = get_embedding_model(_resolved(), transport=transport)
    assert first is not second
    assert cached_embedding_models() == 0


def test_a_keyless_endpoint_hashes_an_empty_key():
    key = embedding_model_key(_resolved(api_key=None, provider_type="openai_compatible"))
    assert key[0] == "openai_compatible"
    assert key[3]  # a digest, never empty
    first = get_embedding_model(_resolved(api_key=None))
    assert get_embedding_model(_resolved(api_key=None)) is first


def test_the_cache_is_bounded():
    models = [
        get_embedding_model(_resolved(model_name=f"model-{index}"))
        for index in range(MAX_EMBEDDING_MODELS + 3)
    ]
    assert cached_embedding_models() == MAX_EMBEDDING_MODELS
    assert models[0] is not models[-1]
