"""LangChain model factory — the only module that builds chat models.

Import boundary: provider SDKs and LangChain chat
classes are imported here and nowhere else. ``build_chat_model`` turns a
DB-resolved model configuration (``ResolvedModel``) into a LangChain chat
model; retries stay in the gateway funnel (``max_retries=0``) and tests
inject an ``httpx`` transport instead of touching the network.
"""

from typing import TYPE_CHECKING, Any, Optional, cast
from urllib.parse import urlsplit

import httpx
from google.genai import types as google_types
from google.genai.client import Client as GoogleClient
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from app.core.config import settings

if TYPE_CHECKING:
    from app.ai.providers.resolution import ResolvedModel

_KEYLESS_API_KEY = "missing"
GOOGLE_BASE_URL = "https://generativelanguage.googleapis.com"
_GOOGLE_REASONING_EFFORT_LEVELS = frozenset({"minimal", "low", "medium", "high"})


class CompatibleChatOpenAI(ChatOpenAI):
    """ChatOpenAI that keeps ``max_tokens`` on the wire.

    ``ChatOpenAI`` renames the ``max_tokens`` parameter to
    ``max_completion_tokens`` in the request payload — fine for OpenAI
    itself, but OpenAI-compatible endpoints (Ollama, LM Studio, OpenRouter,
    llama.cpp…) reject the newer name. Skipping the rename restores the
    wire contract these providers always had.
    """

    @property
    def _default_params(self) -> dict[str, Any]:
        # Skip ChatOpenAI's override; BaseChatOpenAI leaves the name alone.
        return super(ChatOpenAI, self)._default_params


def is_openai_endpoint(base_url: Optional[str]) -> bool:
    """True when the base URL points at OpenAI's own API.

    Providers are sometimes registered as ``openai_compatible`` with
    ``https://api.openai.com/v1`` — the wire contract of OpenAI itself
    (``max_completion_tokens``) must win over the declared type.
    """
    try:
        return urlsplit(base_url or "").hostname == "api.openai.com"
    except ValueError:
        return False


def is_openai_wire(provider_type: str, base_url: Optional[str]) -> bool:
    """Should payloads use OpenAI's modern wire contract?"""
    return provider_type == "openai" or (
        provider_type == "openai_compatible" and is_openai_endpoint(base_url)
    )


def token_cap_kwargs(
    provider_type: str, cap: int, base_url: Optional[str] = None
) -> dict[str, int]:
    """Token-cap params for a plain REST chat payload, per provider type.

    Modern OpenAI models reject ``max_tokens`` while OpenAI-compatible
    endpoints don't know ``max_completion_tokens`` — the cap adapts per
    provider type (used by the httpx connection ping; ``build_chat_model``
    applies the same split through ChatOpenAI's own mechanics).
    """
    if is_openai_wire(provider_type, base_url):
        return {"max_completion_tokens": cap}
    return {"max_tokens": cap}


def _google_model(
    resolved: "ResolvedModel",
    transport: Optional[httpx.AsyncBaseTransport] = None,
) -> ChatGoogleGenerativeAI:
    """Native Gemini API chat model (LangChain ``langchain-google-genai``).

    Mirrors study-assistant's reference implementation: no ``response_format``
    (the prompt's JSON-schema line + the gateway's ``_extract_json`` parsing
    carry structured output), unknown reasoning-effort tokens are omitted,
    and retries stay in the gateway funnel — the SDK client only ever runs
    with a 1-attempt retry policy, and is replaced wholesale when a test
    transport is injected (never instantiated in tests without one).
    """
    api_key = resolved.api_key or _KEYLESS_API_KEY
    base_url = resolved.base_url or GOOGLE_BASE_URL
    kwargs: dict[str, Any] = {
        "model": resolved.model_name,
        "api_key": api_key,
        "base_url": base_url,
        "temperature": None,
        # 0 is SDK-normalized to a single attempt — no client-side retries,
        # the gateway funnel owns retry policy (career's max_retries=0).
        "max_retries": 0,
    }
    if resolved.reasoning_effort in _GOOGLE_REASONING_EFFORT_LEVELS:
        kwargs["reasoning_effort"] = resolved.reasoning_effort
    if resolved.temperature is not None:
        kwargs["temperature"] = resolved.temperature
    if resolved.max_tokens is not None:
        kwargs["max_tokens"] = resolved.max_tokens
    model = ChatGoogleGenerativeAI(**kwargs)
    if transport is not None:
        model.client = GoogleClient(
            api_key=api_key,
            http_options=google_types.HttpOptions(
                base_url=base_url,
                timeout=int(settings.AI_TIMEOUT),
                retry_options=google_types.HttpRetryOptions(attempts=1),
                httpx_client=httpx.Client(
                    transport=cast(httpx.BaseTransport, transport),
                    timeout=settings.AI_TIMEOUT,
                ),
                httpx_async_client=httpx.AsyncClient(
                    transport=transport, timeout=settings.AI_TIMEOUT
                ),
            ),
        )
    return model


