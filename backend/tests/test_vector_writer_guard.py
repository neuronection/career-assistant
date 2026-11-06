"""Writer guard wall (plan 50 §4, blocker 6).

A resolved embedding configuration must match the target space before any
vector is written: a settings change cannot silently mix models,
dimensions, normalization or asymmetric prefixes in one space.
"""

from __future__ import annotations

import pytest

from app.storage import vector_contract as vc
from app.storage.vector_backends import (
    ResolvedEmbedding,
    VectorSpaceMismatch,
    assert_writer_matches_space,
    writer_mismatch_reason,
)

SPACE = vc.VectorSpace(
    name="content",
    provider="openai",
    model="text-embedding-3-small",
    dim=1536,
    normalize=True,
    query_prefix=None,
    document_prefix=None,
)


def test_matching_configuration_passes():
    resolved = ResolvedEmbedding(
        provider="openai", model="text-embedding-3-small", dim=1536, normalize=True
    )
    assert writer_mismatch_reason(SPACE, resolved) is None
    assert_writer_matches_space(SPACE, resolved)


def test_case_and_whitespace_do_not_split_a_space():
    resolved = ResolvedEmbedding(
        provider=" OpenAI ", model="Text-Embedding-3-Small", dim=1536, normalize=True
    )
    assert writer_mismatch_reason(SPACE, resolved) is None


def test_none_and_empty_prefix_are_equivalent():
    resolved = ResolvedEmbedding(
        provider="openai",
        model="text-embedding-3-small",
        dim=1536,
        normalize=True,
        query_prefix="",
        document_prefix="  ",
    )
    assert writer_mismatch_reason(SPACE, resolved) is None


@pytest.mark.parametrize(
    "resolved",
    [
        ResolvedEmbedding(provider="ollama", model="text-embedding-3-small", dim=1536),
        ResolvedEmbedding(provider="openai", model="text-embedding-3-large", dim=1536),
        ResolvedEmbedding(provider="openai", model="text-embedding-3-small", dim=1024),
        ResolvedEmbedding(
            provider="openai", model="text-embedding-3-small", dim=1536, normalize=False
        ),
        ResolvedEmbedding(
            provider="openai",
            model="text-embedding-3-small",
            dim=1536,
            query_prefix="query: ",
        ),
        ResolvedEmbedding(
            provider="openai",
            model="text-embedding-3-small",
            dim=1536,
            document_prefix="passage: ",
        ),
    ],
)
def test_any_semantic_mismatch_is_refused(resolved):
    with pytest.raises(VectorSpaceMismatch) as raised:
        assert_writer_matches_space(SPACE, resolved)
    assert raised.value.degraded == vc.DegradedReason.SPACE_MISMATCH
    assert writer_mismatch_reason(SPACE, resolved) is not None


def test_asymmetric_prefix_roles_are_guarded():
    asymmetric = vc.VectorSpace(
        name="content",
        provider="intfloat",
        model="e5-large-v2",
        dim=1024,
        query_prefix="query: ",
        document_prefix="passage: ",
    )
    matching = ResolvedEmbedding(
        provider="intfloat",
        model="e5-large-v2",
        dim=1024,
        query_prefix="query: ",
        document_prefix="passage: ",
    )
    assert_writer_matches_space(asymmetric, matching)

    swapped = ResolvedEmbedding(
        provider="intfloat",
        model="e5-large-v2",
        dim=1024,
        query_prefix="passage: ",
        document_prefix="query: ",
    )
    with pytest.raises(VectorSpaceMismatch):
        assert_writer_matches_space(asymmetric, swapped)
