"""Factory unit tests: build_chat_model kwargs per provider type."""

import httpx
import pytest
from google.genai.client import Client as GoogleClient
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI

from app.ai.chat_models import (
    GOOGLE_BASE_URL,
    CompatibleChatOpenAI,
    build_chat_model,
    build_embedding_model,
    is_openai_endpoint,
    token_cap_kwargs,
)
from app.ai.providers.resolution import ResolvedModel


def _resolved(provider_type: str, **overrides) -> ResolvedModel:
    defaults = dict(
        provider_type=provider_type,
        base_url="https://api.example.com/v1",
        api_key="sk-secret-123",
        model_name="gpt-test",
        source="system:default",
    )
    defaults.update(overrides)
    return ResolvedModel(**defaults)


def test_build_chat_model_compatible_defaults():
    model = build_chat_model(_resolved("openai_compatible"))
    assert model.model_name == "gpt-test"
    assert isinstance(model, CompatibleChatOpenAI)
    assert model.temperature is None
    assert model.max_retries == 0
    assert model.max_tokens is None
    assert model.model_kwargs == {"response_format": {"type": "json_object"}}
    assert model.use_responses_api is False
    assert model.stream_usage is True
    assert model.http_async_client is None


def test_build_chat_model_temperature_and_max_tokens_split():
    compatible = build_chat_model(_resolved("openai_compatible", max_tokens=512))
    assert isinstance(compatible, CompatibleChatOpenAI)
    assert compatible.max_tokens == 512
    assert compatible._default_params["max_tokens"] == 512
    assert "max_completion_tokens" not in compatible._default_params

    openai_model = build_chat_model(_resolved("openai", max_tokens=512))
    assert openai_model._default_params["max_completion_tokens"] == 512
    assert "max_tokens" not in openai_model._default_params
    assert openai_model.model_kwargs["response_format"] == {"type": "json_object"}


def test_build_chat_model_openai_endpoint_overrides_compatible_type():
    """api.openai.com base URL wins over the declared compatible type."""
    model = build_chat_model(
        _resolved(
            "openai_compatible",
            base_url="https://api.openai.com/v1",
            max_tokens=512,
            temperature=0.2,
        )
    )
    assert isinstance(model, ChatOpenAI)
    assert not isinstance(model, CompatibleChatOpenAI)
    assert model._default_params["max_completion_tokens"] == 512
    assert "max_tokens" not in model._default_params
    assert model.temperature == 0.2


def test_build_chat_model_temperature_omitted_when_unset():
    model = build_chat_model(_resolved("openai", max_tokens=512))
    assert "temperature" not in model._default_params


def test_compatible_model_keeps_max_tokens_without_cap():
    model = build_chat_model(_resolved("openai_compatible"))
    assert "max_tokens" not in model._default_params
    assert "max_completion_tokens" not in model._default_params


def test_build_chat_model_temperature_override():
    model = build_chat_model(_resolved("openai_compatible", temperature=0.1))
    assert model.temperature == 0.1


def test_build_chat_model_reasoning_effort_only_when_set():
    unset = build_chat_model(_resolved("openai_compatible"))
    assert "reasoning_effort" not in unset._default_params

    compatible = build_chat_model(
        _resolved("openai_compatible", reasoning_effort="high")
    )
    assert compatible.reasoning_effort == "high"
    assert compatible._default_params["reasoning_effort"] == "high"

    openai_model = build_chat_model(_resolved("openai", reasoning_effort="none"))
    assert openai_model.reasoning_effort == "none"
    assert openai_model._default_params["reasoning_effort"] == "none"


def test_build_chat_model_rejects_mock():
    with pytest.raises(ValueError, match="mock"):
        build_chat_model(_resolved("mock"))


def test_build_chat_model_google_defaults():
    model = build_chat_model(
        _resolved("google", base_url=GOOGLE_BASE_URL, model_name="gemini-2.5-flash")
    )
    assert isinstance(model, ChatGoogleGenerativeAI)
    assert model.model == "gemini-2.5-flash"
    assert model.google_api_key.get_secret_value() == "sk-secret-123"
    assert model.temperature is None
    assert model.max_output_tokens is None
    assert model.max_retries == 0
    assert model.reasoning_effort is None
    assert "response_format" not in model.model_kwargs


def test_build_chat_model_google_base_url_fallback():
    model = build_chat_model(_resolved("google", base_url=""))
    assert model.base_url == GOOGLE_BASE_URL


def test_build_chat_model_google_optional_knobs():
    model = build_chat_model(
        _resolved(
            "google",
            base_url=GOOGLE_BASE_URL,
            temperature=0.3,
            max_tokens=256,
            reasoning_effort="high",
        )
    )
    assert model.temperature == 0.3
    assert model.max_output_tokens == 256
    assert model.reasoning_effort == "high"


def test_build_chat_model_google_unknown_reasoning_effort_omitted():
    model = build_chat_model(
        _resolved("google", base_url=GOOGLE_BASE_URL, reasoning_effort="none")
    )
    assert model.reasoning_effort is None


def test_build_chat_model_google_transport_swaps_client():
    """The transport seam replaces the Gemini SDK client's httpx stack
    (tests never touch the network); the async client derives from the
    same swapped client, so ``ainvoke`` rides the seam too."""
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={}))
    model = build_chat_model(
        _resolved("google", base_url=GOOGLE_BASE_URL), transport=transport
    )
    assert isinstance(model.client, GoogleClient)
    assert isinstance(
        model.client._api_client._httpx_client._transport, httpx.MockTransport
    )
    assert isinstance(
        model.client._api_client._async_httpx_client._transport, httpx.MockTransport
    )
    assert model.async_client is model.client.aio
    without = build_chat_model(_resolved("google", base_url=GOOGLE_BASE_URL))
    assert isinstance(
        without.client._api_client._httpx_client._transport, httpx.HTTPTransport
    )


def test_build_embedding_model_rejects_google():
    with pytest.raises(ValueError, match="embeddings-capable"):
        build_embedding_model(
            _resolved("google", base_url=GOOGLE_BASE_URL, model_name="gemini-2.5-flash")
        )


def test_build_chat_model_injects_async_transport():
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={}))
    model = build_chat_model(_resolved("openai_compatible"), transport=transport)
    assert isinstance(model.http_async_client, httpx.AsyncClient)


def test_token_cap_kwargs_per_provider_type():
    assert token_cap_kwargs("openai", 5) == {"max_completion_tokens": 5}
    assert token_cap_kwargs("openai_compatible", 5) == {"max_tokens": 5}
    assert token_cap_kwargs("mock", 5) == {"max_tokens": 5}


def test_token_cap_kwargs_openai_endpoint():
    assert is_openai_endpoint("https://api.openai.com/v1") is True
    assert is_openai_endpoint("https://api.example.com/v1") is False
    assert is_openai_endpoint(None) is False
    assert token_cap_kwargs("openai_compatible", 5, "https://api.openai.com/v1") == {
        "max_completion_tokens": 5
    }
    assert token_cap_kwargs("openai_compatible", 5, "https://api.example.com/v1") == {
        "max_tokens": 5
    }
