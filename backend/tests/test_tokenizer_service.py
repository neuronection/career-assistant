"""Tokenizer service/registry (plan 52 T1-min): exact, fallback, offline, cached."""

from __future__ import annotations

import hashlib
import json
import socket
from pathlib import Path

import pytest

from app.ai.tokenizers import (
    CL100K_BASE,
    FALLBACK_IDENTIFIER,
    FALLBACK_MAX_INPUT_TOKENS,
    HF_TOKENIZER_FILENAME,
    OPENAI_EMBEDDING_MAX_INPUT_TOKENS,
    TokenizerService,
    TokenizerUnavailable,
    fallback_spec,
    hf_tokenizer_spec,
    resolve_embedding_profile,
    resolve_tokenizer_spec,
)
from app.ai.tokenizers.service import (
    CL100K_BASE_ASSET,
    DEFAULT_ASSET_DIR,
    MAX_TOKENIZER_JSON_BYTES,
)
from app.storage import tokenizer_contract as tc

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "tokenizer_tiktoken.fixtures.json"
HF_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "tokenizer_hf_wordlevel.json"
REFERENCE = (
    Path(__file__).resolve().parents[1] / "app" / "data" / "tokenizers" / "reference_corpus.json"
)


def _hf_fixture_bytes() -> bytes:
    return HF_FIXTURE.read_bytes()


def _hf_fixture_sha() -> str:
    return hashlib.sha256(_hf_fixture_bytes()).hexdigest()


def _hf_spec(**overrides) -> tc.TokenizerSpec:
    payload = {
        "identifier": "fixture/wordlevel",
        "revision": "0123456789abcdef0123456789abcdef01234567",
        "artifact_sha256": _hf_fixture_sha(),
        "max_input_tokens": 512,
        "source": "curated",
    }
    payload.update(overrides)
    return hf_tokenizer_spec(**payload)


def _write_hf_cache(cache_dir: Path, payload: bytes, *, sha: str | None = None) -> str:
    digest = sha or hashlib.sha256(payload).hexdigest()
    target = cache_dir / digest / HF_TOKENIZER_FILENAME
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    return digest


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
        ("openai_compatible", "unknown-embed-9000"),
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


def test_sentencepiece_is_explicitly_unsupported():
    sparse = tc.TokenizerSpec(
        kind="sentencepiece",
        identifier="org/model",
        revision="v1",
        artifact_sha256="c" * 64,
        max_input_tokens=512,
        source="admin",
    )
    service = TokenizerService()
    with pytest.raises(TokenizerUnavailable) as error:
        service.count(sparse, "text")
    assert error.value.reason == "unsupported_tokenizer_kind"
    assert service.available(sparse) is False


def test_hf_tokenizer_loads_from_the_content_cache(tmp_path: Path):
    payload = _hf_fixture_bytes()
    spec = _hf_spec()
    _write_hf_cache(tmp_path, payload)
    service = TokenizerService(cache_dir=tmp_path)

    assert service.available(spec) is True
    assert service.count(spec, "hello world") == 2
    assert service.count(spec, "hello unknown") == 2
    ids = service.encode(spec, "hello world")
    assert ids == [2, 3]
    assert service.decode(spec, ids) == "hello world"
    assert service.count_or_fallback(spec, "hello world").exact is True
    assert service.cached_count == 1


def test_hf_tokenizer_missing_asset_degrades_visibly(tmp_path: Path):
    spec = _hf_spec()
    service = TokenizerService(cache_dir=tmp_path)
    assert service.available(spec) is False
    effective, reason = service.effective_spec(spec)
    assert reason == "asset_missing"
    assert effective.kind is tc.TokenizerKind.HEURISTIC
    assert effective.exact is False
    counted = service.count_or_fallback(spec, "hello world")
    assert counted.exact is False
    assert counted.degraded_reason == "asset_missing"


def test_hf_tokenizer_rejects_size_cap_corruption_and_bad_schema(tmp_path: Path):
    oversized = b"x" * (MAX_TOKENIZER_JSON_BYTES + 1)
    oversized_sha = _write_hf_cache(tmp_path, oversized)
    service = TokenizerService(cache_dir=tmp_path)
    with pytest.raises(TokenizerUnavailable) as error:
        service.count(_hf_spec(artifact_sha256=oversized_sha), "text")
    assert error.value.reason == "asset_too_large"

    corrupt = b'{"not": "the expected bytes"}'
    corrupt_sha = _write_hf_cache(tmp_path, corrupt)
    with pytest.raises(TokenizerUnavailable) as error:
        service.count(_hf_spec(artifact_sha256=corrupt_sha), "text")
    assert error.value.reason == "schema_invalid"

    expected = _hf_fixture_sha()
    broken = tmp_path / expected / HF_TOKENIZER_FILENAME
    broken.parent.mkdir(parents=True, exist_ok=True)
    broken.write_bytes(_hf_fixture_bytes() + b"tampered")
    with pytest.raises(TokenizerUnavailable) as error:
        service.count(_hf_spec(), "text")
    assert error.value.reason == "asset_corrupt"


def test_hf_cache_is_bounded_by_the_same_lru(tmp_path: Path):
    payload = _hf_fixture_bytes()
    _write_hf_cache(tmp_path, payload)
    service = TokenizerService(cache_dir=tmp_path, max_cached=1)
    hf = _hf_spec()
    tiktoken = resolve_tokenizer_spec("openai_compatible", "text-embedding-3-small")
    assert service.count(hf, "hello world") == 2
    assert service.cached_count == 1
    assert service.count(tiktoken, "hello world") == 2
    assert service.cached_count == 1
    assert service.count(hf, "hello world") == 2
    assert service.cached_count == 1


def test_exact_counting_makes_no_network_call(monkeypatch, tmp_path: Path):
    def forbidden(*args, **kwargs):  # pragma: no cover - the assertion is the raise
        raise AssertionError("tokenizer service attempted a network call")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    _write_hf_cache(tmp_path, _hf_fixture_bytes())
    service = TokenizerService(cache_dir=tmp_path)
    spec = resolve_tokenizer_spec("openai_compatible", "text-embedding-3-small")
    assert service.count(spec, "offline " * 100) >= 100
    assert service.decode(spec, service.encode(spec, "still offline")) == "still offline"
    hf = _hf_spec()
    assert service.count(hf, "hello world") == 2
    assert service.decode(hf, service.encode(hf, "hello world")) == "hello world"
