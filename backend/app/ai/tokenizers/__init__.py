"""Tokenizer registry and counting service (plan 52 T1-min, T2a, T4).

Exact bundled ``tiktoken`` for the curated OpenAI embedding models, a
labelled conservative fallback for everything else, and the read-only shadow
measurements built on top. Plan 52 T2a adds the persisted admin profile
override and the model/batch/chunk defaults behind the same precedence:
admin → curated → fallback. Token-aware chunking and the space-key fold
remain plan 52 T3; plan 52 T4 uses the service as the interim token
accounting source for live indexing progress (counts only).
"""

from app.ai.tokenizers.registry import (
    CURATED_EMBEDDING_PROFILES,
    CURATED_OPENAI_MODELS,
    EmbeddingModelProfile,
    curated_profile,
    fallback_profile,
    resolve_embedding_profile,
    resolve_tokenizer_spec,
)
from app.ai.tokenizers.service import (
    CL100K_BASE,
    FALLBACK_IDENTIFIER,
    FALLBACK_MAX_INPUT_TOKENS,
    OPENAI_EMBEDDING_MAX_INPUT_TOKENS,
    TokenCount,
    TokenizerService,
    TokenizerUnavailable,
    fallback_spec,
    get_tokenizer_service,
    provider_class,
    tiktoken_spec,
)

__all__ = [
    "CL100K_BASE",
    "CURATED_EMBEDDING_PROFILES",
    "CURATED_OPENAI_MODELS",
    "FALLBACK_IDENTIFIER",
    "FALLBACK_MAX_INPUT_TOKENS",
    "OPENAI_EMBEDDING_MAX_INPUT_TOKENS",
    "EmbeddingModelProfile",
    "TokenCount",
    "TokenizerService",
    "TokenizerUnavailable",
    "curated_profile",
    "fallback_profile",
    "fallback_spec",
    "get_tokenizer_service",
    "provider_class",
    "resolve_embedding_profile",
    "resolve_tokenizer_spec",
    "tiktoken_spec",
]
