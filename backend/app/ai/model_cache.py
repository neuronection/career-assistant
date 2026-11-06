"""Process-local cache of built embedding clients (plan 201 S2).

Every ``embed_texts`` call used to construct a fresh ``OpenAIEmbeddings``,
which builds its own ``httpx.AsyncClient`` + ``openai.AsyncOpenAI`` in
``validate_environment`` — a new connection pool (and TLS handshake) per
request. The object is parameter-free once resolved, so one instance per
``(provider, base_url, model, key, timeout)`` is safe to share.

Rules:

- The cache is bounded and evicts least-recently-used entries, closing the
  clients it drops.
- An injected transport (tests) bypasses the cache entirely: a shared client
  must never carry a mock transport into another test.
- Keys carry a digest of the API key, never the key itself.
- ``clear_embedding_models`` is the test seam (an autouse fixture calls it).
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import threading
from collections import OrderedDict
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)

MAX_EMBEDDING_MODELS = 8

_cache: OrderedDict[tuple[str, ...], Any] = OrderedDict()
_lock = threading.Lock()
#: In-flight async-client closes, kept referenced until they finish (RUF006).
_closing_tasks: set[asyncio.Task[None]] = set()


def _key_digest(api_key: str | None) -> str:
    """A short, stable digest — ``sha256("")`` for keyless endpoints."""
    return hashlib.sha256((api_key or "").encode("utf-8")).hexdigest()[:16]


def embedding_model_key(resolved: Any) -> tuple[str, ...]:
    """The cache identity of one resolved embedding model."""
    return (
        str(getattr(resolved, "provider_type", "") or ""),
        str(getattr(resolved, "base_url", "") or ""),
        str(getattr(resolved, "model_name", "") or ""),
        _key_digest(getattr(resolved, "api_key", None)),
        str(int(getattr(settings, "ai_timeout", 0) or 0)),
    )


def get_embedding_model(resolved: Any, transport: Any = None) -> Any:
    """The cached embeddings model for a resolved provider/model."""
    from app.ai.chat_models import build_embedding_model

    if transport is not None:
        return build_embedding_model(resolved, transport=transport)
    key = embedding_model_key(resolved)
    with _lock:
        cached = _cache.get(key)
        if cached is not None:
            _cache.move_to_end(key)
            return cached
    model = build_embedding_model(resolved)
    with _lock:
        _cache[key] = model
        _cache.move_to_end(key)
        while len(_cache) > MAX_EMBEDDING_MODELS:
            _, evicted = _cache.popitem(last=False)
            _close_quietly(evicted)
    return model


def clear_embedding_models() -> None:
    """Drop every cached model (test isolation; also a config-change escape)."""
    with _lock:
        while _cache:
            _, model = _cache.popitem(last=False)
            _close_quietly(model)


def _close_quietly(model: Any) -> None:
    """Close the clients a dropped model owns, never raising.

    ``OpenAI.close`` is sync and ``AsyncOpenAI.close`` is a coroutine, so the
    close runs on whatever thread/loop we are on: sync inline, async as a
    tracked task (never an un-awaited coroutine).
    """
    import inspect

    for attribute in ("client", "async_client"):
        client = getattr(model, attribute, None)
        if client is None:
            continue
        closer = getattr(client, "aclose", None) or getattr(client, "close", None)
        if not callable(closer):
            continue
        if inspect.iscoroutinefunction(closer):
            _schedule_close(closer)
            continue
        try:
            closer()
        except Exception:
            logger.debug("embedding client close failed", exc_info=True)


def _schedule_close(acloser: Any) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    try:
        task = loop.create_task(acloser())
    except Exception:
        logger.debug("embedding async client close failed", exc_info=True)
        return
    _closing_tasks.add(task)
    task.add_done_callback(_closing_tasks.discard)


def cached_embedding_models() -> int:
    """How many models the process holds (tests and diagnostics)."""
    with _lock:
        return len(_cache)


__all__ = [
    "MAX_EMBEDDING_MODELS",
    "cached_embedding_models",
    "clear_embedding_models",
    "embedding_model_key",
    "get_embedding_model",
]