async def discover_google_models(
    api_key: Optional[str], base_url: Optional[str]
) -> list[dict]:
    """Gemini catalog via the google-genai SDK's model listing.

    Only generation-capable models are offered (embedding/TTS models would
    fail the chat funnel); ids drop the ``models/`` prefix so they register
    like any other model name. The SDK import stays inside this function —
    tests stub ``google.genai.client.Client`` (no network, keeping tests
    hermetic). ``Model.supported_actions`` is the google-genai v2 field
    (the legacy SDK called it ``supported_generation_methods``).
    """
    from google.genai import types as google_types
    from google.genai.client import Client

    client = Client(
        api_key=api_key or _KEYLESS_API_KEY,
        http_options=google_types.HttpOptions(
            base_url=base_url or GOOGLE_BASE_URL,
            timeout=10000,
        ),
    )
    pager = await client.aio.models.list()
    models = [
        {
            "id": model.name.removeprefix("models/"),
            "name": model.display_name or model.name.removeprefix("models/"),
            "owned_by": "google",
        }
        async for model in pager
        if "generateContent" in (model.supported_actions or []) and model.name
    ]
    models.sort(key=lambda m: m["name"])
    return models


def build_chat_model(
    resolved: "ResolvedModel",
    transport: Optional[httpx.AsyncBaseTransport] = None,
) -> BaseChatModel:
    """Build the LangChain chat model for a resolved provider/model.

    OpenAI-wire types always use Chat Completions (never the Responses API)
    with JSON-object mode, matching the wire contract the gateway funnel has
    always sent; ``google`` uses the native Gemini API semantics.
    """
    if resolved.provider_type == "google":
        return _google_model(resolved, transport)
    if resolved.provider_type not in ("openai", "openai_compatible"):
        raise ValueError(
            f"provider type '{resolved.provider_type}' has no chat-model "
            "factory branch (the mock provider never reaches the factory)"
        )
    openai_wire = is_openai_wire(resolved.provider_type, resolved.base_url)
    kwargs: dict[str, Any] = {
        "model": resolved.model_name,
        "api_key": resolved.api_key or _KEYLESS_API_KEY,
        "base_url": resolved.base_url,
        "timeout": settings.AI_TIMEOUT,
        # None (unset) omits temperature from the payload — modern OpenAI
        # reasoning models reject any non-default value.
        "temperature": resolved.temperature,
        "max_retries": 0,
        "use_responses_api": False,
        "stream_usage": True,
        "model_kwargs": {"response_format": {"type": "json_object"}},
    }
    if resolved.max_tokens is not None:
        # The provider-type split lives here: OpenAI wants the modern
        # parameter name, compatible endpoints the classic one.
        if openai_wire:
            kwargs["max_completion_tokens"] = resolved.max_tokens
        else:
            kwargs["max_tokens"] = resolved.max_tokens
    if resolved.reasoning_effort:
        # First-class field on BaseChatOpenAI (included by _default_params,
        # which CompatibleChatOpenAI also inherits); only sent when set.
        kwargs["reasoning_effort"] = resolved.reasoning_effort
    if transport is not None:
        kwargs["http_async_client"] = httpx.AsyncClient(
            transport=transport, timeout=settings.AI_TIMEOUT
        )
    cls = ChatOpenAI if openai_wire else CompatibleChatOpenAI
    return cls(**kwargs)


def build_embedding_model(
    resolved: "ResolvedModel",
    transport: Optional[httpx.AsyncBaseTransport] = None,
) -> "OpenAIEmbeddings":
    """Build the LangChain embeddings model for a resolved provider/model.

    OpenAI-wire only: the google branch is chat-only (no
    ``GoogleGenerativeAIEmbeddings`` branch — assign an embeddings-capable
    OpenAI/OpenAI-compatible model to the embed task). The mock provider
    never reaches the factory (the gateway synthesizes deterministic
    vectors).
    """
    if resolved.provider_type not in ("openai", "openai_compatible"):
        raise ValueError(
            f"provider type '{resolved.provider_type}' has no embeddings "
            "factory branch — google is chat-only; assign an "
            "embeddings-capable OpenAI/OpenAI-compatible model to the "
            "embed task (the mock provider never reaches the factory)"
        )
    kwargs: dict[str, Any] = {
        "model": resolved.model_name,
        "api_key": resolved.api_key or _KEYLESS_API_KEY,
        "base_url": resolved.base_url,
        "timeout": settings.AI_TIMEOUT,
        "max_retries": 0,
        # Ollama-class endpoints don't serve the tiktoken offline checks.
        "check_embedding_ctx_length": False,
    }
    if transport is not None:
        kwargs["http_async_client"] = httpx.AsyncClient(
            transport=transport, timeout=settings.AI_TIMEOUT
        )
    return OpenAIEmbeddings(**kwargs)
