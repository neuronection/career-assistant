"""Tokenizer registry and counting service (plan 52 T1-min, T4 accounting).

Exact bundled ``tiktoken`` for the curated OpenAI embedding models, a
labelled conservative fallback for everything else, and the read-only shadow
measurements built on top. Plan 52 T4 additionally uses the service as the
interim token accounting source for live indexing progress (counts only; no
chunk, space or record write changes). Token-aware chunking and the space-key
fold remain plan 52 T3.
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
