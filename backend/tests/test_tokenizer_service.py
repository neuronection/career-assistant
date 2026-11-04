"""Tokenizer service/registry (plan 52 T1-min): exact, fallback, offline, cached."""

from __future__ import annotations

import json
import socket
from pathlib import Path

import pytest

from app.ai.tokenizers import (
    CL100K_BASE,
    FALLBACK_IDENTIFIER,
    FALLBACK_MAX_INPUT_TOKENS,
    OPENAI_EMBEDDING_MAX_INPUT_TOKENS,
    TokenizerService,
    TokenizerUnavailable,
    fallback_spec,
    resolve_embedding_profile,
    resolve_tokenizer_spec,
)
from app.ai.tokenizers.service import CL100K_BASE_ASSET, DEFAULT_ASSET_DIR
from app.storage import tokenizer_contract as tc

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "tokenizer_tiktoken.fixtures.json"
REFERENCE = (
    Path(__file__).resolve().parents[1] / "app" / "data" / "tokenizers" / "reference_corpus.json"
)


def _reference_samples() -> dict[str, dict]:
    payload = json.loads(REFERENCE.read_text(encoding="utf-8"))
    return {row["language"]: row for row in payload["samples"]}


def _expected_counts() -> dict[str, int]:
    payload = json.loads(FIXTURES.read_text(encoding="utf-8"))
    return {row["language"]: row["tokens"] for row in payload["samples"]}


def test_openai_embedding_models_pin_cl100k_exactly():
    for model in ("text-embedding-3-small", "text-embedding-3-large", "text-embedding-ada-002"):
        profile = resolve_embedding_profile("openai_compatible", model)
        assert profile.tokenizer.kind is tc.TokenizerKind.TIKTOKEN
        assert profile.tokenizer.identifier == CL100K_BASE
        assert profile.tokenizer.exact is True
        assert profile.tokenizer.source is tc.TokenizerSource.CURATED
        assert profile.tokenizer.max_input_tokens == OPENAI_EMBEDDING_MAX_INPUT_TOKENS
        assert profile.max_input_assumed is False
        assert profile.chunk.max_chunk_tokens == 512
        assert profile.chunk.overlap_tokens == 64
        assert profile.batch_max_items == 2048
        assert profile.batch_max_tokens > 0
        assert profile.chunk.fits(profile.tokenizer.max_input_tokens)


def test_unknown_and_non_openai_models_are_labelled_fallback():
    for provider, model in (
        ("openai_compatible", "nomic-embed-text"),
        ("openai_compatible", "text-embedding-4-unknown"),
        ("google", "gemini-embedding-2"),
        ("mock", "mock-embed"),
    ):
        spec = resolve_tokenizer_spec(provider, model)
        assert spec.kind is tc.TokenizerKind.HEURISTIC, (provider, model)
        assert spec.identifier == FALLBACK_IDENTIFIER
        assert spec.exact is False
        assert spec.source is tc.TokenizerSource.FALLBACK
        assert spec.max_input_tokens == FALLBACK_MAX_INPUT_TOKENS


def test_exact_counts_match_the_pinned_fixture():
    service = TokenizerService()
    spec = resolve_tokenizer_spec("openai_compatible", "text-embedding-3-small")
    samples = _reference_samples()
    for language, expected in _expected_counts().items():
        actual = service.count(spec, samples[language]["text"])
        assert actual == expected, language


def test_heuristic_is_conservative_for_every_reference_sample():
    service = TokenizerService()
    exact = resolve_tokenizer_spec("openai_compatible", "text-embedding-3-small")
    fallback = fallback_spec()
    for language, row in _reference_samples().items():
        exact_count = service.count(exact, row["text"])
        heuristic = service.count(fallback, row["text"])
        assert heuristic >= exact_count, language
        assert heuristic == tc.heuristic_token_count(row["text"]), language


def test_counts_are_deterministic_and_encoding_round_trips():
    service = TokenizerService()
    spec = resolve_tokenizer_spec("openai_compatible", "text-embedding-3-small")
    text = _reference_samples()["greek"]["text"]
    assert service.count(spec, text) == service.count(spec, text)
    ids = service.encode(spec, text)
    assert service.decode(spec, ids) == text
    with pytest.raises(TokenizerUnavailable):
        service.encode(fallback_spec(), text)


def test_cache_is_bounded_and_keyed_by_spec_identity():
    service = TokenizerService(max_cached=1)
    first = resolve_tokenizer_spec("openai_compatible", "text-embedding-3-small")
    same_encoding_other_limit = tc.TokenizerSpec.from_dict(
        {**first.to_dict(), "max_input_tokens": 4096}
    )
    assert same_encoding_other_limit.cache_key != first.cache_key
    text = _reference_samples()["english"]["text"]
    assert service.count(first, text) == 32
    assert service.cached_count == 1
    assert service.count(same_encoding_other_limit, text) == 32
    assert service.cached_count == 1, "the LRU bound evicts the previous encoder"
    assert service.count(first, text) == 32
    assert service.cached_count == 1


def test_missing_asset_degrades_visibly_and_never_fakes_exactness(tmp_path: Path):
    service = TokenizerService(asset_dir=tmp_path)
    spec = resolve_tokenizer_spec("openai_compatible", "text-embedding-3-small")
    effective, reason = service.effective_spec(spec)
    assert reason == "asset_missing"
    assert effective.kind is tc.TokenizerKind.HEURISTIC
    assert effective.exact is False
    counted = service.count_or_fallback(spec, "Hello world")
    assert counted.exact is False
    assert counted.degraded_reason == "asset_missing"
    with pytest.raises(TokenizerUnavailable):
        service.count(spec, "Hello world")


def test_corrupt_asset_degrades_visibly(tmp_path: Path):
    payload = (DEFAULT_ASSET_DIR / CL100K_BASE_ASSET).read_bytes()
    (tmp_path / CL100K_BASE_ASSET).write_bytes(payload + b"corrupt")
    service = TokenizerService(asset_dir=tmp_path)
    spec = resolve_tokenizer_spec("openai_compatible", "text-embedding-3-small")
    _, reason = service.effective_spec(spec)
    assert reason == "asset_corrupt"
    assert service.count_or_fallback(spec, "Hello").exact is False


def test_hf_and_sentencepiece_are_explicitly_unsupported():
    hf = tc.TokenizerSpec(
        kind="hf_tokenizers",
        identifier="org/model",
        revision="0123456789abcdef0123456789abcdef01234567",
        artifact_sha256="b" * 64,
        max_input_tokens=512,
        source="curated",
    )
    sparse = tc.TokenizerSpec(
        kind="sentencepiece",
        identifier="org/model",
        revision="v1",
        artifact_sha256="c" * 64,
        max_input_tokens=512,
        source="admin",
    )
    service = TokenizerService()
    for spec in (hf, sparse):
        with pytest.raises(TokenizerUnavailable) as error:
            service.count(spec, "text")
        assert error.value.reason == "unsupported_tokenizer_kind"
        assert service.available(spec) is False


def test_exact_counting_makes_no_network_call(monkeypatch):
    def forbidden(*args, **kwargs):  # pragma: no cover - the assertion is the raise
        raise AssertionError("tokenizer service attempted a network call")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    service = TokenizerService()
    spec = resolve_tokenizer_spec("openai_compatible", "text-embedding-3-small")
    assert service.count(spec, "offline " * 100) >= 100
    assert service.decode(spec, service.encode(spec, "still offline")) == "still offline"
