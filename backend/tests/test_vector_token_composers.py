"""Token-aware composers (plan 52 T3b).

Every embeddable view splits by token ids with exact character offsets,
token overlap and a hard ``max_chars`` ceiling. The legacy character
composers stay untouched; an item that cannot fit is a typed
``input_too_long`` write failure, never a truncation.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.ai.tokenizers import TokenizerService, resolve_tokenizer_spec
from app.services.vector_composers import (
    InputTooLong,
    chunk_tokens,
    compose_posting_views,
    compose_token_records,
)
from app.storage.tokenizer_contract import ChunkConfig, TokenizerKind, TokenizerSpec

REFERENCE = (
    Path(__file__).resolve().parents[1] / "app" / "data" / "tokenizers" / "reference_corpus.json"
)


def _samples() -> list[dict]:
    return json.loads(REFERENCE.read_text(encoding="utf-8"))["samples"]


def _spec() -> TokenizerSpec:
    return resolve_tokenizer_spec("openai_compatible", "text-embedding-3-small")


def _heuristic() -> TokenizerSpec:
    return TokenizerSpec(
        kind=TokenizerKind.HEURISTIC,
        identifier="utf8-heuristic-v1",
        max_input_tokens=2048,
        source="fallback",
    )


def _posting(*, skills: int = 8, responsibilities: int = 8, body: str = "") -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.UUID(int=11),
        title="Senior Backend Engineer " * 6,
        org="ACME International " * 4,
        raw={"description": body or "Build reliable distributed services. " * 200},
        extract={
            "skills": [
                {
                    "raw_label": f"skill-{index} with a deliberately descriptive label",
                    "priority": "must_have" if index % 2 else "nice_to_have",
                    "required_level": index % 9,
                }
                for index in range(skills)
            ],
            "responsibilities": [
                {
                    "text": f"Own responsibility number {index} end to end across teams",
                    "time_pct": 10,
                }
                for index in range(responsibilities)
            ],
            "prerequisites": [{"label": "Fluent English"}],
        },
    )


def test_token_chunks_round_trip_exact_offsets_for_every_language():
    service = TokenizerService()
    spec = _spec()
    chunk = ChunkConfig(max_chunk_tokens=48, overlap_tokens=8, max_chars=2000)
    for row in _samples():
        text = row["text"]
        chunks = chunk_tokens(text, tokenizer=spec, chunk=chunk, service=service)
        assert chunks, row["language"]
        assert chunks[0].token_start == 0
        assert chunks[-1].token_end == service.count(spec, text)
        for chunk_row in chunks:
            assert text[chunk_row.char_start : chunk_row.char_end] == chunk_row.text
            assert chunk_row.token_count == chunk_row.token_end - chunk_row.token_start
            assert len(chunk_row.text) <= chunk.max_chars
        if len(chunks) > 1:
            assert chunks[1].token_start < chunks[0].token_end, "token windows overlap"
            assert chunks[1].char_start <= chunks[0].char_end, "character windows overlap"


def test_all_embeddable_views_split_and_keep_exact_char_offsets():
    service = TokenizerService()
    spec = _spec()
    chunk = ChunkConfig(max_chunk_tokens=32, overlap_tokens=4, max_chars=64)
    composed = compose_posting_views(_posting())
    tokenized = compose_token_records(composed, tokenizer=spec, chunk=chunk, service=service)

    assert {record.view for record in tokenized.records} == {
        record.view for record in composed.records
    }
    for view in composed.views:
        records = [record for record in tokenized.records if record.view == view]
        if not composed.views[view].strip():
            assert records == []
            continue
        assert records, view
        for record in records:
            assert record.token_count is not None
            assert record.token_count == record.token_end - record.token_start
            assert record.char_start is not None and record.char_end is not None
            assert composed.views[view][record.char_start : record.char_end] == record.text
            assert len(record.text) <= chunk.max_chars
            assert record.text_ref is not None
    summary_records = [record for record in tokenized.records if record.view == "summary"]
    assert len(summary_records) > 1, "an oversized short view is split, not truncated"


def test_char_ceiling_never_truncates():
    service = TokenizerService()
    spec = _spec()
    chunk = ChunkConfig(max_chunk_tokens=32, overlap_tokens=4, max_chars=40)
    text = "word " * 120
    chunks = chunk_tokens(text, tokenizer=spec, chunk=chunk, service=service)
    assert len(chunks) > 1
    for chunk_row in chunks:
        assert len(chunk_row.text) <= 40
        assert text[chunk_row.char_start : chunk_row.char_end] == chunk_row.text
    assert max(row.char_end for row in chunks) >= len(text.rstrip()) - 4


def test_a_single_item_that_cannot_fit_raises_input_too_long():
    service = TokenizerService()
    spec = _spec()
    chunk = ChunkConfig(max_chunk_tokens=32, overlap_tokens=0, max_chars=1)
    with pytest.raises(InputTooLong) as raised:
        chunk_tokens("hello", tokenizer=spec, chunk=chunk, service=service, view="summary")
    assert raised.value.reason == "input_too_long"
    assert raised.value.view == "summary"


def test_the_heuristic_fallback_chunks_but_stays_labelled():
    service = TokenizerService()
    spec = _heuristic()
    chunk = ChunkConfig(max_chunk_tokens=64, overlap_tokens=8, max_chars=200)
    text = "Αναζητούμε έμπειρο μηχανικό λογισμικού. " * 20
    chunks = chunk_tokens(text, tokenizer=spec, chunk=chunk, service=service)
    assert len(chunks) > 1
    assert spec.exact is False
    for row in chunks:
        assert text[row.char_start : row.char_end] == row.text
        assert row.token_count == row.token_end - row.token_start
        assert len(row.text) <= chunk.max_chars


def test_token_records_change_the_source_hash():
    service = TokenizerService()
    spec = _spec()
    chunk = ChunkConfig(max_chunk_tokens=32, overlap_tokens=4, max_chars=64)
    composed = compose_posting_views(_posting())
    tokenized = compose_token_records(composed, tokenizer=spec, chunk=chunk, service=service)
    assert tokenized.source_hash != composed.source_hash
    assert (
        tokenized.source_hash
        == compose_token_records(composed, tokenizer=spec, chunk=chunk, service=service).source_hash
    )
