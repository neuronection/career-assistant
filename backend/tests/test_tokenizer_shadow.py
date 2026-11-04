"""Shadow token counts and the read-only tokenizer report (plan 52 T1-min).

The shadow path composes the existing char views/records, counts tokens and
returns aggregates only. These tests pin the arithmetic, the multilingual
mismatch, the bounded corpus scan and the no-raw-text rule.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from app.ai.tokenizers import (
    TokenizerService,
    resolve_embedding_profile,
    resolve_tokenizer_spec,
)
from app.services import tokenizer_report
from app.services.vector_composers import (
    BODY_CHUNK_CHARS,
    BODY_CHUNK_OVERLAP_CHARS,
    ComposedDocument,
    ComposedRecord,
    chunk_text,
)
from app.services.vector_index_service import LoadedSource, SourceRow
from app.storage import retrieval_ops as ops

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "tokenizer_tiktoken.fixtures.json"


def _expected_counts() -> dict[str, int]:
    payload = json.loads(FIXTURES.read_text(encoding="utf-8"))
    return {row["language"]: row["tokens"] for row in payload["samples"]}


def _records() -> list[ComposedRecord]:
    body = " ".join(f"paragraph{index}" for index in range(400))
    return [
        ComposedRecord(view="summary", text="Backend engineer at ACME"),
        *[
            ComposedRecord(
                view="body",
                text=chunk.text,
                chunk_index=index,
                char_start=chunk.char_start,
                char_end=chunk.char_end,
            )
            for index, chunk in enumerate(chunk_text(body))
        ],
    ]


def test_measure_records_reports_per_view_and_total_aggregates():
    service = TokenizerService()
    spec = resolve_tokenizer_spec("openai_compatible", "text-embedding-3-small")
    report = tokenizer_report.measure_records(_records(), spec=spec, service=service)
    views = {row["view"]: row for row in report["views"]}
    assert set(views) == {"body", "summary"}
    assert views["summary"]["records"] == 1
    assert views["summary"]["chars"] == len("Backend engineer at ACME")
    assert views["body"]["records"] >= 2
    total = report["totals"]
    assert total["records"] == len(_records())
    assert total["tokens"] == sum(row["tokens"] for row in views.values())
    assert total["exact"] is True
    assert total["chars_per_token"] > 0
    assert total["max_record_tokens"] <= spec.max_input_tokens
    ops.assert_no_raw_text(report)


def test_current_char_chunks_have_a_language_dependent_token_spread():
    """The T1-min evidence: 1600/240 chars is not a language-neutral budget."""
    service = TokenizerService()
    spec = resolve_tokenizer_spec("openai_compatible", "text-embedding-3-small")
    samples = json.loads(
        (
            Path(__file__).resolve().parents[1] / "app/data/tokenizers/reference_corpus.json"
        ).read_text(encoding="utf-8")
    )["samples"]
    by_language = {row["language"]: row["text"] for row in samples}
    maxima: dict[str, int] = {}
    for language in ("english", "greek", "german", "cjk"):
        # Repeat the synthetic sample to a realistic posting length.
        text = (by_language[language] * 40)[:5000]
        counts = [service.count(spec, chunk.text) for chunk in chunk_text(text)]
        maxima[language] = max(counts)
        assert all(count < spec.max_input_tokens for count in counts), language
    assert maxima["english"] < 512
    assert maxima["german"] < 512
    assert maxima["greek"] > 512, "a 1600-char Greek chunk already exceeds a 512-token target"
    assert maxima["cjk"] > 4 * maxima["english"], "CJK costs far more tokens per character"


def test_measure_reference_exposes_the_multilingual_mismatch():
    service = TokenizerService()
    spec = resolve_tokenizer_spec("openai_compatible", "text-embedding-3-small")
    report = tokenizer_report.measure_reference(spec=spec, service=service)
    expected = _expected_counts()
    assert report["state"] == "ok"
    assert report["exact"] is True
    by_language = {row["language"]: row for row in report["samples"]}
    assert set(by_language) == set(expected)
    for language, tokens in expected.items():
        assert by_language[language]["tokens"] == tokens, language
    # The same character budget costs very different token budgets.
    assert by_language["greek"]["chars_per_token"] < by_language["english"]["chars_per_token"]
    assert by_language["cjk"]["chars_per_token"] < by_language["english"]["chars_per_token"]
    ops.assert_no_raw_text(report)


def test_reference_heuristic_is_visibly_approximate_and_still_counted():
    service = TokenizerService()
    spec = resolve_embedding_profile("openai_compatible", "nomic-embed-text").tokenizer
    report = tokenizer_report.measure_reference(spec=spec, service=service)
    assert report["exact"] is False
    assert all(row["tokens"] > 0 for row in report["samples"])
    ops.assert_no_raw_text(report)


async def test_corpus_scan_is_bounded_and_never_reports_text(monkeypatch, caplog):
    service = TokenizerService()
    spec = resolve_tokenizer_spec("openai_compatible", "text-embedding-3-small")
    secret = "SECRET-DOCUMENT-TEXT that must never reach the report or a log"

    async def fake_list_sources(db, kind, *, since=None, after=None, limit=None):
        return [SourceRow(source_id=f"{kind}-1"), SourceRow(source_id=f"{kind}-2")]

    async def fake_load_source(db, kind, source_id):
        composed = ComposedDocument(
            kind=kind,
            source_id=source_id,
            views={"body": secret},
            records=(ComposedRecord(view="body", text=secret),),
        )
        return LoadedSource(composed=composed, scope_type="global")

    monkeypatch.setattr(tokenizer_report, "list_sources", fake_list_sources)
    monkeypatch.setattr(tokenizer_report, "load_source", fake_load_source)
    with caplog.at_level("INFO"):
        report = await tokenizer_report.measure_corpus(
            None, spec=spec, service=service, kinds=("posting",), limit_per_kind=2
        )
    assert report["state"] == "ok"
    assert report["documents"] == 2
    assert report["records"] == 2
    assert report["kinds"][0]["kind"] == "posting"
    assert report["tokens"] > 0
    payload = json.dumps(report)
    assert secret not in payload
    assert secret not in caplog.text
    ops.assert_no_raw_text(report)


async def test_build_report_pins_current_char_chunk_config(db, monkeypatch):
    service = TokenizerService()

    async def resolved(*args, **kwargs):
        return _resolved()

    monkeypatch.setattr(tokenizer_report.resolution, "resolve_task_model", resolved)
    report = await tokenizer_report.build_report(
        db, service=service, kinds=("posting",), limit_per_kind=1
    )
    assert report["state"] == "ok"
    assert report["model"] == {
        "provider": "openai_compatible",
        "model": "text-embedding-3-small",
        "max_input_assumed": False,
    }
    assert report["tokenizer"]["identifier"] == "cl100k_base"
    assert report["tokenizer"]["exact"] is True
    assert report["tokenizer"]["max_input_tokens"] == 8191
    assert report["chunking"] == {
        "view": "body",
        "max_chunk_chars": BODY_CHUNK_CHARS,
        "overlap_chars": BODY_CHUNK_OVERLAP_CHARS,
        "chunker_version": "1",
        "composer_version": "1",
        "token_aware": False,
    }
    assert report["shadow"] == {"writes": False}
    assert report["reference"]["state"] == "ok"
    assert report["corpus"]["state"] in ("ok", "empty")
    ops.assert_no_raw_text(report)


async def test_build_report_falls_back_visibly_when_unconfigured(db, monkeypatch):
    service = TokenizerService()

    async def unresolved(*args, **kwargs):
        return None

    monkeypatch.setattr(tokenizer_report.resolution, "resolve_task_model", unresolved)
    report = await tokenizer_report.build_report(
        db, service=service, kinds=("posting",), limit_per_kind=1
    )
    assert report["state"] == "unconfigured"
    assert report["model"]["provider"] == "unconfigured"
    assert report["tokenizer"]["kind"] == "heuristic"
    assert report["tokenizer"]["exact"] is False
    assert report["tokenizer"]["source"] == "fallback"
    assert report["reference"]["exact"] is False
    ops.assert_no_raw_text(report)


def _resolved():
    return SimpleNamespace(provider_type="openai_compatible", model_name="text-embedding-3-small")
