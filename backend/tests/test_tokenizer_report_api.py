"""The read-only tokenizer/limits report API (plan 52 T1-min)."""

from __future__ import annotations

import json

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
        "chunking",
        "reference",
        "corpus",
        "shadow",
    }
    assert body["tokenizer"]["kind"] in ("tiktoken", "heuristic")
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
