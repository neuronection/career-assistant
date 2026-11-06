"""Tokenizer registry and counting service (plan 52 T1-min, T2a, T2b, T4).

Exact bundled ``tiktoken`` for the curated OpenAI embedding models, verified
pinned Hugging Face ``tokenizer.json`` assets from the local cache, and a
labelled conservative fallback for everything else. Plan 52 T2a adds the
persisted admin profile override and the model/batch/chunk defaults behind the
same precedence: admin → curated → fallback. Plan 52 T2b adds the HF loader,
its cache/fetch support and provenance-aware open-source presets. Token-aware
chunking and the space-key fold remain plan 52 T3; plan 52 T4 uses the service
as the interim token accounting source for live indexing progress (counts
only).
"""

from app.ai.tokenizers.registry import (
    CURATED_EMBEDDING_PROFILES,
    CURATED_HF_PRESETS,
    CURATED_OPENAI_MODELS,
    UNAVAILABLE_HF_PRESETS,
    CuratedPreset,
    EmbeddingModelProfile,
    curated_profile,
    fallback_profile,
    resolve_embedding_profile,
    resolve_tokenizer_spec,
    unavailable_preset,
)
from app.ai.tokenizers.service import (
    CL100K_BASE,
    FALLBACK_IDENTIFIER,
    FALLBACK_MAX_INPUT_TOKENS,
    HF_CACHE_SUBDIR,
    HF_TOKENIZER_FILENAME,
    MAX_TOKENIZER_JSON_BYTES,
    OPENAI_EMBEDDING_MAX_INPUT_TOKENS,
    TokenCount,
    TokenizerService,
    TokenizerUnavailable,
    default_cache_dir,
    fallback_spec,
    get_tokenizer_service,
    hf_tokenizer_spec,
    provider_class,
    tiktoken_spec,
)

__all__ = [
    "CL100K_BASE",
    "CURATED_EMBEDDING_PROFILES",
    "CURATED_HF_PRESETS",
    "CURATED_OPENAI_MODELS",
    "FALLBACK_IDENTIFIER",
    "FALLBACK_MAX_INPUT_TOKENS",
    "HF_CACHE_SUBDIR",
    "HF_TOKENIZER_FILENAME",
    "MAX_TOKENIZER_JSON_BYTES",
    "OPENAI_EMBEDDING_MAX_INPUT_TOKENS",
    "UNAVAILABLE_HF_PRESETS",
    "CuratedPreset",
    "EmbeddingModelProfile",
    "TokenCount",
    "TokenizerService",
    "TokenizerUnavailable",
    "curated_profile",
    "default_cache_dir",
    "fallback_profile",
    "fallback_spec",
    "get_tokenizer_service",
    "hf_tokenizer_spec",
    "provider_class",
    "resolve_embedding_profile",
    "resolve_tokenizer_spec",
    "tiktoken_spec",
    "unavailable_preset",
]
