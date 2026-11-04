"""Tokenizer registry and counting service (plan 52 T1-min).

Exact bundled ``tiktoken`` for the curated OpenAI embedding models, a
labelled conservative fallback for everything else, and the read-only shadow
measurements built on top. No write path imports this package yet: plan 52
T3 adds token-aware chunking and the space-key fold.
"""

from app.ai.tokenizers.service import (
    CL100K_BASE,
    FALLBACK_IDENTIFIER,
    FALLBACK_MAX_INPUT_TOKENS,
    OPENAI_EMBEDDING_MAX_INPUT_TOKENS,
    EmbeddingModelProfile,
    TokenCount,
    TokenizerService,
    TokenizerUnavailable,
    fallback_spec,
    get_tokenizer_service,
    provider_class,
    resolve_embedding_profile,
    resolve_tokenizer_spec,
    tiktoken_spec,
)

__all__ = [
    "CL100K_BASE",
    "FALLBACK_IDENTIFIER",
    "FALLBACK_MAX_INPUT_TOKENS",
    "OPENAI_EMBEDDING_MAX_INPUT_TOKENS",
    "EmbeddingModelProfile",
    "TokenCount",
    "TokenizerService",
    "TokenizerUnavailable",
    "fallback_spec",
    "get_tokenizer_service",
    "provider_class",
    "resolve_embedding_profile",
    "resolve_tokenizer_spec",
    "tiktoken_spec",
]
