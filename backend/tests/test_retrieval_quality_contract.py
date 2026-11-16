"""Pin the retrieval quality-compare wire keys against the frontend contract.

The admin retrieval API returns untyped dicts, so ``to_dict()`` is the wire
shape and the frontend carries a hand-written TypeScript twin. The shared
field list in ``contracts/retrieval-quality-compare.fields.json`` is consumed
by both this test and ``frontend/src/tests/retrievalQualityContract.test.tsx``;
a rename that skips either side fails one of them.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.storage.retrieval_ops import QualityCompareDTO, QualityQueryResultDTO

CONTRACT_PATH = (
    Path(__file__).resolve().parents[2] / "contracts" / "retrieval-quality-compare.fields.json"
)


def _contract() -> dict[str, list[str]]:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def _compare() -> QualityCompareDTO:
    return QualityCompareDTO(
        baseline_space_id="space-active",
        new_space_id="space-build",
        set_version=3,
        k=5,
        baseline_recall_at_k=0.9,
        baseline_precision_at_k=0.7,
        new_recall_at_k=0.5,
        new_precision_at_k=0.5,
        passed=True,
        queries=(
            QualityQueryResultDTO(
                query_id="gq-1",
                expected_document_ids=("doc-a",),
                retrieved_document_ids=("doc-a",),
                recall_at_k=1.0,
                precision_at_k=1.0,
                passed=True,
            ),
        ),
    )


def test_compare_payload_keys_match_the_shared_contract() -> None:
    contract = _contract()
    payload = _compare().to_dict()

    assert list(payload) == contract["fields"]


def test_compare_query_keys_match_the_shared_contract() -> None:
    contract = _contract()
    payload = _compare().to_dict()

    queries = payload["queries"]
    assert isinstance(queries, list) and queries
    assert list(queries[0]) == contract["query_fields"]
