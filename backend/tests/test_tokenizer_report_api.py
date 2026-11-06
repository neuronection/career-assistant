"""The read-only tokenizer/limits report API (plan 52 T1-min)."""

from __future__ import annotations

import json
import socket

from app.models.vector_model import VectorSpace as VectorSpaceRow
from app.services import tokenizer_report
from app.storage import retrieval_ops as ops

PATH = "/api/v1/admin/retrieval/tokenizer"


async def test_report_returns_tokenizer_limits_and_reference_aggregates(client, auth_headers):
    response = await client.get(PATH, headers=auth_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["state"] in ("ok", "unconfigured")
    assert set(body) == {
        "state",
        "model",
        "tokenizer",
        "profile",
        "chunking",
        "reference",
        "corpus",
        "shadow",
    }
    assert body["tokenizer"]["kind"] in ("tiktoken", "heuristic")
    assert body["tokenizer"]["source"] in ("curated", "admin", "fallback")
    assert body["profile"]["source"] == body["tokenizer"]["source"]
    assert body["profile"]["batch_max_items"] > 0
    assert body["profile"]["batch_max_tokens"] > 0
    assert body["profile"]["chunk"]["max_chunk_tokens"] > 0
    assert body["profile"]["chunk"]["overlap_tokens"] >= 0
    assert body["profile"]["chunk"]["max_chars"] > 0
    assert body["profile"]["max_input_tokens"] == body["tokenizer"]["max_input_tokens"]
    assert isinstance(body["tokenizer"]["exact"], bool)
    assert body["tokenizer"]["max_input_tokens"] > 0
    assert body["chunking"]["max_chunk_chars"] == 1600
    assert body["chunking"]["overlap_chars"] == 240
    assert body["chunking"]["token_aware"] is False
    assert body["shadow"] == {"writes": False}
    assert body["reference"]["state"] == "ok"
    assert len(body["reference"]["samples"]) == 5
    assert body["reference"]["total_tokens"] > 0
    assert body["corpus"]["state"] in ("ok", "empty")
    assert "SECRET" not in json.dumps(body)
    assert "Senior backend engineer" not in json.dumps(body), "reference text never leaves"
    ops.assert_no_raw_text(body)


async def test_report_claims_token_aware_only_for_a_token_aware_active_space(
    client, db, auth_headers
):
    active = VectorSpaceRow(
        name="content",
        provider="openai",
        model="text-embedding-3-small",
        dim=1536,
        metric="cosine",
        normalize=True,
        chunker_version="2",
        composer_version="1",
        status="active",
        tokenizer_kind="tiktoken",
        tokenizer_identifier="cl100k_base",
        tokenizer_artifact_sha256="a" * 64,
        tokenizer_exact=True,
        tokenizer_source="curated",
        max_input_tokens=8191,
        chunk_max_tokens=256,
        chunk_overlap_tokens=32,
        chunk_max_chars=1200,
    )
    db.add(active)
    await db.commit()

    body = (await client.get(PATH, headers=auth_headers)).json()
    assert body["chunking"]["token_aware"] is True
    assert body["chunking"]["view"] == "all views"
    assert body["chunking"]["chunker_version"] == "2"
    assert body["chunking"]["max_chunk_tokens"] == 256
    assert body["chunking"]["overlap_tokens"] == 32
    assert body["chunking"]["max_chunk_chars"] == 1200
    assert body["chunking"]["tokenizer_source"] == "curated"
    assert body["shadow"] == {"writes": False}


async def test_tokenizer_read_paths_make_no_network_call(monkeypatch, client, auth_headers):
    """A curated HF profile is resolved/read without fetching on the request path."""

    def forbidden(*args, **kwargs):  # pragma: no cover - the assertion is the raise
        raise AssertionError("a tokenizer read path attempted a network call")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)

    preview = await client.get(
        "/api/v1/admin/retrieval/model-profiles",
        params={"provider": "openai_compatible", "model": "nomic-embed-text"},
        headers=auth_headers,
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["resolution"]["tokenizer_kind"] == "hf_tokenizers"

    report = await client.get(PATH, headers=auth_headers)
    assert report.status_code == 200, report.text


async def test_report_is_bounded_by_kind_and_limit(client, auth_headers):
    response = await client.get(PATH, params={"kinds": "posting", "limit": 1}, headers=auth_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert [row["kind"] for row in body["corpus"]["kinds"]] == ["posting"]
    assert body["corpus"]["limit_per_kind"] == 1
    assert body["corpus"]["documents"] <= 1


async def test_report_rejects_unknown_kinds_and_out_of_range_limits(client, auth_headers):
    unknown = await client.get(PATH, params={"kinds": "planet"}, headers=auth_headers)
    assert unknown.status_code == 400
    too_large = await client.get(
        PATH, params={"limit": tokenizer_report.MAX_CORPUS_LIMIT + 1}, headers=auth_headers
    )
    assert too_large.status_code == 422
